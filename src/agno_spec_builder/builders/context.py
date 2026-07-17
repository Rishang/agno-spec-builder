"""Context providers feature — named agno ContextProviders agents attach to via
`context: [<name>, ...]`. Each provider contributes tools (query_<id> or its
underlying toolset, per `mode`).

Stateless: providers hold no rows of their own; they answer from their source
(filesystem, wiki, database). Custom Python providers register here by name."""

from typing import Any

from agno_spec_builder.imports import resolve_symbol
from agno_spec_builder.schemas import ModelConfig
from agno_spec_builder.schemas.context import ContextProviderConfig
from agno_spec_builder.schemas.provider import ProviderConfig

# YAML `provider:` name -> "module:Class", imported lazily on build.
# Custom ContextProvider subclasses: add a line here and reference by name.
CONTEXT_PROVIDERS: dict[str, str] = {
    "fs": "agno.context.fs.provider:FilesystemContextProvider",
    "wiki": "agno.context.wiki.provider:WikiContextProvider",
    "database": "agno.context.database.provider:DatabaseContextProvider",
    "workspace": "agno.context.workspace.provider:WorkspaceContextProvider",
    "mcp": "agno.context.mcp.provider:MCPContextProvider",
    "drive": "agno.context.drive.provider:DriveContextProvider",
    "web": "agno.context.web.provider:WebContextProvider",
}


def build_context_provider(
    cfg: ContextProviderConfig,
    models: dict[str, ModelConfig] | None = None,
    providers: dict[str, ProviderConfig] | None = None,
):
    """ContextProviderConfig -> live agno ContextProvider."""
    from agno.context.mode import ContextMode

    path = CONTEXT_PROVIDERS.get(cfg.provider)
    if path is None:
        raise ValueError(f"Context provider {cfg.provider!r} not supported (known: {list(CONTEXT_PROVIDERS)})")
    cls = resolve_symbol(path)

    kwargs: dict[str, Any] = cfg.model_dump(exclude={"name", "provider", "mode", "model"})
    kwargs["id"] = cfg.name
    kwargs["mode"] = ContextMode(cfg.mode)
    if cfg.model is not None:
        from agno_spec_builder.builders.agents import build_model  # local: avoid import cycle

        kwargs["model"] = build_model(cfg.model, models, providers)
    return cls(**kwargs)
