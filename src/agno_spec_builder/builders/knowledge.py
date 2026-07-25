"""Build Agno Knowledge objects from declarative config."""

from typing import Any

from agno.db.base import BaseDb

from agno_spec_builder.imports import resolve_symbol
from agno_spec_builder.schemas.embedders import EmbedderConfig
from agno_spec_builder.schemas.knowledge import KnowledgeConfig
from agno_spec_builder.schemas.provider import ProviderConfig
from agno_spec_builder.utils import expand_env, resolve

# YAML `provider:` name -> "module:Class", imported lazily on build.
VECTOR_DBS: dict[str, str] = {
    "lancedb": "agno.vectordb.lancedb:LanceDb",
    "chroma": "agno.vectordb.chroma:ChromaDb",
    "pgvector": "agno.vectordb.pgvector:PgVector",
    "qdrant": "agno.vectordb.qdrant:Qdrant",
    "mongodb": "agno.vectordb.mongodb:MongoDb",
}

RERANKERS: dict[str, str] = {
    "cohere": "agno.knowledge.reranker.cohere:CohereReranker",
    "infinity": "agno.knowledge.reranker.infinity:InfinityReranker",
    "sentence-transformer": "agno.knowledge.reranker.sentence_transformer:SentenceTransformerReranker",
    "aws": "agno.knowledge.reranker.aws_bedrock:AwsBedrockReranker",
}

EMBEDDERS: dict[str, str] = {
    "openai": "agno_spec_builder.providers.openai:OpenAIEmbedder",
    "openai-like": "agno.knowledge.embedder.openai_like:OpenAILikeEmbedder",
    "google": "agno_spec_builder.providers.google:GeminiEmbedder",
    "gemini": "agno_spec_builder.providers.google:GeminiEmbedder",
    "mistral": "agno.knowledge.embedder.mistral:MistralEmbedder",
    "ollama": "agno.knowledge.embedder.ollama:OllamaEmbedder",
    "fastembed": "agno.knowledge.embedder.fastembed:FastEmbedEmbedder",
    "sentence-transformer": "agno.knowledge.embedder.sentence_transformer:SentenceTransformerEmbedder",
}

# Lazy — semantic/markdown pull heavy optional deps.
CHUNKERS: dict[str, str] = {
    "fixed": "agno.knowledge.chunking.fixed:FixedSizeChunking",
    "recursive": "agno.knowledge.chunking.recursive:RecursiveChunking",
    "document": "agno.knowledge.chunking.document:DocumentChunking",
    "agentic": "agno.knowledge.chunking.agentic:AgenticChunking",
    "markdown": "agno.knowledge.chunking.markdown:MarkdownChunking",
    "semantic": "agno.knowledge.chunking.semantic:SemanticChunking",
    "row": "agno.knowledge.chunking.row:RowChunking",
    "code": "agno.knowledge.chunking.code:CodeChunking",
}


def _load(registry: dict[str, str], spec: dict[str, Any], what: str):
    kwargs = dict(spec)
    provider = kwargs.pop("provider", None)
    path = registry.get(provider or "")
    if path is None:
        raise ValueError(f"{what} provider {provider!r} not supported (known: {list(registry)})")
    return resolve_symbol(path)(**kwargs)


def build_embedder(
    config: EmbedderConfig,
    catalog: dict[str, EmbedderConfig] | None = None,
    providers: dict[str, ProviderConfig] | None = None,
):
    """EmbedderConfig -> live agno Embedder. Inline `{provider,id}` or catalog `{id:}`.
    A matching `providers:` entry of kind `embedders` (same name as `config.provider`)
    contributes connection kwargs (api_key, base_url, …) merged into the call."""
    if not config.provider:
        if not config.id:
            raise ValueError("Embedder needs `provider` or catalog `id`")
        config = resolve([config.id], catalog or {})[0]
    path = EMBEDDERS.get(config.provider)
    if path is None:
        raise ValueError(f"Embedder provider {config.provider!r} not supported (known: {list(EMBEDDERS)})")
    from agno_spec_builder.builders.providers import resolve_provider_spec

    provider_kw = resolve_provider_spec(config.provider, "embedders", providers)
    kw = {**provider_kw, **config.embedder_kwargs()}
    return resolve_symbol(path)(**kw)


def _chunked_readers(chunking: dict[str, Any]) -> dict:
    """text/website readers with the configured chunker; skip if optional deps missing."""
    from agno.knowledge.reader.reader_factory import ReaderFactory

    spec = dict(chunking)
    strategy = _load(CHUNKERS, {"provider": spec.pop("strategy", None), **spec}, "chunking")
    readers: dict = {}
    for key in ("text", "website"):
        try:
            readers[key] = ReaderFactory.create_reader(key, chunking_strategy=strategy)
        except Exception:
            continue
    return readers


def build_knowledge(
    cfg: KnowledgeConfig,
    embedders: dict[str, EmbedderConfig] | None = None,
    providers: dict[str, ProviderConfig] | None = None,
    db: BaseDb | None = None,
    namespace: str | None = None,
):
    """KnowledgeConfig -> live agno Knowledge, contents tracked in the shared DB.
    A `providers:` entry of kind `vectordb` whose name matches the vector_db's
    `provider` contributes connection kwargs (api_key, url, …) merged into the
    vector db constructor call."""
    from agno.db.in_memory import InMemoryDb
    from agno.knowledge.knowledge import Knowledge

    db = db or InMemoryDb()
    vdb_spec = expand_env(dict(cfg.vector_db))
    if cfg.embedder:
        vdb_spec["embedder"] = build_embedder(cfg.embedder, embedders, providers)
    # Merge a matching vectordb provider profile's spec. The profile is looked up
    # by the vector_db's `provider` field; its spec is merged *under* the inline
    # vector_db kwargs so an inline value wins over the profile default.
    from agno_spec_builder.builders.providers import resolve_provider_spec

    vdb_provider = vdb_spec.get("provider")
    vdb_spec = {**resolve_provider_spec(vdb_provider, "vectordb", providers), **vdb_spec}

    if vdb_provider == "lancedb" and "table_name" not in vdb_spec and "table" not in vdb_spec:
        # If no table_name/table is specified, use the knowledge name slugified.
        from agno_spec_builder.utils import slugify

        vdb_spec["table_name"] = slugify(cfg.name)

    if namespace:
        # These are the collection identifiers used by the supported vector
        # adapters. Keep the logical knowledge-base name stable for YAML refs.
        for key in ("collection", "collection_name", "table_name"):
            if isinstance(vdb_spec.get(key), str):
                vdb_spec[key] = f"{namespace}__{vdb_spec[key]}"

    if isinstance(reranker := vdb_spec.get("reranker"), dict):
        vdb_spec["reranker"] = _load(RERANKERS, reranker, "reranker")
    if isinstance(vdb_spec.get("search_type"), str):
        from agno.vectordb.search import SearchType

        vdb_spec["search_type"] = SearchType(vdb_spec["search_type"])
    if isinstance(vdb_spec.get("distance"), str):
        from agno.vectordb.distance import Distance

        vdb_spec["distance"] = Distance(vdb_spec["distance"])

    extras = cfg.model_dump(exclude={"name", "description", "max_results", "vector_db", "embedder", "chunking"})
    if cfg.chunking and (readers := _chunked_readers(cfg.chunking)):
        extras.setdefault("readers", readers)
    return Knowledge(
        name=cfg.name,
        description=cfg.description,
        max_results=cfg.max_results,
        contents_db=db,
        vector_db=_load(VECTOR_DBS, vdb_spec, "vector db"),
        **extras,
    )
