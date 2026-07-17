"""OpenAI model and embedder with prompt-cache support."""

import os
from dataclasses import dataclass

from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.models.openai import OpenAIChat as _OpenAIChat

__all__ = ["OpenAIChat", "OpenAIEmbedder"]


@dataclass
class OpenAIChat(_OpenAIChat):
    base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
