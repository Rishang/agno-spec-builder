from collections.abc import Callable

from agno.agent import Agent
from agno.db.base import BaseDb
from agno.models.base import Model
from agno.skills import Skills
from agno.team import Team, TeamMode

from agno_spec_builder.builders.agents import log_tool_use
from agno_spec_builder.builders.schemas import SchemaBuilder
from agno_spec_builder.schemas import ModelConfig, SkillConfig, TeamConfig
from agno_spec_builder.skills.cache import SkillCache, skill_cache
from agno_spec_builder.skills.registry import skill_registry


class TeamBuilder:
    """Builds agno Teams from TeamConfigs. Members are slugs resolved against the
    shared agent catalog first, then against other team specs (a team can contain
    sub-teams). Like SchemaBuilder, sub-teams build lazily through recursion — so
    declaration order doesn't matter and a cycle raises instead of looping.

    Member id == slug so delegation/selection and run-tracking are stable (agno
    selects members by role but tracks them by id).
    """

    def __init__(
        self,
        agents: dict[str, Agent],
        schemas: SchemaBuilder,
        db: BaseDb,
        specs: list[TeamConfig],
        build_model: Callable[[ModelConfig], Model],
        skills: list[SkillConfig],
        skills_cache: SkillCache = skill_cache,
    ):
        self.agents = agents
        self.schemas = schemas
        self.db = db
        self.build_model = build_model
        self.skills = skills
        self.skills_cache = skills_cache
        self._specs = {c.slug: c for c in specs}
        self.registry: dict[str, Team] = {}
        self._building: set[str] = set()  # slugs mid-build, for cycle detection
        for slug in self._specs:
            self._ensure(slug)

    def _ensure(self, slug: str) -> Team:
        if slug in self.registry:
            return self.registry[slug]
        if slug in self._building:
            raise ValueError(f"Circular team ref: {slug}")
        self._building.add(slug)
        try:  # finally: a failed build must not leave the slug stuck mid-build
            self.registry[slug] = self._build(self._specs[slug])
        finally:
            self._building.discard(slug)
        return self.registry[slug]

    def _member(self, slug: str) -> Agent | Team:
        if slug in self.agents:
            return self.agents[slug]
        if slug in self._specs:  # a sub-team; build it on demand
            return self._ensure(slug)
        raise ValueError(f"Unknown member {slug!r}. agents={list(self.agents)} teams={list(self._specs)}")

    def _build(self, cfg: TeamConfig) -> Team:
        members = [self._member(s) for s in cfg.members]
        kwargs = cfg.team_kwargs()
        if cfg.model:
            kwargs["model"] = self.build_model(cfg.model)
        if cfg.output_schema:
            kwargs["output_schema"] = self.schemas.output_schema(cfg.output_schema)
        if cfg.skills:
            kwargs["skills"] = Skills(loaders=skill_registry(cfg.skills, self.skills, self.skills_cache))
            kwargs["tool_hooks"] = [log_tool_use]
        return Team(
            id=cfg.slug,
            name=cfg.name,
            members=members,
            mode=TeamMode(cfg.mode),
            db=self.db,
            **kwargs,
        )
