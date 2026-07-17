"""Skill source ABC — remote SKILL.md fetchers for the skill cache."""

from abc import ABC, abstractmethod


class SkillSource(ABC):
    config_key: str

    @abstractmethod
    def fetch(self, source: str) -> list[dict]:
        """Return [{path, content}, ...] SKILL.md blobs for a source key."""

    def catalog_sources(self, raw: dict) -> list[str]:
        """Unique source keys from the config skills section."""
        seen: list[str] = []
        for item in raw.get("skills", []):
            value = item.get(self.config_key) if isinstance(item, dict) else None
            if value and value not in seen:
                seen.append(value)
        return seen
