"""Team YAML config."""

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agno_spec_builder.schemas.model import ModelConfig
from agno_spec_builder.utils import slugify


class TeamConfig(BaseModel):
    # extra="allow": any agno Team arg (mode, debug_mode, ...) set in YAML passes
    # through team_kwargs. members are slugs resolved against the agent/team catalog.
    model_config = ConfigDict(extra="allow")

    name: str = Field(description="Human-readable team name.")
    slug: str = Field(
        default="",
        description=("Stable id used to reference this team elsewhere. Defaults to slugify(name)."),
    )
    background: bool = Field(
        default=False,
        description=(
            "Default for Agno's invocation-time `background` option when this team is run "
            "through Built.arun(); callers may override it per invocation."
        ),
    )
    model: ModelConfig | None = Field(
        default=None,
        description="Leader model. Optional — some team modes don't need one.",
    )
    members: list[str] = Field(description="Agent or team slugs that make up this team.")
    mode: Literal["coordinate", "route", "broadcast", "tasks"] = Field(
        default="coordinate",
        description="Leader collaboration topology — how the leader delegates to members.",
    )
    output_schema: str | dict | None = Field(
        default=None,
        description=("A schema name (from the top-level `schemas:` section) or an inline {name, fields} dict."),
    )
    skills: list[str] = Field(
        default_factory=list,
        description=("Skill names (from the top-level `skills:` catalog) available to the leader."),
    )

    @model_validator(mode="after")
    def default_slug_from_name(self) -> Self:
        if not self.slug:
            self.slug = slugify(self.name)
        return self

    def team_kwargs(self) -> dict[str, Any]:
        # name/mode/model/members/output_schema wired explicitly by the builder;
        # everything else (instructions, description, followups, debug_mode, ...)
        # passes through to agno's Team constructor.
        _WIRE = {"name", "slug", "background", "members", "model", "mode", "output_schema", "skills"}
        return self.model_dump(exclude=_WIRE, exclude_none=True, exclude_defaults=True)
