"""YAML-driven tool-call hook factories."""

import inspect
from collections.abc import Callable
from typing import Any


def static_args_hook(
    rules: list[dict[str, Any]],
) -> Callable[..., Any]:
    """Tool hook factory: force-inject kwargs for named tool functions.

    YAML::

        tool_hooks:
          - name: static_args_hook
            rules:
              - function_name: search_web
                inject: { max_results: 10 }

    Async like log_tool_use — sync agent.run() skips async tool hooks.
    """
    inject_map = {r["function_name"]: dict(r["inject"]) for r in rules}

    async def hook(function_name: str, function_call: Callable, arguments: dict[str, Any]):
        if function_name in inject_map:
            arguments.update(inject_map[function_name])
        result = function_call(**arguments)
        if inspect.isawaitable(result):
            result = await result
        return result

    return hook
