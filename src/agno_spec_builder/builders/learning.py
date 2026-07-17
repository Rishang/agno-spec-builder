"""Build named Agno LearningMachine instances."""

from typing import Any

from agno.db.base import BaseDb
from agno.db.in_memory import InMemoryDb

from agno_spec_builder.imports import resolve_symbol
from agno_spec_builder.schemas import LearningConfig, ModelConfig
from agno_spec_builder.schemas.provider import ProviderConfig
from agno_spec_builder.utils import resolve

_STORE_CONFIGS: dict[str, str] = {
    "user_profile": "agno.learn.config:UserProfileConfig",
    "user_memory": "agno.learn.config:UserMemoryConfig",
    "session_context": "agno.learn.config:SessionContextConfig",
    "entity_memory": "agno.learn.config:EntityMemoryConfig",
    "learned_knowledge": "agno.learn.config:LearnedKnowledgeConfig",
    "decision_log": "agno.learn.config:DecisionLogConfig",
}


def _store(key: str, value: bool | dict, model, knowledge: dict, db: BaseDb) -> Any:
    if isinstance(value, bool):
        return value
    from agno.learn.config import LearningMode

    kwargs = dict(value)
    kwargs.setdefault("model", model)
    if isinstance(kwargs.get("mode"), str):
        kwargs["mode"] = LearningMode(kwargs["mode"])
    if key == "learned_knowledge":
        if isinstance(kwargs.get("knowledge"), str):
            (kwargs["knowledge"],) = resolve([kwargs["knowledge"]], knowledge or {})
    else:
        kwargs.setdefault("db", db)
    return resolve_symbol(_STORE_CONFIGS[key])(**kwargs)


def build_learning(
    cfg: LearningConfig,
    models: dict[str, ModelConfig] | None = None,
    knowledge: dict | None = None,
    providers: dict[str, ProviderConfig] | None = None,
    db: BaseDb | None = None,
):
    """Convert a learning config into a live LearningMachine."""
    from agno.learn import LearningMachine

    from agno_spec_builder.builders.agents import build_model

    db = db or InMemoryDb()
    model = build_model(cfg.model, models, providers)
    stores = {key: _store(key, getattr(cfg, key), model, knowledge or {}, db) for key in _STORE_CONFIGS}
    extras = cfg.model_dump(exclude={"name", "model", "namespace", *_STORE_CONFIGS})
    return LearningMachine(db=db, model=model, namespace=cfg.namespace, **stores, **extras)
