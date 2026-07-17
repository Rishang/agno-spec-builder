"""Model YAML config."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelConfig(BaseModel):
    # extra="allow": any agno Model arg (cache_response, retries, ...) set in YAML
    # flows straight to the constructor — no need to mirror agno's fields here.
    # extra_headers / extra_body: OpenRouter request passthrough.
    # extended_cache_time / prompt_cache_retention: src/providers/* when ENABLE_PROMPT_CACHE=true.
    model_config = ConfigDict(extra="allow")

    id: str = Field(
        description=(
            "Provider model id when `provider` is set, "
            "or a catalog ref to top-level `models:` when `provider` is omitted."
        ),
    )
    provider: str = Field(
        default="",
        description=(
            "Selects the agno Model class via MODEL_PROVIDERS, e.g. 'openrouter', 'anthropic'. "
            "Omit with only `id:` to reference the top-level `models:` catalog."
        ),
    )
    reasoning_effort: Literal["off", "low", "medium", "high"] = Field(
        default="off",
        description=("Reasoning effort hint passed to models that support it. 'off' omits the param."),
    )
    extra_headers: dict[str, str] = Field(
        default_factory=dict,
        description=("Extra HTTP headers sent with each request (e.g. OpenRouter routing hints)."),
    )
    extra_body: dict[str, Any] = Field(
        default_factory=dict,
        description=("Extra JSON fields merged into the request body (provider-specific options)."),
    )

    @model_validator(mode="before")
    @classmethod
    def _name_alias_to_id(cls, data: Any) -> Any:
        # Legacy YAML used `name:` for the provider model id — agno models take `id:`.
        if isinstance(data, dict) and "name" in data and "id" not in data:
            data = dict(data)
            data["id"] = data.pop("name")
        elif isinstance(data, dict) and "name" in data:
            data = {k: v for k, v in data.items() if k != "name"}
        return data

    def model_kwargs(self) -> dict[str, Any]:
        """Passthrough kwargs for the concrete model constructor.
        id/provider/reasoning_effort are wired explicitly in builder.py."""
        _WIRE = {"id", "provider", "reasoning_effort", "name"}
        return self.model_dump(exclude=_WIRE, exclude_none=True, exclude_defaults=True)


class FallbackConfig(BaseModel):
    """Mirrors agno's FallbackConfig — per-error-type model routing. Model lists
    use the same shape as `model:`/`parser_model:`."""

    on_error: list[ModelConfig] = Field(
        default_factory=list,
        description="Models tried in order, in addition to any error-specific list below.",
    )
    on_rate_limit: list[ModelConfig] = Field(
        default_factory=list,
        description="Models tried, in order, specifically on 429 rate-limit errors.",
    )
    on_context_overflow: list[ModelConfig] = Field(
        default_factory=list,
        description=("Models tried, in order, specifically when the context window is exceeded."),
    )
