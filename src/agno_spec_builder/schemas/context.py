"""Context provider YAML config."""

from pydantic import BaseModel, ConfigDict, Field

from agno_spec_builder.schemas.model import ModelConfig


class ContextProviderConfig(BaseModel):
    # extra="allow": provider constructor kwargs (root, exclude_patterns, ...)
    # pass straight through.
    model_config = ConfigDict(extra="allow")

    name: str = Field(description="Provider name, referenced by agents' `context:` list.")
    provider: str = Field(description="One of CONTEXT_PROVIDERS: fs | wiki | database | ...")
    mode: str = Field(
        default="tools",
        description="ContextMode: 'tools' exposes the source's tools directly (no "
        "sub-agent model needed); 'agent'/'default' wrap it behind a query_<name> "
        "tool answered by a sub-agent (set `model:` then).",
    )
    model: ModelConfig | None = Field(default=None, description="Sub-agent model for 'agent'/'default' mode.")
