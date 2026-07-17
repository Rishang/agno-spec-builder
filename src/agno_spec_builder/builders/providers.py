"""Resolve a provider profile's connection kwargs by name and kind.

`build_model` / `build_embedder` / `build_knowledge` call into here to merge a
provider's `spec` (base_url, api_key, …) into their constructor call. The catalog
is built by `src/platform/builder.py:build()` from the top-level `providers:`
YAML section and threaded through as a dict[name, ProviderConfig]."""

from typing import Any

from agno_spec_builder.schemas.provider import ProviderConfig, ProviderKind


def resolve_provider_spec(
    name: str,
    kind: ProviderKind,
    catalog: dict[str, ProviderConfig] | None,
) -> dict[str, Any]:
    """Return the resolved (env-expanded) `spec` for provider `name` of `kind`,
    or an empty dict if the name isn't in the catalog. A catalog entry whose
    `kind` doesn't match is ignored — a `models` provider named `openai` is not
    a valid `embedders` provider, even though the names collide.

    Returns {} (not an error) when no profile is registered: the `providers:`
    section is optional, and a model/embedder/vectordb can still be built from
    its own inline kwargs + env vars. A wrong-kind entry is also silently
    skipped rather than raising — the caller's own provider-class lookup
    (MODEL_PROVIDERS / EMBEDDERS / VECTOR_DBS) is the authoritative validation."""
    if not catalog or not name:
        return {}
    entry = catalog.get(name)
    if entry is None or entry.kind != kind:
        return {}
    return entry.resolved_spec()
