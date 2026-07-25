"""Declarative externally configured agent toolsets."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolsetConfig(BaseModel):
    """A named toolkit built by a registered toolset factory."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Unique toolset name referenced from an agent's `tools` list.")
    type: str = Field(min_length=1, description="Key in `TOOLSET_REGISTRY`.")
    provider: str | None = Field(
        default=None,
        description="Optional models provider profile; its spec is merged before `init`, which wins on conflicts.",
    )
    init: dict[str, Any] = Field(
        default_factory=dict,
        description="Constructor keyword arguments for the toolset factory.",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_a2a_fields(cls, value: Any) -> Any:
        """Keep the original direct A2A YAML form working while adopting `init`."""
        if not isinstance(value, dict) or value.get("type") != "a2a":
            return value
        data = dict(value)
        init = dict(data.get("init") or {})
        for key in ("url", "headers", "timeout", "protocol"):
            if key in data:
                if key in init:
                    raise ValueError(f"toolset {key!r} cannot appear in both the root and `init`")
                init[key] = data.pop(key)
        data["init"] = init
        return data
