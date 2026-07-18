"""GitHub skill source — fetch SKILL.md blobs via codeload tar."""

import asyncio
import io
import os
import tarfile
import urllib.error
import urllib.request

import httpx

from agno_spec_builder.skills.base import SkillSource

_MAX_TAR_BYTES = 50 * 1024 * 1024  # ponytail: hard cap; streamed extraction if repos outgrow it


class GithubSkillSource(SkillSource):
    config_key = "github"

    def fetch(self, source: str) -> list[dict]:
        """Synchronously fetch skill blobs for Agno's required loader contract."""
        return self._extract(source, self._fetch_bytes(source))

    async def afetch(self, source: str) -> list[dict]:
        """Fetch skill blobs without blocking an agent application's event loop."""
        spec, _, ref = source.partition("@")
        owner, repo, *_ = spec.strip("/").split("/")
        url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref or 'HEAD'}"
        headers = {"Authorization": f"Bearer {token}"} if (token := os.getenv("GITHUB_TOKEN")) else {}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ValueError(f"github skill source {source!r}: HTTP {e.response.status_code} fetching {url}") from e
        except httpx.HTTPError as e:
            raise ValueError(f"github skill source {source!r}: fetch failed ({e})") from e
        return await asyncio.to_thread(self._extract, source, response.content)

    @staticmethod
    def _fetch_bytes(source: str) -> bytes:
        spec, _, ref = source.partition("@")
        owner, repo, *_ = spec.strip("/").split("/")
        url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref or 'HEAD'}"
        req = urllib.request.Request(url)
        if token := os.getenv("GITHUB_TOKEN"):  # private repos / rate limits
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read(_MAX_TAR_BYTES + 1)
        except urllib.error.HTTPError as e:
            raise ValueError(f"github skill source {source!r}: HTTP {e.code} fetching {url}") from e
        except OSError as e:
            raise ValueError(f"github skill source {source!r}: fetch failed ({e})") from e
        return data

    @staticmethod
    def _extract(source: str, data: bytes) -> list[dict]:
        spec, *_ = source.partition("@")
        _, _, *sub = spec.strip("/").split("/")
        prefix = "/".join(sub)
        if len(data) > _MAX_TAR_BYTES:
            raise ValueError(f"github skill source {source!r}: tarball exceeds 50MB cap")

        files: list[dict] = []
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar.getmembers():
                rel = member.name.split("/", 1)[1] if "/" in member.name else ""
                if not member.isfile() or not rel.endswith("SKILL.md"):
                    continue
                if prefix and not rel.startswith(prefix + "/"):
                    continue
                fileobj = tar.extractfile(member)
                if fileobj is None:
                    continue
                files.append({"path": rel, "content": fileobj.read().decode()})
        return files


github_skills = GithubSkillSource()
