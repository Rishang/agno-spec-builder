"""Provider runtime settings — prompt-cache toggle and shared helpers."""

import os
from dataclasses import dataclass


@dataclass
class ProviderSettings:
    """Simple toggle read from the environment at import time."""

    enable_prompt_cache: bool = True

    def __post_init__(self):
        env = os.getenv("AGNO_ENABLE_PROMPT_CACHE", "").lower()
        if env in ("0", "false", "no"):
            self.enable_prompt_cache = False


provider_settings = ProviderSettings()


def cache_session_id(run_response) -> str | None:
    """Session id truncated to provider cache-key limits, or None."""
    sid = getattr(run_response, "session_id", None) if run_response else None
    return sid[:256] if sid else None
