"""Knowledge YAML config — bases."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agno_spec_builder.schemas.embedders import EmbedderConfig


class KnowledgeConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(description="Knowledge base name, referenced by agents' `knowledge:`.")
    description: str | None = None
    max_results: int = Field(default=10, description="Max documents returned per search.")
    vector_db: dict[str, Any] = Field(
        description="{provider: lancedb|chroma|pgvector|qdrant|mongodb, ...constructor kwargs}."
    )
    embedder: EmbedderConfig | None = Field(
        default=None,
        description=("Inline embedder config or catalog ref `{id: <name>}` from top-level `embedders:`."),
    )
    chunking: dict[str, Any] | None = Field(
        default=None,
        description=(
            "{strategy: fixed|recursive|document|agentic|markdown|semantic|row, "
            "...kwargs} — chunking strategy applied to the default text/website "
            "readers (e.g. {strategy: fixed, chunk_size: 800, overlap: 100})."
        ),
    )
