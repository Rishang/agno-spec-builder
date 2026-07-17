import asyncio
import json
from typing import Any

import httpx
from agno.tools import Toolkit

# ponytail: per-base locks for SQLite contents_db; semaphore for parallel upserts.
_WRITE_LOCKS: dict[str, asyncio.Lock] = {}
_INGEST_CONCURRENCY = 4
_ADD_TIMEOUT_S = 120
_PROBE_TIMEOUT_S = 15


def _lock(base: str) -> asyncio.Lock:
    return _WRITE_LOCKS.setdefault(base, asyncio.Lock())


def _docs(docs) -> list[dict[str, Any]]:
    return [{"name": d.name, "content": d.content, "meta_data": d.meta_data} for d in docs]


class KnowledgeHubTools(Toolkit):
    """Multi-KB search when an agent's `knowledge:` is a list."""

    def __init__(self, bases: dict[str, Any]):
        self.bases = bases
        lines = [f"- {n}: {kb.description or ''}".rstrip(": ") for n, kb in bases.items()]
        super().__init__(
            name="knowledge_hub",
            tools=[self.search_knowledge_base, self.search_knowledge_bases],
            instructions="Knowledge bases:\n" + "\n".join(lines),
            add_instructions=True,
        )

    async def _asearch(self, base: str, project: str, query: str, max_results: int, filters: dict | None):
        kb = self.bases.get(base)
        if kb is None:
            raise KeyError(base)
        return await kb.asearch(
            query=query,
            max_results=max_results,
            filters={**(filters or {}), "project": project},
        )

    async def search_knowledge_base(
        self, base: str, project: str, query: str, max_results: int = 10, filters: dict | None = None
    ) -> str:
        """Search one knowledge base, scoped to project. Returns JSON docs with meta_data for citations."""
        try:
            docs = await self._asearch(base, project, query, max_results, filters)
        except KeyError:
            return f"Unknown knowledge base {base!r}; available: {list(self.bases)}"
        return json.dumps(_docs(docs))

    async def search_knowledge_bases(
        self,
        bases: list[str],
        project: str,
        query: str,
        max_results: int = 10,
        filters: dict | None = None,
    ) -> str:
        """Search several bases in parallel. Returns JSON {base: [docs...]}. Prefer for first hop."""
        unknown = [b for b in bases if b not in self.bases]
        if unknown:
            return f"Unknown knowledge base(s) {unknown}; available: {list(self.bases)}"

        async def one(name: str):
            return name, _docs(await self._asearch(name, project, query, max_results, filters))

        return json.dumps(dict(await asyncio.gather(*(one(b) for b in bases))))


class KnowledgeWriterTools(Toolkit):
    """Write into named knowledge bases (`tools: [knowledge-writer]`)."""

    def __init__(self, bases: dict[str, Any]):
        self.bases = bases
        super().__init__(
            name="knowledge_writer",
            tools=[self.add_to_knowledge, self.add_repo_paths_to_knowledge],
        )

    async def add_to_knowledge(
        self,
        base: str,
        project: str,
        name: str,
        text: str | None = None,
        url: str | None = None,
        path: str | None = None,
        metadata: dict | None = None,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        upsert: bool = True,
        skip_if_exists: bool = False,
    ) -> str:
        """Add text/url/path to a KB. Prefer url over large text; prefer add_repo_paths for many files.
        Stable `name` + upsert=true; always set metadata source/id/url/title/updated_at."""
        kb = self.bases.get(base)
        if kb is None:
            return f"Unknown knowledge base {base!r}; available: {list(self.bases)}"
        async with _lock(base):
            await kb.add_content_async(
                name=name,
                text_content=text,
                url=url,
                path=path,
                metadata={**(metadata or {}), "project": project},
                include=include,
                exclude=exclude,
                upsert=upsert,
                skip_if_exists=skip_if_exists,
            )
        return f"added {name!r} to {base}"

    async def add_repo_paths_to_knowledge(
        self,
        base: str,
        project: str,
        owner: str,
        repo: str,
        ref: str,
        paths: list[str],
        source: str = "code",
        upsert: bool = True,
    ) -> str:
        """Ingest GitHub files by repo-relative path (~20/call). Skips empty bodies.
        Returns JSON {ok, skipped, failed}."""
        kb = self.bases.get(base)
        if kb is None:
            return f"Unknown knowledge base {base!r}; available: {list(self.bases)}"

        ok: list[str] = []
        skipped: list[str] = []
        failed: list[dict[str, str]] = []
        sem = asyncio.Semaphore(_INGEST_CONCURRENCY)

        async with httpx.AsyncClient(follow_redirects=True, timeout=_PROBE_TIMEOUT_S) as client:

            async def one(rel: str) -> None:
                rel = rel.lstrip("/")
                raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{rel}"
                meta = {
                    "source": source,
                    "path": rel,
                    "updated_at": ref,
                    "project": project,
                    "url": f"https://github.com/{owner}/{repo}/blob/{ref}/{rel}",
                }
                try:
                    r = await client.get(raw)
                    r.raise_for_status()
                    if not r.text.strip():
                        skipped.append(rel)
                        return
                    # ponytail: pass fetched text — avoids a second GET inside add_content_async.
                    async with sem:
                        await asyncio.wait_for(
                            kb.add_content_async(name=rel, text_content=r.text, metadata=meta, upsert=upsert),
                            timeout=_ADD_TIMEOUT_S,
                        )
                    ok.append(rel)
                except TimeoutError:
                    failed.append({"path": rel, "error": f"timed out after {_ADD_TIMEOUT_S}s"})
                except Exception as e:
                    failed.append({"path": rel, "error": str(e)})

            await asyncio.gather(*(one(p) for p in paths))

        return json.dumps({"ok": ok, "skipped": skipped, "failed": failed, "base": base, "count": len(ok)})
