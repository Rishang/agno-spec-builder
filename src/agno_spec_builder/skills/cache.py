"""Cache contracts and an in-memory cache for remote skills."""

import asyncio
from typing import Protocol

from agno_spec_builder.skills.github import GithubSkillSource, github_skills


class SkillCache(Protocol):
    def resolve(self, source: str) -> list[dict]: ...

    async def aresolve(self, source: str) -> list[dict]: ...


class MemorySkillCache:
    """Process-local cache suitable for a standalone builder or tests."""

    def __init__(self, github: GithubSkillSource | None = None) -> None:
        self.github = github or github_skills
        self._files: dict[str, list[dict]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, source: str) -> list[dict] | None:
        return self._files.get(source)

    def set(self, source: str, files: list[dict]) -> None:
        self._files[source] = files

    def resolve(self, source: str) -> list[dict]:
        files = self.get(source)
        if files is None:
            files = self.github.fetch(source)
            self.set(source, files)
        return files

    async def aresolve(self, source: str) -> list[dict]:
        """Fetch and cache a remote source without blocking the event loop."""
        if (files := self.get(source)) is not None:
            return files
        lock = self._locks.setdefault(source, asyncio.Lock())
        async with lock:
            if (files := self.get(source)) is not None:
                return files
            files = await self.github.afetch(source)
            self.set(source, files)
            return files


skill_cache = MemorySkillCache()
