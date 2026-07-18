import copy
import inspect

from agno.agent import Agent
from agno.db.base import BaseDb
from agno.models.base import Model
from agno.models.fallback import FallbackConfig as AgnoFallbackConfig
from agno.skills import Skills
from agno.tools import Toolkit

from agno_spec_builder.builders.schemas import SchemaBuilder
from agno_spec_builder.hooks import HOOK_REGISTRY, TOOL_HOOK_BUILDERS
from agno_spec_builder.imports import resolve_symbol
from agno_spec_builder.schemas import AgentConfig, ModelConfig, ProviderConfig, SkillConfig, ToolHookRef, ToolRef
from agno_spec_builder.skills.cache import SkillCache, skill_cache
from agno_spec_builder.skills.registry import skill_registry
from agno_spec_builder.tools import TOOL_REGISTRY
from agno_spec_builder.utils import log, resolve


def _as_ref(entry: str | ToolRef) -> ToolRef:
    return entry if isinstance(entry, ToolRef) else ToolRef(name=entry)


def _build_tool_hooks(refs: list[ToolHookRef]) -> list:
    """Resolve YAML tool_hooks entries via TOOL_HOOK_BUILDERS."""
    out = []
    for ref in refs:
        builder = TOOL_HOOK_BUILDERS.get(ref.name)
        if builder is None:
            raise ValueError(f"Unknown tool_hook {ref.name!r}. known={list(TOOL_HOOK_BUILDERS)}")
        out.append(builder(ref.model_dump(exclude_none=True)))
    return out


def filter_tools(tools: list, ref: ToolRef) -> list:
    """Apply a ToolRef's include/exclude to toolkits (by function name) and bare
    Functions (by name). Toolkits are shallow-copied so the shared registry
    instance stays untouched; a toolkit filtered to zero functions is dropped."""
    if not ref.include_tools and not ref.exclude_tools:
        return tools

    def ok(name: str) -> bool:
        if ref.include_tools and name not in ref.include_tools:
            return False
        return not (ref.exclude_tools and name in ref.exclude_tools)

    out = []
    for tool in tools:
        functions = getattr(tool, "functions", None)
        if isinstance(functions, dict):  # Toolkit
            tool = copy.copy(tool)
            tool.functions = {k: v for k, v in functions.items() if ok(k)}
            if tool.functions:
                out.append(tool)
        elif ok(getattr(tool, "name", "")):
            out.append(tool)
    return out


async def log_tool_use(function_name, function_call, arguments):
    """Tool hook: log every tool/skill call (skills, plain tools, and MCP tools).
    Async-only — requires arun(); sync agent.run() will get an unawaited coroutine.
    inspect.isawaitable handles sync tools correctly on the arun() path."""
    log.info(f"using {function_name}({arguments})")
    result = function_call(**arguments)
    if inspect.isawaitable(result):
        result = await result
    return result


# Provider name (from YAML) -> "module:ClassName". Imported lazily in build_model
# so only the selected provider's SDK needs to be installed.
MODEL_PROVIDERS: dict[str, str] = {
    "openrouter": "agno_spec_builder.providers.openrouter:OpenRouter",
    "openai": "agno_spec_builder.providers.openai:OpenAIChat",
    "openai-responses": "agno.models.openai.responses:OpenAIResponses",
    "deepseek": "agno.models.deepseek:DeepSeek",
    "anthropic": "agno_spec_builder.providers.claude:Claude",
    "google": "agno_spec_builder.providers.google:Gemini",
    "gemini": "agno_spec_builder.providers.google:Gemini",
    "meta": "agno.models.meta:Llama",
    "xai": "agno.models.xai:xAI",
    "aws": "agno.models.aws:AwsBedrock",
    "azure": "agno.models.azure:AzureAIFoundry",
}


def resolve_model(
    config: ModelConfig,
    catalog: dict[str, ModelConfig] | None = None,
) -> ModelConfig:
    """Inline `{provider, id}` or catalog ref `{id: <catalog-key>}`."""
    if config.provider:
        return config
    return resolve([config.id], catalog or {})[0]


def build_model(
    config: ModelConfig,
    catalog: dict[str, ModelConfig] | None = None,
    providers: dict[str, ProviderConfig] | None = None,
) -> Model:
    config = resolve_model(config, catalog)
    spec = MODEL_PROVIDERS.get(config.provider)
    if spec is None:
        raise ValueError(f"Provider {config.provider!r} not supported")
    model_cls = resolve_symbol(spec)
    reasoning_effort = None if config.reasoning_effort == "off" else config.reasoning_effort
    from agno_spec_builder.builders.providers import resolve_provider_spec

    provider_kw = resolve_provider_spec(config.provider, "models", providers)
    kw = {**provider_kw, **config.model_kwargs()}
    return model_cls(
        id=config.id,
        reasoning_effort=reasoning_effort,
        **kw,
    )


def build_agent(
    config: AgentConfig,
    skills: list[SkillConfig],
    schemas: SchemaBuilder,
    db: BaseDb,
    knowledge: dict | None = None,
    context_providers: dict | None = None,
    models: dict[str, ModelConfig] | None = None,
    learning: dict | None = None,
    providers: dict[str, ProviderConfig] | None = None,
    skills_cache: SkillCache = skill_cache,
    toolsets: dict[str, Toolkit] | None = None,
) -> Agent:
    # Only attach capabilities the agent actually declares. An empty Skills
    # loader still exposes get_skill_* tools, so a no-skill agent would invent
    # skill names and loop — so wire skills/tools/hooks only when present.
    kwargs = config.agent_kwargs()
    if config.mcp:
        kwargs.setdefault("retries", 2)
        kwargs.setdefault("delay_between_retries", 3)
        kwargs.setdefault("exponential_backoff", True)
    if config.skills:
        kwargs["skills"] = Skills(loaders=skill_registry(config.skills, skills, skills_cache))
    tools = []
    available_tools = {**TOOL_REGISTRY, **(toolsets or {})}
    for entry in map(_as_ref, config.tools):
        # agno reasoning toolkits need live objects, so they build here instead
        # of living in TOOL_REGISTRY. include/exclude filtering applies as usual.
        if entry.name == "memory-tools":
            from agno.tools.memory import MemoryTools

            tools += filter_tools([MemoryTools(db=db)], entry)
        elif entry.name == "knowledge-tools":
            from agno.tools.knowledge import KnowledgeTools

            if not isinstance(config.knowledge, str):
                raise ValueError(f"agent {config.slug!r}: knowledge-tools needs `knowledge:` set to one base name")
            (kb,) = resolve([config.knowledge], knowledge or {})
            tools += filter_tools([KnowledgeTools(knowledge=kb)], entry)
            # KnowledgeTools brings its own search_knowledge; avoid a duplicate.
            kwargs.setdefault("search_knowledge", False)
        elif entry.name == "knowledge-writer":
            from agno_spec_builder.tools.knowledge import KnowledgeWriterTools

            if not knowledge:
                raise ValueError(f"agent {config.slug!r}: knowledge-writer needs a `knowledge:` catalog")
            tools += filter_tools([KnowledgeWriterTools(dict(knowledge))], entry)
        else:
            tools += filter_tools(resolve([entry.name], available_tools), entry)
    # Each named ContextProvider contributes tools (query_<name> or its
    # underlying toolset, per its mode), allow/drop-filtered per agent.
    for entry in map(_as_ref, config.context):
        (provider,) = resolve([entry.name], context_providers or {})
        tools += filter_tools(list(provider.get_tools()), entry)
    if isinstance(config.knowledge, str):
        (kwargs["knowledge"],) = resolve([config.knowledge], knowledge or {})
        kwargs.setdefault("search_knowledge", True)
    elif config.knowledge:  # list -> multi-KB hub search tool instead of agno's single-KB search
        from agno_spec_builder.tools.knowledge import KnowledgeHubTools

        kbs = resolve(config.knowledge, knowledge or {})
        tools.append(KnowledgeHubTools(dict(zip(config.knowledge, kbs, strict=True))))
    if tools:
        kwargs["tools"] = tools
    if config.learning is not None:
        if isinstance(config.learning, bool):
            kwargs["learning"] = config.learning  # native passthrough: agno builds a default machine
        else:
            (kwargs["learning"],) = resolve([config.learning], learning or {})
    if config.skills or tools or config.mcp or config.workflow_tools or config.tool_hooks:
        kwargs["tool_hooks"] = [log_tool_use, *_build_tool_hooks(config.tool_hooks)]
    if config.input_schema:
        kwargs["input_schema"] = schemas.output_schema(config.input_schema)
    if config.output_schema:
        kwargs["output_schema"] = schemas.output_schema(config.output_schema)
        # Tool/function calls and native structured-output mode are mutually
        # exclusive on most providers, so an agent with both falls back to
        # asking the model to emit JSON in prose and regex-parsing it — fragile,
        # especially for nested schemas. agno's parser_model sidesteps this: the
        # primary call runs unconstrained (free to use tools), then a tool-free
        # second call reformats its output into output_schema via native mode.
        if config.parser_model or config.skills or config.tools or config.mcp or config.workflow_tools:
            kwargs["parser_model"] = build_model(config.parser_model or config.model, models, providers)
    if config.mcp:
        kwargs["metadata"] = {**(kwargs.get("metadata") or {}), "mcp": config.mcp}
    # fallback_config wins if both are set (matches agno's own precedence).
    if config.fallback_config:
        kwargs["fallback_config"] = AgnoFallbackConfig(
            on_error=[build_model(m, models, providers) for m in config.fallback_config.on_error],
            on_rate_limit=[build_model(m, models, providers) for m in config.fallback_config.on_rate_limit],
            on_context_overflow=[build_model(m, models, providers) for m in config.fallback_config.on_context_overflow],
        )
    elif config.fallback_models:
        kwargs["fallback_models"] = [build_model(m, models, providers) for m in config.fallback_models]
    if config.followup_model:
        kwargs["followup_model"] = build_model(config.followup_model, models, providers)
    if config.pre_hooks:
        kwargs["pre_hooks"] = resolve(config.pre_hooks, HOOK_REGISTRY)
    if config.post_hooks:
        kwargs["post_hooks"] = resolve(config.post_hooks, HOOK_REGISTRY)
    # id == slug: stable identity for team delegation/selection and run tracking.
    return Agent(id=config.slug, db=db, model=build_model(config.model, models, providers), **kwargs)


def attach_workflow_tools(agent: Agent, refs: list[str | ToolRef], workflows: dict) -> None:
    """Late-attach WorkflowTools to an already-built agent. Workflows aren't built
    when build_agent runs (agents build first so workflows can reference them), so
    an agent's `workflow_tools:` slugs are resolved here — after the workflow
    registry exists — and each wrapped workflow is added as a tool the agent can
    call (async_mode=True for our streaming stack). include/exclude filtering drops
    run/think/analyze per agent, same as any toolkit."""
    from agno.tools.workflow import WorkflowTools

    for entry in map(_as_ref, refs):
        (wf,) = resolve([entry.name], workflows)
        for tool in filter_tools([WorkflowTools(workflow=wf, async_mode=True)], entry):
            agent.add_tool(tool)
