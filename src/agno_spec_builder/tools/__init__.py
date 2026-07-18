"""Built-in tools and configurable toolset factories."""

from collections.abc import Callable

from agno.tools import Function, Toolkit
from agno.tools.calculator import CalculatorTools
from agno.tools.coding import CodingTools
from agno.tools.python import PythonTools
from agno.tools.user_feedback import UserFeedbackTools

from agno_spec_builder.imports import resolve_symbol
from agno_spec_builder.tools.a2a import A2ATools
from agno_spec_builder.tools.bash import BashTools
from agno_spec_builder.tools.openai import OpenAICompatibleTools

ToolsetBuilder = Callable[..., Toolkit]

TOOL_REGISTRY: dict[str, Function | Toolkit] = {
    "bash": BashTools(),
    "coding": CodingTools(),
    "python": PythonTools(),
    "calculator": CalculatorTools(),
    "ask_user": UserFeedbackTools(),
}

def _agno_toolset(target: str, **kwargs) -> Toolkit:
    """Build an optional Agno toolkit without importing its SDK until selected."""
    kwargs.pop("name", None)  # these Agno toolkits provide their own Toolkit name
    return resolve_symbol(target)(**kwargs)


def _openai_tools(**kwargs) -> Toolkit:
    # Agno's built-in OpenAITools does not accept a custom base_url. Keep it
    # for the normal OpenAI path; use the compatible audio wrapper on request.
    if kwargs.get("base_url"):
        kwargs.pop("name", None)
        return OpenAICompatibleTools(**kwargs)
    return _agno_toolset("agno.tools.openai:OpenAITools", **kwargs)


def _elevenlabs_tools(**kwargs) -> Toolkit:
    return _agno_toolset("agno.tools.eleven_labs:ElevenLabsTools", **kwargs)


def _firecrawl_tools(**kwargs) -> Toolkit:
    return _agno_toolset("agno.tools.firecrawl:FirecrawlTools", **kwargs)


TOOLSET_REGISTRY: dict[str, ToolsetBuilder] = {
    "a2a": A2ATools,
    "openai": _openai_tools,
    "elevenlabs": _elevenlabs_tools,
    "firecrawl": _firecrawl_tools,
}

__all__ = ["TOOLSET_REGISTRY", "TOOL_REGISTRY", "A2ATools", "BashTools"]
