"""Top-level declarative Agno graph builder."""

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml
from agno.agent import Agent
from agno.db.base import BaseDb
from agno.db.in_memory import InMemoryDb
from agno.team import Team
from agno.tools import Toolkit
from agno.workflow import Workflow
from pydantic import BaseModel

from agno_spec_builder.base_schema import BaseSchema, NamedProviderSpec
from agno_spec_builder.builders.agents import attach_workflow_tools, build_agent, build_model
from agno_spec_builder.builders.context import build_context_provider
from agno_spec_builder.builders.knowledge import build_knowledge
from agno_spec_builder.builders.learning import build_learning
from agno_spec_builder.builders.schemas import SchemaBuilder
from agno_spec_builder.builders.teams import TeamBuilder
from agno_spec_builder.builders.workflows import WorkflowBuilder
from agno_spec_builder.mcp.schema import McpServerConfig
from agno_spec_builder.mcp.toolkit import McpRunner
from agno_spec_builder.schemas import (
    AgentOsConfig,
    EmbedderConfig,
    ModelConfig,
    ProviderConfig,
    ScheduleConfig,
    SkillConfig,
    WebhookConfig,
)
from agno_spec_builder.skills.cache import SkillCache, skill_cache
from agno_spec_builder.skills.loaders import LocalPathSkills
from agno_spec_builder.tools import TOOLSET_REGISTRY
from agno_spec_builder.utils import expand_env, log
from agno_spec_builder.workflow.store import FanoutStateStore, InMemoryFanoutStore


@dataclass
class Built:
    """All objects and validated catalogs produced from one root spec."""

    agents: dict[str, Agent]
    teams: dict[str, Team]
    workflows: dict[str, Workflow]
    skills: dict[str, SkillConfig]
    mcp_servers: dict[str, McpServerConfig] = field(default_factory=dict)
    knowledge: dict = field(default_factory=dict)
    schedules: dict[str, ScheduleConfig] = field(default_factory=dict)
    models: dict[str, ModelConfig] = field(default_factory=dict)
    embedders: dict[str, EmbedderConfig] = field(default_factory=dict)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    vector_dbs: dict[str, dict[str, Any]] = field(default_factory=dict)
    learning: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    schemas: SchemaBuilder | None = None
    mcp_runner: McpRunner = field(default_factory=McpRunner)
    db: BaseDb | None = None
    project: str | None = None
    agentos: AgentOsConfig = field(default_factory=AgentOsConfig)
    tests: list[dict[str, Any]] = field(default_factory=list)
    toolsets: dict[str, Toolkit] = field(default_factory=dict)
    webhooks: dict[str, WebhookConfig] = field(default_factory=dict)
    background_defaults: dict[str, bool] = field(default_factory=dict)

    def _target(self, ref: str) -> Agent | Team | Workflow:
        """Resolve ``agent.<slug>``, ``team.<slug>``, or ``workflow.<slug>``."""
        kind, separator, slug = ref.partition(".")
        catalogs = {"agent": self.agents, "team": self.teams, "workflow": self.workflows}
        if not separator or not slug or kind not in catalogs:
            raise ValueError("target must be `agent.<slug>`, `team.<slug>`, or `workflow.<slug>`")
        target = catalogs[kind].get(slug)
        if target is None:
            raise ValueError(f"unknown {kind} target {slug!r}; available={list(catalogs[kind])}")
        return target

    async def arun(
        self,
        target: str,
        input: Any = None,
        *,
        background: bool | None = None,
        stream: bool | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run a built resource with its declarative background default.

        ``target`` uses the same ``kind.slug`` references as workflow steps. A
        per-call ``background`` value overrides the resource's YAML setting.
        ``stream=True`` plus background execution returns Agno's resumable event
        iterator; AgentOS clients can reconnect through the native ``/resume``
        route. Non-streaming background calls return a PENDING run output.
        """
        resource = self._target(target)
        run_in_background = self.background_defaults.get(target, False) if background is None else background
        run_kwargs = {**kwargs, "background": run_in_background}
        if stream is not None:
            run_kwargs["stream"] = stream

        effective_stream = bool(getattr(resource, "stream", False)) if stream is None else stream
        if effective_stream:
            run_kwargs["stream"] = True
        if isinstance(resource, Agent) and self.mcp_runner.needs(resource):
            if effective_stream:
                return self.mcp_runner.stream(resource, input, **run_kwargs)
            return await self.mcp_runner.invoke(resource, input, **run_kwargs)
        # Agno returns an async iterator, not an awaitable, for stream=True.
        # Keep the outer coroutine awaitable while handing that iterator to callers.
        # The resource union's `arun` overloads do not unify, but share this runtime shape.
        result = cast(Any, resource).arun(input, **run_kwargs)
        return result if effective_stream else await result

    async def aget_run_output(
        self,
        target: str,
        run_id: str,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> Any:
        """Poll a background run using the target resource's persisted run state."""
        resource = self._target(target)
        return await resource.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)


def _catalog(section: dict[str, Any] | list[dict[str, Any]], cls: type[BaseModel]) -> dict[str, Any]:
    """Normalize a validated list/mapping root catalog to a named mapping."""
    if isinstance(section, list):
        return {
            item["name"]: cls.model_validate({key: value for key, value in item.items() if key != "name"})
            for item in section
        }
    return {name: value if isinstance(value, cls) else cls.model_validate(value) for name, value in section.items()}


def _vector_catalog(section: list[NamedProviderSpec] | dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if isinstance(section, list):
        return {entry.name: entry.model_dump(exclude={"name"}) for entry in section}
    return dict(section)


def _load_source_sync(source: str | Path | dict | BaseSchema) -> BaseSchema:
    """Parse and validate one supported source form.

    ``str`` values are interpreted as inline JSON when they begin with ``{``,
    as JSON file paths when they end in ``.json`` (case-insensitive), and as
    inline YAML otherwise. Use :class:`Path` for YAML files. Dictionaries and
    existing ``BaseSchema`` instances are validated/reused directly.
    """

    if isinstance(source, BaseSchema):
        return source
    if isinstance(source, dict):
        raw = source
    elif isinstance(source, str):
        source = source.strip()
        if source.startswith("{"):
            raw = json.loads(source)
        elif Path(source).suffix.lower() == ".json":
            with Path(source).open(encoding="utf-8") as stream:
                raw = json.load(stream)
        else:
            raw = yaml.safe_load(source)
    else:
        with source.open(encoding="utf-8") as stream:
            raw = yaml.safe_load(stream)
    if not isinstance(raw, dict):
        raise ValueError("spec root must be a mapping")
    return BaseSchema.model_validate(raw)


async def _load_source(source: str | Path | dict | BaseSchema) -> BaseSchema:
    """Validate a source without blocking the caller's event loop."""
    return await asyncio.to_thread(_load_source_sync, source)


async def _warm_skills(root: BaseSchema, skills_cache: SkillCache) -> None:
    """Fetch remote and local skills before Agno's synchronous loaders run."""
    github_sources = {skill.github for skill in root.skills if skill.github}
    if github_sources:
        await asyncio.gather(*(skills_cache.aresolve(source) for source in github_sources))

    local_paths = {skill.path for skill in root.skills if skill.path}
    if local_paths:
        await LocalPathSkills.apreload(local_paths)


def _build_from_root(
    root: BaseSchema,
    db: BaseDb | None,
    skills_cache: SkillCache,
    tenant_namespace: str | None,
    fanout_store: FanoutStateStore | None,
) -> Built:
    """Synchronously assemble Agno objects outside the event-loop thread."""
    db = db or InMemoryDb()
    fanout_store = fanout_store or InMemoryFanoutStore()

    log.info("building graph from spec: project=%s", root.project)

    skills = {item.name: item for item in root.skills}
    mcp_servers = {item.name: item for item in root.mcp}
    mcp_runner = McpRunner(mcp_servers)
    schemas = SchemaBuilder(root.schemas)
    models = _catalog(root.models, ModelConfig)
    embedders = _catalog(root.embedders, EmbedderConfig)
    providers = {item.name: item for item in root.providers}
    vector_dbs = _vector_catalog(root.vectordb)

    knowledge = {
        item.name: build_knowledge(item, embedders, providers, db, tenant_namespace) for item in root.knowledge
    }
    learning = {item.name: build_learning(item, models, knowledge, providers, db) for item in root.learning}
    context = {item.name: build_context_provider(item, models, providers) for item in root.context}
    schedules = {item.name: item for item in root.schedules}
    toolsets: dict[str, Toolkit] = {}
    for config in root.toolsets:
        factory = TOOLSET_REGISTRY.get(config.type)
        if factory is None:
            raise ValueError(f"unknown toolset type {config.type!r}; available={list(TOOLSET_REGISTRY)}")
        init = expand_env(config.init)
        # Merge an optional models profile; explicit toolset init wins.
        if config.provider:
            from agno_spec_builder.builders.providers import resolve_provider_spec

            provider_kw = resolve_provider_spec(config.provider, "models", providers)
            init = {**provider_kw, **init}
        if "name" in init:
            raise ValueError("toolset `init` cannot set `name`; use the entry's top-level `name`")
        toolsets[config.name] = factory(name=config.name, **init)
    webhooks = {item.name: item for item in root.webhooks}

    agent_specs = root.agents
    skill_list = list(skills.values())
    agents = {
        spec.slug: build_agent(
            spec, skill_list, schemas, db, knowledge, context, models, learning, providers, skills_cache, toolsets
        )
        for spec in agent_specs
    }

    team_specs = root.teams
    teams = TeamBuilder(
        agents,
        schemas,
        db,
        team_specs,
        lambda model: build_model(model, models, providers),
        skill_list,
        skills_cache,
    ).registry

    workflows = WorkflowBuilder(
        agents, teams, schemas, db, root.workflows, mcp_runner=mcp_runner, fanout_store=fanout_store
    ).registry
    for spec in agent_specs:
        if spec.workflow_tools:
            attach_workflow_tools(agents[spec.slug], spec.workflow_tools, workflows)

    return Built(
        agents=agents,
        teams=teams,
        workflows=workflows,
        skills=skills,
        mcp_servers=mcp_servers,
        knowledge=knowledge,
        schedules=schedules,
        models=models,
        embedders=embedders,
        providers=providers,
        vector_dbs=vector_dbs,
        learning=learning,
        context=context,
        schemas=schemas,
        mcp_runner=mcp_runner,
        db=db,
        project=root.project,
        agentos=root.agentos,
        tests=root.tests,
        toolsets=toolsets,
        webhooks=webhooks,
        background_defaults={
            **{f"agent.{spec.slug}": spec.background for spec in agent_specs},
            **{f"team.{spec.slug}": spec.background for spec in team_specs},
            **{f"workflow.{spec.slug}": spec.background for spec in root.workflows},
        },
    )


async def build(
    source: str | Path | dict | BaseSchema,
    db: BaseDb | None = None,
    skills_cache: SkillCache = skill_cache,
    tenant_namespace: str | None = None,
    fanout_store: FanoutStateStore | None = None,
) -> Built:
    """Build a runtime graph from an authoritative :class:`BaseSchema` root.

    ``source`` may be a YAML path, mapping, or prevalidated ``BaseSchema``. A
    fresh :class:`agno.db.in_memory.InMemoryDb` is used unless ``db`` is supplied.
    The result owns its MCP runner and fan-out state, allowing multiple independent
    graphs in one process without application globals. Agno's synchronous object
    construction runs in a worker thread so callers do not block their event loop.
    """
    root = await _load_source(source)
    await _warm_skills(root, skills_cache)
    return await asyncio.to_thread(
        _build_from_root,
        root,
        db,
        skills_cache,
        tenant_namespace,
        fanout_store,
    )


def _build_agentos_db(config: "AgentOsConfig") -> BaseDb | None:
    """Resolve the AgentOS database from the declarative ``agentos.db`` block.

    Returns ``None`` when no ``db`` block is declared, signaling
    :func:`build_agentos` to fall back to ``runtime.db`` (the db injected into
    :func:`build`). This keeps the existing injection escape hatch intact
    while letting the YAML pick a backend when it wants to.

    Imports are lazy so the spec-builder package keeps working in
    environments that pin agno without the db SDKs (sqlalchemy for
    sqlite/postgres, etc.).
    """
    if config.db is None:
        return None

    kind = config.db.kind
    spec = expand_env(config.db.spec)

    # Lazy imports — the db SDKs are optional agno extras.
    if kind == "in_memory":
        from agno.db.in_memory import InMemoryDb

        return InMemoryDb(**spec)
    if kind == "sqlite":
        from agno.db.sqlite import SqliteDb

        return SqliteDb(**spec)
    if kind == "postgres":
        from agno.db.postgres import PostgresDb

        return PostgresDb(**spec)

    # Unreachable: AgentOsDbKind is a Literal that pydantic already validated.
    raise ValueError(f"unsupported agentos db kind: {kind!r}")


def _build_agentos_sync(runtime: Built, kwargs: dict[str, Any]):
    """Construct AgentOS outside the event-loop thread."""
    if not runtime.agentos.enabled:
        return None

    # Imported lazily so the spec-builder package keeps working in
    # environments that pin agno without the os extra.
    from agno.os import AgentOS

    db = _build_agentos_db(runtime.agentos)
    if db is None:
        db = runtime.db

    knowledge_list = [k for k in runtime.knowledge.values() if k is not None]
    a2a_interface = kwargs.pop("a2a_interface", runtime.agentos.a2a_interface)
    agentos_id = expand_env(runtime.agentos.id) if runtime.agentos.id else None
    if runtime.agentos.agui_interface and runtime.agentos.agui_interface is not False:
        from agno.os.interfaces.agui import AGUI

        interfaces = list(kwargs.pop("interfaces", []) or [])
        interfaces.extend(AGUI(agent=agent, prefix=f"/agui/agents/{slug}") for slug, agent in runtime.agents.items())
        interfaces.extend(AGUI(team=team, prefix=f"/agui/teams/{slug}") for slug, team in runtime.teams.items())
        kwargs["interfaces"] = interfaces

    if runtime.webhooks:
        from fastapi import FastAPI

        from agno_spec_builder.webhooks import attach_webhook_routes

        base_app = kwargs.get("base_app")
        if base_app is None:
            base_app = FastAPI()
            kwargs["base_app"] = base_app
        attach_webhook_routes(base_app, runtime)

    return AgentOS(
        id=agentos_id,
        agents=list(runtime.agents.values()),
        teams=list(runtime.teams.values()),
        workflows=list(runtime.workflows.values()),
        db=db,
        knowledge=knowledge_list or None,
        a2a_interface=a2a_interface,
        **kwargs,
    )


async def build_agentos(runtime: Built, **kwargs: Any):
    """Construct an :class:`agno.os.AgentOS` from a built runtime graph.

    Returns ``None`` when ``runtime.agentos.enabled`` is ``False`` so callers
    can write::

        runtime = await build(Path("config.yml"))
        os = await build_agentos(runtime)
        if os is not None:
            os.serve(app=os.get_app(), **runtime.agentos.server.model_dump())

    Only the components ``AgentOS`` accepts directly are forwarded: agents,
    teams, workflows, db, and knowledge. Everything else on ``Built``
    (skills, mcp_servers, schedules, schemas, ...) is owned by the runtime
    and not duplicated onto the OS instance.

    The db is resolved from ``runtime.agentos.db`` when the YAML declares one;
    otherwise it falls back to ``runtime.db`` (the db injected into
    :func:`build`). This lets the YAML swap the AgentOS backend independently
    of the graph's db — e.g. graph on ``InMemoryDb`` for tests, OS on
    ``SqliteDb`` for persistence.

    ``**kwargs`` are forwarded verbatim to the ``AgentOS`` constructor, so
    callers can toggle any OS-level flag the spec doesn't model yet — e.g.
    ``build_agentos(runtime, authorization=True, tracing=True, scheduler=True)``.
    A caller-supplied ``a2a_interface`` overrides the declarative setting.
    When ``runtime.agentos.agui_interface`` is enabled, generated AG-UI
    interfaces are appended to any caller-provided ``interfaces``.
    ``kwargs`` that collide with the forwarded components (``agents``,
    ``teams``, ``workflows``, ``db``, ``knowledge``) raise ``TypeError`` from
    ``AgentOS.__init__`` (duplicate keyword), which is the desired fail-loud
    behavior.
    """
    return await asyncio.to_thread(_build_agentos_sync, runtime, kwargs)
