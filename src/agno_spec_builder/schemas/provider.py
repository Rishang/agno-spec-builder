"""Provider YAML config — connection profiles for models/embedders/vectordbs/dbs.

A top-level `providers:` entry centralizes connection kwargs (base_url, api_key,
extra headers, …) for a named provider. Other sections reference the provider by
name via their existing `provider:` field; the provider's `spec` is merged into
the constructor call at build time, so connection details live in one place.

Kinds:
- models    → merged into agno Model constructors (OpenRouter, OpenAIChat, …)
- embedders → merged into agno Embedder constructors
- vectordb  → merged into agno VectorDb constructors (Qdrant, LanceDb, …)
- db        → merged into agno Db constructors (reserved; not wired yet)

`spec` is a free-form dict (ConfigDict(extra="allow")): any kwarg the provider's
constructor accepts can be set here. Secret refs (`${env.VAR}`, `${input:var}`)
are expanded at build time via src.utils.expand_env.
"""

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The four provider kinds. `db` is reserved for agno Db connection profiles
# (SqliteDb, PostgresDb, …) — not wired into build() yet, but accepted so the
# catalog can hold the entry without a schema change later.
ProviderKind = Literal["models", "embedders", "vectordb", "db"]


class ProviderConfig(BaseModel):
    # extra="allow" on `spec` would be redundant (spec is a dict field), but we
    # keep extra="allow" on the top-level model so a flat YAML shape without an
    # explicit `spec:` nesting still works — every key except name/kind becomes
    # a spec kwarg. This mirrors the passthrough philosophy of ModelConfig.
    model_config = ConfigDict(extra="allow")

    name: str = Field(description="Provider profile name; referenced by `provider:` on models/embedders/vectordbs.")
    kind: ProviderKind = Field(description="What this provider connects to: models | embedders | vectordb | db.")
    spec: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Constructor kwargs for the provider's underlying class "
            "(base_url, api_key, extra_headers, …). Secret refs (${env.VAR}, "
            "${input:var}) are expanded at build time."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _flatten_extra_into_spec(cls, data: Any) -> Any:
        """Accept a flat shape (`name`, `kind`, `base_url`, `api_key`, …) by
        folding every non-reserved key into `spec`. A YAML author can write
        either:
            providers:
              - name: openrouter
                kind: models
                spec:
                  base_url: https://...
            or:
            providers:
              - name: openrouter
                kind: models
                base_url: https://...
        Both produce the same ProviderConfig."""
        if not isinstance(data, dict):
            return data
        reserved = {"name", "kind", "spec"}
        spec = dict(data.get("spec") or {})
        for k, v in data.items():
            if k not in reserved and k not in spec:
                spec[k] = v
        return {**{k: v for k, v in data.items() if k in reserved}, "spec": spec}

    @model_validator(mode="after")
    def _name_required(self) -> Self:
        if not self.name:
            raise ValueError("provider entry needs a `name`")
        return self

    def resolved_spec(self) -> dict[str, Any]:
        """spec with secret refs expanded (env-only today). Called at build time."""
        from agno_spec_builder.utils import expand_env

        return expand_env(self.spec)
