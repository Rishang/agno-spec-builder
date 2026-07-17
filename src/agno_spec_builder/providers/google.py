"""Google Gemini model re-export and batched embedder."""

import asyncio
from dataclasses import dataclass
from typing import Any

from agno.knowledge.embedder.google import GeminiEmbedder as _GeminiEmbedder
from agno.models.google import Gemini
from agno.utils.log import log_error, log_info

__all__ = ["Gemini", "GeminiEmbedder"]


@dataclass
class GeminiEmbedder(_GeminiEmbedder):
    """Per-text concurrent batch embedder (Gemini returns one vector per request)."""

    enable_batch: bool = True
    embed_concurrency: int = 8

    async def _embed(self, text: str, task_type: str) -> tuple[list[float], dict[str, Any] | None]:
        if not (text or "").strip():
            raise ValueError("empty text — nothing to embed")
        _id = self.id.removeprefix("models/")
        config: dict[str, Any] = {"task_type": task_type}
        if self.dimensions:
            config["output_dimensionality"] = self.dimensions
        if self.title:
            config["title"] = self.title
        params: dict[str, Any] = {"contents": text, "model": _id, "config": config}
        if self.request_params:
            params.update(self.request_params)
        usage: dict[str, Any] | None = None
        try:
            response = await self.aclient.aio.models.embed_content(**params)
            if response.metadata and hasattr(response.metadata, "billable_character_count"):
                usage = {"billable_character_count": response.metadata.billable_character_count}
            if response.embeddings and response.embeddings[0].values is not None:
                return response.embeddings[0].values, usage
            log_info("No embeddings found in response")
            return [], usage
        except Exception as e:
            log_error(f"Error extracting embeddings: {e}")
            raise

    async def async_get_embedding_and_usage(self, text: str) -> tuple[list[float], dict[str, Any] | None]:
        return await self._embed(text, "RETRIEVAL_QUERY")

    async def async_get_embeddings_batch_and_usage(
        self, texts: list[str]
    ) -> tuple[list[list[float]], list[dict[str, Any] | None]]:
        sem = asyncio.Semaphore(self.embed_concurrency)

        async def one(t: str):
            async with sem:
                return await self._embed(t, "RETRIEVAL_DOCUMENT")

        results = await asyncio.gather(*(one(t) for t in texts))
        return [e for e, _ in results], [u for _, u in results]
