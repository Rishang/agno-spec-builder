"""Anthropic Claude model with prompt-cache control."""

from dataclasses import dataclass

from agno.models.anthropic import Claude as _Claude

from agno_spec_builder.providers import provider_settings
from agno_spec_builder.utils import log


@dataclass
class Claude(_Claude):
    cache_system_prompt: bool = True
    cache_tools: bool = True

    def __post_init__(self):
        if not provider_settings.enable_prompt_cache:
            self.cache_system_prompt = False
            self.cache_tools = False
        ttl = "1h" if self.extended_cache_time else "5m"
        log.debug(
            "claude prompt-cache system=%s tools=%s ttl=%s model=%r",
            self.cache_system_prompt,
            self.cache_tools,
            ttl,
            self.id,
        )
        super().__post_init__()
