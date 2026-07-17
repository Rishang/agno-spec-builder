"""Small helpers shared by schemas and builders."""

import logging
import os
import re
from typing import Any

log = logging.getLogger("agno_spec_builder")


def is_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_]+", value))


_ENV_REF = re.compile(r"\$\{input:(\w+)\}|\$\{(\w+)\}|\$([A-Za-z_]\w*)")


def expand_env(value: Any) -> Any:
    """Expand ``$VAR``, ``${VAR}``, and ``${input:var}`` recursively."""

    def env(name: str) -> str:
        if name in os.environ:
            return os.environ[name]
        if name.upper() in os.environ:
            return os.environ[name.upper()]
        raise KeyError(name)

    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            input_key = match.group(1)
            name = input_key or match.group(2) or match.group(3)
            try:
                return env(name)
            except KeyError:
                if input_key:
                    raise ValueError(f"MCP secret ${{input:{input_key}}} not set; define {name.upper()}") from None
                raise ValueError(f"environment variable ${name} is referenced but not set") from None

        return "$".join(_ENV_REF.sub(replace, part) for part in value.split("$$"))
    if isinstance(value, dict):
        return {key: expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_env(item) for item in value]
    return value


def slugify(text: str) -> str:
    return text.lower().replace(" ", "-").replace("_", "-")


def resolve[T](names: list[str], registry: dict[str, T]) -> list[T]:
    resolved: list[T] = []
    for name in names:
        if name not in registry:
            raise ValueError(f"Unknown name: {name!r}. Available: {list(registry)}")
        resolved.append(registry[name])
    return resolved
