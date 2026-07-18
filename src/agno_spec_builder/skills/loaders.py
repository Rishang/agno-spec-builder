import asyncio
import re
from typing import Any, ClassVar

import yaml
from agno.skills.errors import SkillValidationError
from agno.skills.loaders.base import SkillLoader
from agno.skills.loaders.local import LocalSkills
from agno.skills.skill import Skill
from agno.skills.validator import validate_metadata

from agno_spec_builder.schemas import SkillConfig
from agno_spec_builder.skills.cache import SkillCache, skill_cache
from agno_spec_builder.utils import log


def _parse_skill_md(content: str) -> tuple[dict[str, Any], str]:
    frontmatter: dict[str, Any] = {}
    instructions = content

    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, re.DOTALL)

    if frontmatter_match:
        frontmatter_text = frontmatter_match.group(1)
        instructions = frontmatter_match.group(2).strip()
        frontmatter = yaml.safe_load(frontmatter_text) or {}

    return frontmatter, instructions


# agno's validator whitelist; lenient mode drops anything else (Claude Code
# skills carry extras like 'argument-hint' that agno rejects).
_ALLOWED_FRONTMATTER = {
    "allowed-tools",
    "compatibility",
    "description",
    "license",
    "metadata",
    "name",
}


def _skill_from_md(content: str, source: str, lenient: bool = False) -> Skill:
    frontmatter, instructions = _parse_skill_md(content)
    if lenient:
        frontmatter = {k: v for k, v in frontmatter.items() if k in _ALLOWED_FRONTMATTER}

    errors = validate_metadata(frontmatter)
    if errors:
        name = frontmatter.get("name", "unknown")
        raise SkillValidationError(f"Skill validation failed for '{name}'", errors=errors)

    return Skill(
        name=frontmatter.get("name", "unnamed-skill"),
        description=frontmatter.get("description", ""),
        instructions=instructions,
        source_path=source,
        metadata=frontmatter.get("metadata"),
        license=frontmatter.get("license"),
        compatibility=frontmatter.get("compatibility"),
        allowed_tools=frontmatter.get("allowed-tools"),
    )


class StringSkills(SkillLoader):
    """Loads skills from SKILL.md content strings."""

    def __init__(self, skills: list[SkillConfig]):
        self.contents = [s.content for s in skills if s.content]

    def load(self) -> list[Skill]:
        skills: list[Skill] = []
        for content in self.contents:
            try:
                skill = _skill_from_md(content, f"inline:{content[:40]}")
            except SkillValidationError:
                raise
            except Exception as e:
                log.warning(f"Error loading skill from string: {e}")
                continue
            skills.append(skill)

        log.debug(f"Loaded {len(skills)} skills from strings")
        return skills


class LocalPathSkills(SkillLoader):
    """Loads skills from local filesystem paths via agno's :class:`LocalSkills`.

    See https://docs.agno.com/skills/loading-skills — a path may point at a single
    skill folder (containing SKILL.md) or a directory of skill folders. Validation
    is disabled so third-party skills with extra frontmatter keys (e.g. Claude
    Code's `argument-hint`) load on a best-effort basis, matching GithubSkills.
    """

    _preloaded: ClassVar[dict[str, list[Skill]]] = {}

    def __init__(self, skills: list[SkillConfig]):
        self.paths = [s.path for s in skills if s.path]

    @classmethod
    async def preload(cls, path: str) -> list[Skill]:
        """Load one local skill path outside the event-loop thread."""
        if path not in cls._preloaded:
            cls._preloaded[path] = await asyncio.to_thread(LocalSkills(path, validate=False).load)
        return cls._preloaded[path]

    @classmethod
    async def apreload(cls, paths: set[str]) -> None:
        """Warm every declared local skill path before an agent can run."""
        path_list = tuple(paths)
        results = await asyncio.gather(*(cls.preload(path) for path in path_list), return_exceptions=True)
        for path, result in zip(path_list, results, strict=True):
            if isinstance(result, Exception):
                log.warning(f"Skipping local skill path {path}: {result}")

    def load(self) -> list[Skill]:
        skills: list[Skill] = []
        for path in self.paths:
            try:
                # validate=False mirrors GithubSkills' lenient mode: extra
                # frontmatter keys are kept as-is rather than rejected.
                loaded = self._preloaded[path] if path in self._preloaded else LocalSkills(path, validate=False).load()
                skills.extend(loaded)
            except Exception as e:
                log.warning(f"Skipping local skill path {path}: {e}")
        log.debug(f"Loaded {len(skills)} skills from local paths")
        return skills


class GithubSkills(SkillLoader):
    """Loads skills from GitHub sources via the SQLite skill cache."""

    def __init__(self, skills: list[SkillConfig], cache: SkillCache = skill_cache):
        self.sources = [s.github for s in skills if s.github]
        self.cache = cache

    def load(self) -> list[Skill]:
        skills: list[Skill] = []
        for source in self.sources:
            for f in self.cache.resolve(source):
                try:
                    skills.append(_skill_from_md(f["content"], f"github:{source}:{f['path']}", lenient=True))
                except Exception as e:
                    log.warning(f"Skipping github skill {source}:{f['path']}: {e}")
        log.debug(f"Loaded {len(skills)} skills from github")
        return skills
