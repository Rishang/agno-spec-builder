"""Cache contracts and an in-memory cache for remote skills."""

from typing import Protocol

from agno_spec_builder.skills.github import GithubSkillSource, github_skills


class SkillCache(Protocol):
    def resolve(self, source: str) -> list[dict]: ...


class MemorySkillCache:
    """Process-local cache suitable for a standalone builder or tests."""

    def __init__(self, github: GithubSkillSource | None = None) -> None:
        self.github = github or github_skills
        self._files: dict[str, list[dict]] = {}

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


skill_cache = MemorySkillCache()
