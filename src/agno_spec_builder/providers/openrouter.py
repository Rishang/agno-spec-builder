"""OpenRouter model with prompt-cache session-id support."""

import os
from dataclasses import dataclass, field

from agno.models.openrouter import OpenRouter as _OpenRouter

from agno_spec_builder.providers import cache_session_id, provider_settings
from agno_spec_builder.utils import log


@dataclass
class OpenRouter(_OpenRouter):
    base_url: str = field(default_factory=lambda: os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))

    def get_request_params(self, response_format=None, tools=None, tool_choice=None, run_response=None):
        params = super().get_request_params(
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
        )
        if not provider_settings.enable_prompt_cache:
            return params
        sid = cache_session_id(run_response)
        if sid:
            params["extra_headers"] = {
                **(params.get("extra_headers") or self.extra_headers or {}),
                "x-session-id": sid,
            }
            log.debug("openrouter prompt-cache x-session-id=%r model=%r", sid, self.id)
        elif run_response:
            log.debug("openrouter no session_id model=%r — sticky via message hash", self.id)
        return params
