"""Authoritative root schema for agno-spec-builder YAML documents."""

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agno_spec_builder.mcp.schema import McpServerConfig
from agno_spec_builder.schemas.agent import AgentConfig
from agno_spec_builder.schemas.agentos_config import AgentOsConfig
from agno_spec_builder.schemas.context import ContextProviderConfig
from agno_spec_builder.schemas.embedders import EmbedderConfig
from agno_spec_builder.schemas.knowledge import KnowledgeConfig
from agno_spec_builder.schemas.learning import LearningConfig
from agno_spec_builder.schemas.model import ModelConfig
from agno_spec_builder.schemas.provider import ProviderConfig
from agno_spec_builder.schemas.schedule import ScheduleConfig
from agno_spec_builder.schemas.skill import SkillConfig
from agno_spec_builder.schemas.team import TeamConfig
from agno_spec_builder.schemas.toolset import ToolsetConfig
from agno_spec_builder.schemas.webhook import WebhookConfig
from agno_spec_builder.schemas.workflow import WorkflowConfig

ModelCatalog = dict[str, ModelConfig] | list[dict[str, Any]]
EmbedderCatalog = dict[str, EmbedderConfig] | list[dict[str, Any]]


class NamedProviderSpec(BaseModel):
    """Named free-form root catalog entry, currently used by ``vectordb``."""

    model_config = ConfigDict(extra="allow")

    name: str
    provider: str


class BaseSchema(BaseModel):
    """Complete YAML root consumed by :func:`agno_spec_builder.build`.

    Root keys are strict to catch misspelled sections. Component schemas retain
    their own passthrough behavior for Agno constructor options. ``models`` and
    ``embedders`` accept either the canonical list form (entries require ``name``)
    or the legacy mapping form.
    """

    model_config = ConfigDict(extra="forbid")

    project: str | None = None
    agentos: AgentOsConfig = Field(default_factory=AgentOsConfig)
    providers: list[ProviderConfig] = Field(default_factory=list)
    models: ModelCatalog = Field(default_factory=dict)
    embedders: EmbedderCatalog = Field(default_factory=dict)
    vectordb: list[NamedProviderSpec] | dict[str, dict[str, Any]] = Field(default_factory=list)
    skills: list[SkillConfig] = Field(default_factory=list)
    mcp: list[McpServerConfig] = Field(default_factory=list)
    schemas: dict[str, dict[str, Any]] = Field(default_factory=dict)
    agents: list[AgentConfig] = Field(default_factory=list)
    workflows: list[WorkflowConfig] = Field(default_factory=list)
    teams: list[TeamConfig] = Field(default_factory=list)
    context: list[ContextProviderConfig] = Field(default_factory=list)
    schedules: list[ScheduleConfig] = Field(default_factory=list)
    knowledge: list[KnowledgeConfig] = Field(default_factory=list)
    learning: list[LearningConfig] = Field(default_factory=list)
    toolsets: list[ToolsetConfig] = Field(default_factory=list)
    webhooks: list[WebhookConfig] = Field(default_factory=list)

    # Catalog fixtures/evaluation cases belong to the document but are not built.
    tests: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("models", mode="before")
    @classmethod
    def validate_model_catalog(cls, value: Any) -> Any:
        return cls._validate_named_catalog("models", value, ModelConfig)

    @field_validator("embedders", mode="before")
    @classmethod
    def validate_embedder_catalog(cls, value: Any) -> Any:
        return cls._validate_named_catalog("embedders", value, EmbedderConfig)

    @staticmethod
    def _validate_named_catalog(section: str, value: Any, config_type: type[BaseModel]) -> Any:
        if value is None:
            return {}
        if isinstance(value, dict):
            for name, config in value.items():
                if not isinstance(name, str) or not name:
                    raise ValueError(f"{section} mapping keys must be non-empty names")
                config_type.model_validate(config)
            return value
        if isinstance(value, list):
            for index, item in enumerate(value):
                if not isinstance(item, dict):
                    raise ValueError(f"{section}[{index}] needs a non-empty `name`")
                name = item.get("name")
                if not isinstance(name, str) or not name:
                    raise ValueError(f"{section}[{index}] needs a non-empty `name`")
                config_type.model_validate({key: item_value for key, item_value in item.items() if key != "name"})
            return value
        raise ValueError(f"{section} must be a list or mapping")

    @model_validator(mode="after")
    def unique_catalog_names(self) -> Self:
        sections = {
            "providers": [entry.name for entry in self.providers],
            "skills": [entry.name for entry in self.skills],
            "toolsets": [entry.name for entry in self.toolsets],
            "mcp": [entry.name for entry in self.mcp],
            "agents": [entry.slug for entry in self.agents],
            "workflows": [entry.slug for entry in self.workflows],
            "teams": [entry.slug for entry in self.teams],
            "context": [entry.name for entry in self.context],
            "schedules": [entry.name for entry in self.schedules],
            "knowledge": [entry.name for entry in self.knowledge],
            "learning": [entry.name for entry in self.learning],
            "webhooks": [entry.name for entry in self.webhooks],
        }
        if isinstance(self.vectordb, list):
            sections["vectordb"] = [entry.name for entry in self.vectordb]
        for section, names in sections.items():
            duplicates = sorted({name for name in names if names.count(name) > 1})
            if duplicates:
                raise ValueError(f"duplicate {section} names: {duplicates}")
        for section, entries in (("models", self.models), ("embedders", self.embedders)):
            if isinstance(entries, list):
                names = [entry["name"] for entry in entries]
                duplicates = sorted({name for name in names if names.count(name) > 1})
                if duplicates:
                    raise ValueError(f"duplicate {section} names: {duplicates}")
        paths = [entry.endpoint for entry in self.webhooks]
        duplicate_paths = sorted({path for path in paths if paths.count(path) > 1})
        if duplicate_paths:
            raise ValueError(f"duplicate webhook paths: {duplicate_paths}")
        targets = {
            "agent": {agent.slug for agent in self.agents},
            "team": {team.slug for team in self.teams},
            "workflow": {workflow.slug for workflow in self.workflows},
        }
        for webhook in self.webhooks:
            for trigger in webhook.triggers:
                if trigger.name not in targets[trigger.kind]:
                    raise ValueError(f"webhook {webhook.name!r} references unknown {trigger.kind} {trigger.name!r}")
        return self
