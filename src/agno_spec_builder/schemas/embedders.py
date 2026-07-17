"""Embedder YAML config."""

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EmbedderConfig(BaseModel):
    # extra="allow": any agno Embedder arg set in YAML passes straight through.
    model_config = ConfigDict(extra="allow")

    provider: str = Field(
        default="",
        description=(
            "Embedding provider name via EMBEDDERS, e.g. 'openai', 'gemini'. "
            "Omit with only `id:` to reference the top-level `embedders:` catalog."
        ),
    )
    id: str = Field(
        default="",
        description=(
            "Provider model id (e.g. 'text-embedding-3-small') when `provider` is set, "
            "or a catalog ref to top-level `embedders:` when `provider` is omitted."
        ),
    )
    dimensions: int | None = Field(default=None, description="Number of dimensions for the embedding (optional).")

    @model_validator(mode="before")
    @classmethod
    def _model_alias_to_id(cls, data: Any) -> Any:
        # Legacy YAML used `model:` — agno embedders take `id:`.
        if isinstance(data, dict) and "model" in data and "id" not in data:
            data = dict(data)
            data["id"] = data.pop("model")
        elif isinstance(data, dict) and "model" in data:
            data = {k: v for k, v in data.items() if k != "model"}
        return data

    @model_validator(mode="after")
    def _inline_or_catalog_ref(self) -> Self:
        if self.provider:
            return self
        if self.id:
            return self
        raise ValueError("embedder needs `provider` or catalog `id`")

    def embedder_kwargs(self) -> dict[str, Any]:
        """Passthrough kwargs for the concrete embedder constructor."""
        _WIRE = {"provider", "id", "model"}
        kw = self.model_dump(exclude=_WIRE, exclude_none=True, exclude_defaults=True)
        if self.id:
            kw["id"] = self.id
        return kw
