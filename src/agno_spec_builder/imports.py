"""Cached lazy imports for optional providers and adapters."""

import importlib
from functools import cache
from typing import Any


@cache
def resolve_symbol(target: str) -> Any:
    """Resolve ``module:attribute`` once; modules remain lazy until selected."""
    module_name, separator, attribute = target.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError(f"invalid import target {target!r}; expected 'module:attribute'")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ImportError(
            f"Could not import provider {target!r}. Install the provider's optional SDK dependency."
        ) from exc
    try:
        return getattr(module, attribute)
    except AttributeError as exc:
        raise ImportError(f"Provider target {target!r} does not exist") from exc
