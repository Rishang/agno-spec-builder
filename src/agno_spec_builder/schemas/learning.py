"""Learning YAML config."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agno_spec_builder.schemas.model import ModelConfig


class LearningConfig(BaseModel):
    model_config = ConfigDict(extra="allow")  # LearningMachine kwargs passthrough

    name: str = Field(description="Learning-machine name, referenced by agents' `learning:`.")
    model: ModelConfig = Field(description="Model used to extract/curate learnings.")
    namespace: str = Field(default="global", description="Default namespace for entity_memory / learned_knowledge.")
    # Each store: false | true (agno defaults) | dict of store Config kwargs.
    user_profile: bool | dict[str, Any] = False
    user_memory: bool | dict[str, Any] = False
    session_context: bool | dict[str, Any] = False
    entity_memory: bool | dict[str, Any] = False
    learned_knowledge: bool | dict[str, Any] = False  # dict may set knowledge: <base>
    decision_log: bool | dict[str, Any] = False
