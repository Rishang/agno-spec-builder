"""Workflow and step YAML config."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agno_spec_builder.utils import is_identifier, slugify


class RouterHITLConfig(BaseModel):
    """Compact optional configuration for a selector-free Router."""

    model_config = ConfigDict(extra="forbid")

    message: str | None = None
    allow_multiple_selections: bool | None = None
    max_retries: int | None = Field(default=None, ge=1)
    on_reject: Literal["skip", "cancel", "retry"] | None = None


class StepConfig(BaseModel):
    # extra="allow": per-step agno knobs (max_retries, skip_on_failure, ...) pass
    # straight through to the agno Step via step_kwargs().
    model_config = ConfigDict(extra="allow")

    name: str = Field(
        description="Step's handle: required, unique in the workflow, [A-Za-z0-9_] only. "
        "It's the agno Step name, so loop: JMESPath resolves names against it."
    )
    run: str | None = Field(
        default=None,
        description="'agent.<slug>' | 'team.<slug>' | 'workflow.<slug>' — what this step runs. "
        "Exactly one of `run`/`parallel`/`case` should be set per step.",
    )
    parallel: list[StepConfig] | None = Field(
        default=None,
        description=("Static concurrent branches — a list of steps run in parallel instead of `run`."),
    )
    loop: str | None = Field(
        default=None,
        description=(
            "JMESPath over prior named step outputs -> a list; `run`'s agent/team is "
            "invoked once per item, in parallel under max_parallel."
        ),
    )
    max_parallel: int = Field(default=5, description="Concurrency cap for `loop` fan-out.")
    when: str | None = Field(
        default=None,
        description="CEL expression evaluated over prior step outputs; step is skipped if falsy. "
        "Example: \"plan.effort == 'high'\".",
    )
    case: str | None = Field(
        default=None,
        description="CEL expression -> string key; routes to the matching `branches` entry.",
    )
    router: str | Literal[True] | None = Field(
        default=None,
        description=(
            "A non-empty CEL selector expression for an agno native Router, or literal "
            "true for selector-free user routing. A selector may return a choice name, "
            "a list of choice names, or use the native `step_choices` CEL variable. "
            "Configure keyed routes with `branches`; `choices` retains the advanced "
            "list form."
        ),
    )
    choices: list[StepConfig] = Field(
        default_factory=list,
        description=(
            "Advanced/backward-compatible native Router nodes. Each item is a full "
            "StepConfig, so choices may be regular run steps, repeat Loops, Parallel "
            "nodes, or nested Routers. Use either `choices` or `branches`, not both."
        ),
    )
    branches: dict[str, StepConfig] = Field(
        default_factory=dict,
        description=(
            "{key: StepConfig} routes for `case` or `router`. A missing nested step "
            "name is populated from its key, allowing `tech: {run: agent.tech}`."
        ),
    )
    message: str | None = Field(
        default=None,
        description="Compact alias for `user_input_message` when using `router: true`.",
    )
    hitl: RouterHITLConfig | None = Field(
        default=None,
        description=(
            "Optional compact HITL settings for `router: true`: `message`, "
            "`allow_multiple_selections`, `max_retries`, and `on_reject`."
        ),
    )
    requires_confirmation: bool = Field(
        default=False,
        description="Pause before executing the selected Router choice and request confirmation.",
    )
    confirmation_message: str | None = Field(
        default=None,
        description="Message shown when Router choice confirmation is requested.",
    )
    requires_user_input: bool = Field(
        default=False,
        description=(
            "Request route selection from the user. Required when `router: true`; "
            "selector-based Routers instead use a CEL string."
        ),
    )
    user_input_message: str | None = Field(
        default=None,
        description="Message shown when the Router requests route selection.",
    )
    allow_multiple_selections: bool = Field(
        default=False,
        description="Allow selection of multiple routes when using `router: true`.",
    )
    user_input_schema: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional Agno user-input field definitions for HITL routing.",
    )
    requires_output_review: bool = Field(
        default=False,
        description="Pause after route execution so the output can be reviewed.",
    )
    output_review_message: str | None = Field(
        default=None,
        description="Message shown when Router output review is requested.",
    )
    hitl_max_retries: int = Field(
        default=3,
        ge=1,
        description="Maximum HITL retries when rejected output is configured to retry.",
    )
    on_reject: Literal["skip", "cancel", "retry"] = Field(
        default="skip",
        description="Action when confirmation or output review is rejected.",
    )
    human_review: dict[str, Any] | None = Field(
        default=None,
        description="Advanced Agno human-review configuration passed to the native Router.",
    )
    repeat: list[StepConfig] | None = Field(
        default=None,
        description=(
            "agno native Loop: run these sub-steps repeatedly until `until` (CEL "
            "end_condition) is true or `max_iterations` is reached. Distinct from "
            "`loop` (JMESPath fan-out over a list); `repeat` is condition-driven iteration."
        ),
    )
    until: str | None = Field(
        default=None,
        description=(
            "CEL end_condition for a `repeat` loop, evaluated over the loop's step "
            "outputs; iteration stops when it returns true. Omit to loop until max_iterations."
        ),
    )
    max_iterations: int = Field(default=3, description="Iteration cap for a `repeat` loop (agno Loop.max_iterations).")
    input: str | None = Field(
        default=None,
        description=(
            "JMESPath expression -> transforms prior step outputs into this step's "
            "input string. Omit to pass the workflow's current input unchanged."
        ),
    )
    emit: str | None = Field(
        default=None,
        description=(
            "JMESPath expression evaluated over prior step outputs plus this step's "
            "own `result` (e.g. \"'wrote ' + result.title\"). Logged via log.info and "
            "emitted as a CustomEvent in the NDJSON stream (src/routes/stream.py). "
            "Only applies to `run`/`case`/`loop` steps; ignored on `parallel`."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_router_declaration(cls, data: Any) -> Any:
        """Fill branch names and normalize compact selector-free Router syntax."""
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        branches = normalized.get("branches")
        if isinstance(branches, dict):
            changed = False
            named_branches: dict[Any, Any] = {}
            for key, value in branches.items():
                if isinstance(value, dict) and "name" not in value:
                    value = {"name": key, **value}
                    changed = True
                named_branches[key] = value
            if changed:
                normalized["branches"] = named_branches

        if normalized.get("router") is True and "requires_user_input" not in normalized:
            normalized["requires_user_input"] = True

        aliases: list[tuple[str, Any, str]] = []
        if "message" in normalized and normalized["message"] is not None:
            aliases.append(("message", normalized["message"], "user_input_message"))
        hitl = normalized.get("hitl")
        if isinstance(hitl, dict):
            aliases.extend(
                (f"hitl.{source}", value, target)
                for source, target in {
                    "message": "user_input_message",
                    "allow_multiple_selections": "allow_multiple_selections",
                    "max_retries": "hitl_max_retries",
                    "on_reject": "on_reject",
                }.items()
                if (value := hitl.get(source)) is not None
            )

        for source, value, target in aliases:
            if target in normalized:
                raise ValueError(f"`{source}` cannot be combined with `{target}`")
            normalized[target] = value
        return normalized

    @field_validator("router", mode="before")
    @classmethod
    def strict_router_mode(cls, value: Any) -> Any:
        if value is None or isinstance(value, str) or value is True:
            return value
        raise ValueError("router must be a CEL selector string or literal true")

    @field_validator("name")
    @classmethod
    def _bare_identifier(cls, v: str) -> str:
        # name is used as a bare key in loop: JMESPath.
        if not is_identifier(v):
            raise ValueError(f"step name {v!r} must match [A-Za-z0-9_] (no '.', '-', space)")
        return v

    @model_validator(mode="after")
    def validate_router_choices(self) -> Self:
        if self.router is not None and self.case is not None:
            raise ValueError("step must use either `router` or `case`, not both")

        if self.router is not None:
            if isinstance(self.router, str):
                if not self.router.strip():
                    raise ValueError("router selector must be a non-empty CEL expression")
                if self.requires_user_input:
                    raise ValueError("selector-based router cannot require user input; use `router: true`")
            elif not self.requires_user_input:
                raise ValueError("`router: true` requires `requires_user_input: true`")

            if self.choices and self.branches:
                raise ValueError("router step must use either `choices` or `branches`, not both")
            if not self.choices and not self.branches:
                raise ValueError("router step needs non-empty `branches` or `choices`")
            names = [choice.name for choice in self.choices]
            duplicates = sorted({name for name in names if names.count(name) > 1})
            if duplicates:
                raise ValueError(f"router choice names must be unique: {duplicates}")
        elif self.choices:
            raise ValueError("`choices` is only valid on a router step")

        if self.message is not None and self.router is not True:
            raise ValueError("`message` is only valid with `router: true`")
        if self.hitl is not None and self.router is not True:
            raise ValueError("`hitl` is only valid with `router: true`")

        if self.allow_multiple_selections and self.router is not True:
            raise ValueError("`allow_multiple_selections` is only valid with `router: true`")
        if not self.requires_user_input and (self.user_input_message is not None or self.user_input_schema is not None):
            raise ValueError("user input message/schema requires `requires_user_input: true`")
        return self

    @property
    def kind_ref(self) -> tuple[str, str]:
        """`run: "agent.plan"` -> ("agent", "plan")."""
        assert self.run, "step needs `run`"
        kind, _, slug = self.run.partition(".")
        assert kind in ("agent", "team", "workflow") and slug, f"bad run ref: {self.run!r}"
        return kind, slug

    def step_kwargs(self) -> dict[str, Any]:
        # Fields above are wired by the builder; everything else (description,
        # max_retries, skip_on_failure, on_error, ...) passes through to agno Step.
        _WIRE = {
            "run",
            "parallel",
            "loop",
            "max_parallel",
            "name",
            "when",
            "case",
            "router",
            "choices",
            "branches",
            "message",
            "hitl",
            "repeat",
            "until",
            "max_iterations",
            "input",
            "emit",
        }
        return self.model_dump(exclude=_WIRE, exclude_none=True, exclude_defaults=True)


class WorkflowConfig(BaseModel):
    # extra="allow": workflow knobs (stream, stream_events, add_*_to_context, ...)
    # pass straight to agno's Workflow constructor via workflow_kwargs.
    model_config = ConfigDict(extra="allow")

    name: str = Field(description="Human-readable workflow name.")
    slug: str = Field(
        default="",
        description=("Stable id used to reference this workflow elsewhere. Defaults to slugify(name)."),
    )
    description: str | None = Field(default=None, description="Short summary of what the workflow does.")
    background: bool = Field(
        default=False,
        description=(
            "Default for Agno's invocation-time `background` option when this workflow is run "
            "through Built.arun(); callers may override it per invocation."
        ),
    )
    steps: list[StepConfig] = Field(description="Ordered list of steps that make up the workflow.")

    @model_validator(mode="after")
    def default_slug_from_name(self) -> Self:
        if not self.slug:
            self.slug = slugify(self.name)
        return self

    def workflow_kwargs(self) -> dict[str, Any]:
        # name/description/steps wired explicitly in the builder; everything else
        # (dependencies, session_state, stream flags, ...) passes through.
        _WIRE = {"name", "description", "slug", "background", "steps"}
        return self.model_dump(exclude=_WIRE, exclude_none=True, exclude_defaults=True)
