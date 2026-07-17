"""Built-in pre/post and tool-hook registries."""

from collections.abc import Callable
from typing import Any

from agno_spec_builder.hooks.guardrails import HOOK_REGISTRY
from agno_spec_builder.hooks.util import static_args_hook

TOOL_HOOK_BUILDERS: dict[str, Callable[..., Callable[..., Any]]] = {
    "static_args_hook": lambda cfg: static_args_hook(cfg.get("rules") or []),
}

__all__ = ["HOOK_REGISTRY", "TOOL_HOOK_BUILDERS", "static_args_hook"]
