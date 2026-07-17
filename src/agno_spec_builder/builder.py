"""Top-level declarative Agno graph builder."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from agno.agent import Agent
from agno.db.base import BaseDb
from agno.db.in_memory import InMemoryDb
from agno.team import Team
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
    EmbedderConfig,
    ModelConfig,
    ProviderConfig,
    ScheduleConfig,
    SkillConfig,
)
from agno_spec_builder.skills.cache import SkillCache, skill_cache
from agno_spec_builder.utils import log
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
    tests: list[dict[str, Any]] = field(default_factory=list)


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


def _load_source(source: str | Path | dict | BaseSchema) -> BaseSchema:
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


def build(
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
    graphs in one process without application globals.
    """
    root = _load_source(source)
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

    agent_specs = root.agents
    skill_list = list(skills.values())
    agents = {
        spec.slug: build_agent(
            spec, skill_list, schemas, db, knowledge, context, models, learning, providers, skills_cache
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
        tests=root.tests,
    )
