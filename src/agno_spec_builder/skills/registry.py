from agno.skills.loaders.base import SkillLoader

from agno_spec_builder.schemas import SkillConfig
from agno_spec_builder.skills.cache import SkillCache, skill_cache
from agno_spec_builder.skills.loaders import GithubSkills, LocalPathSkills, StringSkills
from agno_spec_builder.utils import resolve

__all__ = ["skill_registry"]


def skill_registry(items: list[str], skills: list[SkillConfig], cache: SkillCache = skill_cache) -> list[SkillLoader]:
    by_name = {skill.name: skill for skill in skills}
    cfgs = resolve(items, by_name)
    loaders: list[SkillLoader] = []
    if any(c.content for c in cfgs):
        loaders.append(StringSkills(cfgs))
    if any(c.path for c in cfgs):
        loaders.append(LocalPathSkills(cfgs))
    if any(c.github for c in cfgs):
        loaders.append(GithubSkills(cfgs, cache))
    return loaders
