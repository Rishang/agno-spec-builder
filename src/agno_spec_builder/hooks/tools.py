"""Tool-call hooks: per-invocation logging and YAML-driven hook stacking."""

import inspect
from collections.abc import Callable
from typing import Any

from agno_spec_builder.schemas import ToolHookRef
from agno_spec_builder.utils import log


async def log_tool_use(function_name, function_call, arguments):
    """Tool hook: log every tool/skill call (skills, plain tools, and MCP tools).
    Async-only — requires arun(); sync agent.run() will get an unawaited coroutine.
    inspect.isawaitable handles sync tools correctly on the arun() path."""
    log.info(f"using {function_name}({arguments})")
    result = function_call(**arguments)
    if inspect.isawaitable(result):
        result = await result
    return result


def build_tool_hooks(refs: list[ToolHookRef]) -> list[Callable[..., Any]]:
    """Resolve YAML tool_hooks entries via TOOL_HOOK_BUILDERS."""
    from agno_spec_builder.hooks import TOOL_HOOK_BUILDERS

    out: list[Callable[..., Any]] = []
    for ref in refs:
        builder = TOOL_HOOK_BUILDERS.get(ref.name)
        if builder is None:
            raise ValueError(f"Unknown tool_hook {ref.name!r}. known={list(TOOL_HOOK_BUILDERS)}")
        out.append(builder(ref.model_dump(exclude_none=True)))
    return out
