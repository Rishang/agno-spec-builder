"""Name-to-guardrail registry for declarative pre/post hooks."""

from collections.abc import Callable
from typing import Any

from agno.eval.base import BaseEval
from agno.guardrails import PIIDetectionGuardrail, PromptInjectionGuardrail
from agno.guardrails.base import BaseGuardrail

Hook = Callable[..., Any] | BaseGuardrail | BaseEval

HOOK_REGISTRY: dict[str, Hook] = {
    "prompt_injection": PromptInjectionGuardrail(),
    "pii_detection": PIIDetectionGuardrail(),
}

try:
    from agno.guardrails import OpenAIModerationGuardrail
except ImportError:  # OpenAI SDK is an optional provider dependency.
    pass
else:
    HOOK_REGISTRY["openai_moderation"] = OpenAIModerationGuardrail()
