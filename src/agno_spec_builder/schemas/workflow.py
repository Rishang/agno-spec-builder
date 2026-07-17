"""Workflow and step YAML config."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agno_spec_builder.utils import is_identifier, slugify


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
    router: str | None = Field(
        default=None,
        description=(
            "CEL selector expression that returns a `branches` key (or list of keys). "
            "Unlike `case` (custom single-dispatch executor), `router` builds an agno "
            "native Router over the named `branches` as choices — supporting native "
            "multi-selection and step-level HITL (requires_confirmation/human_review)."
        ),
    )
    branches: dict[str, StepConfig] = Field(
        default_factory=dict,
        description="{key: StepConfig} — one branch per expected `case`/`router` value.",
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

    @field_validator("name")
    @classmethod
    def _bare_identifier(cls, v: str) -> str:
        # name is used as a bare key in loop: JMESPath.
        if not is_identifier(v):
            raise ValueError(f"step name {v!r} must match [A-Za-z0-9_] (no '.', '-', space)")
        return v

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
            "branches",
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
    steps: list[StepConfig] = Field(description="Ordered list of steps that make up the workflow.")

    @model_validator(mode="after")
    def default_slug_from_name(self) -> Self:
        if not self.slug:
            self.slug = slugify(self.name)
        return self

    def workflow_kwargs(self) -> dict[str, Any]:
        # name/description/steps wired explicitly in the builder; everything else
        # (dependencies, session_state, stream flags, ...) passes through.
        _WIRE = {"name", "description", "slug", "steps"}
        return self.model_dump(exclude=_WIRE, exclude_none=True, exclude_defaults=True)
