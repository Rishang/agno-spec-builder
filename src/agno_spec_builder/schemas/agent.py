"""Agent YAML config and tool refs."""

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agno_spec_builder.schemas.model import FallbackConfig, ModelConfig
from agno_spec_builder.utils import slugify


class ToolRef(BaseModel):
    """A `tools:`/`context:` entry with per-agent function filtering — same
    include/exclude vocabulary as the `mcp:` catalog entries."""

    name: str = Field(description="Tool or context provider name from its catalog.")
    include_tools: list[str] | None = Field(
        default=None,
        description="If set, only these function names from the toolkit/provider are exposed.",
    )
    exclude_tools: list[str] | None = Field(
        default=None,
        description="Function names to hide from this agent.",
    )


class StaticArgsRule(BaseModel):
    function_name: str = Field(description="Tool function name to intercept.")
    inject: dict[str, Any] = Field(description="Kwargs merged into the call before execution.")


class ToolHookRef(BaseModel):
    """A `tool_hooks:` entry — named builder from TOOL_HOOK_BUILDERS plus its params."""

    name: str = Field(description="Hook builder name (e.g. static_args_hook).")
    rules: list[StaticArgsRule] | None = Field(
        default=None,
        description="For static_args_hook: per-function inject maps.",
    )


class AgentConfig(BaseModel):
    # extra="allow": any agno Agent arg (telemetry, markdown, reasoning, ...) set
    # in YAML passes through agent_kwargs without being added here. Fields below
    # are the ones the builder wires specially or that need a non-scalar type.
    model_config = ConfigDict(extra="allow")

    name: str = Field(description="Human-readable agent name.")
    description: str | None = Field(default=None, description="Short summary of what the agent does.")
    instructions: str | list[str] | None = Field(
        default=None,
        description=("System-prompt instructions — a single block or a list of lines/sections."),
    )
    model: ModelConfig = Field(description="Primary model this agent uses to respond.")
    system_message: str | None = Field(
        default=None,
        description="Raw system message, used instead of/alongside generated instructions.",
    )
    slug: str = Field(
        default="",
        description=("Stable id used for team delegation and run tracking. Defaults to slugify(name)."),
    )
    background: bool = Field(
        default=False,
        description=(
            "Default for Agno's invocation-time `background` option when this agent is run "
            "through Built.arun(); callers may override it per invocation."
        ),
    )
    skills: list[str] = Field(
        default_factory=list,
        description=("Skill names (from the top-level `skills:` catalog) this agent can use."),
    )
    tools: list[str | ToolRef] = Field(
        default_factory=list,
        description=(
            "Tool names (from TOOL_REGISTRY or the top-level `toolsets:` catalog) "
            "this agent can call. An entry can also "
            "be {name, include_tools, exclude_tools} to allow/drop individual "
            "functions of a toolkit for this agent only."
        ),
    )
    workflow_tools: list[str | ToolRef] = Field(
        default_factory=list,
        description=(
            "Workflow slugs (from the top-level `workflows:` catalog) exposed to this "
            "agent as agno WorkflowTools — the agent can run a whole workflow as a tool "
            "(async_mode). Attached after workflows are built. Entries accept the same "
            "{name, include_tools, exclude_tools} shape to drop run/think/analyze."
        ),
    )
    mcp: list[str] = Field(
        default_factory=list,
        description=(
            "MCP server names (from the top-level `mcp:` catalog) whose tools this "
            "agent can call. Resolved to MCPTools toolkits by the builder."
        ),
    )
    knowledge: str | list[str] | None = Field(
        default=None,
        description=(
            "Knowledge base name (from the top-level `knowledge:` catalog). Attaches "
            "the built agno Knowledge and enables search_knowledge. A list of names "
            "instead attaches a knowledge_hub tool that searches any of them by name."
        ),
    )
    learning: str | bool | None = Field(
        default=None,
        description=(
            "Learning: `true` enables agno's default LearningMachine (native "
            "passthrough), or a name from the top-level `learning:` catalog attaches "
            "a configured LearningMachine (user profile/memory, session context, "
            "entity memory, learned knowledge, decision log) as the agent's `learning=`."
        ),
    )
    context: list[str | ToolRef] = Field(
        default_factory=list,
        description=(
            "Context provider names (from the top-level `context:` catalog). Each "
            "provider's tools are added to the agent. An entry can also be "
            "{name, include_tools, exclude_tools} to allow/drop individual provider "
            "tools for this agent only."
        ),
    )
    output_schema: str | dict | None = Field(
        default=None,
        description="A schema name (referencing the top-level `schemas:` section) or an inline "
        "{name, fields} dict; builder turns it into a Pydantic model.",
    )
    input_schema: str | dict | None = Field(
        default=None,
        description=(
            "Same shape as output_schema — a schema name or inline {name, fields} dict. "
            "The agent's input is validated against this Pydantic model before the run starts."
        ),
    )
    parser_model: ModelConfig | None = Field(
        default=None,
        description=(
            "Optional dedicated model for agno's parser_model (reformats the primary "
            "model's output into output_schema — needed when tools/skills/mcp are also "
            "set, since native structured-output mode and tool calling don't mix). "
            "Defaults to `model` when omitted; only meaningful alongside output_schema."
        ),
    )
    fallback_models: list[ModelConfig] | None = Field(
        default=None,
        description=(
            "Models tried in order when the primary model call fails. Simple case — "
            "for per-error-type routing (rate limit vs context overflow) use "
            "`fallback_config` instead; agno prefers fallback_config if both are set."
        ),
    )
    fallback_config: FallbackConfig | None = Field(
        default=None,
        description="Per-error-type fallback model routing (advanced). See FallbackConfig.",
    )
    followup_model: ModelConfig | None = Field(
        default=None,
        description=(
            "Optional dedicated model for generating followup questions (agno's "
            "`followups`/`num_followups` options). Defaults to `model` when omitted; "
            "only meaningful alongside `followups: true`."
        ),
    )
    pre_hooks: list[str] = Field(
        default_factory=list,
        description=(
            "Hook names (from var: HOOK_REGISTRY) run right after the session "
            "loads, before processing starts — e.g. guardrails like prompt-injection/PII checks."
        ),
    )
    post_hooks: list[str] = Field(
        default_factory=list,
        description=(
            "Hook names (from var: HOOK_REGISTRY) run after output is generated but before the response is returned."
        ),
    )
    tool_hooks: list[ToolHookRef] = Field(
        default_factory=list,
        description=(
            "Named tool-call hooks (from TOOL_HOOK_BUILDERS) run around each tool "
            "invocation. Always stacked after the built-in log_tool_use hook. "
            "Example: {name: static_args_hook, rules: [{function_name, inject}]}."
        ),
    )

    @model_validator(mode="after")
    def default_slug_from_name(self) -> Self:
        if not self.slug:
            self.slug = slugify(self.name)
        return self

    def agent_kwargs(self) -> dict[str, Any]:
        # output_schema is built into a Pydantic model and passed explicitly by
        # the builder — exclude it so the raw dict doesn't reach agno verbatim.
        _WIRE = {
            "model",
            "slug",
            "background",
            "skills",
            "tools",
            "workflow_tools",
            "mcp",
            "knowledge",
            "learning",
            "context",
            "output_schema",
            "input_schema",
            "parser_model",
            "fallback_models",
            "fallback_config",
            "followup_model",
            "pre_hooks",
            "post_hooks",
            "tool_hooks",
        }
        return self.model_dump(exclude=_WIRE, exclude_none=True, exclude_defaults=True)
