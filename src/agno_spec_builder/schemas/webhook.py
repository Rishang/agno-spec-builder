"""Declarative inbound webhook configuration."""

from string import Formatter
from typing import Any, Literal

import jmespath
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WebhookKind = Literal["agent", "team", "workflow"]


class WebhookMatch(BaseModel):
    """An optional JMESPath equality condition over a JSON webhook body."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, description="JMESPath expression evaluated against the webhook JSON body.")
    value: Any = Field(description="The value the JMESPath result must equal.")

    @field_validator("field")
    @classmethod
    def valid_jmespath(cls, value: str) -> str:
        try:
            jmespath.compile(value)
        except Exception as error:
            raise ValueError(f"invalid JMESPath expression: {error}") from error
        return value


class WebhookTrigger(BaseModel):
    """One agent, team, or workflow invocation configured for an inbound webhook."""

    model_config = ConfigDict(extra="forbid")

    kind: WebhookKind = "agent"
    name: str = Field(min_length=1, description="Slug of the agent, team, or workflow to invoke.")
    match: WebhookMatch | None = Field(default=None, description="Optional payload condition for this trigger.")
    prompt: str = Field(min_length=1, description="Prompt template; `{payload}` expands to the JSON body.")

    @field_validator("prompt")
    @classmethod
    def only_payload_template_variable(cls, value: str) -> str:
        for _, field_name, format_spec, conversion in Formatter().parse(value):
            if field_name is None:
                continue
            if field_name != "payload" or format_spec or conversion:
                raise ValueError("webhook prompt templates support only the `{payload}` variable")
        return value


class WebhookConfig(BaseModel):
    """One authenticated inbound webhook route."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Unique webhook name.")
    path: str = Field(description="Route suffix under `/webhooks/`, for example `grafana-alerts`.")
    secret: str = Field(min_length=1, description="Shared secret; environment references expand when AgentOS is built.")
    secret_header: str = Field(
        default="X-Webhook-Secret",
        min_length=1,
        description="HTTP header containing the shared secret.",
    )
    triggers: list[WebhookTrigger] = Field(min_length=1, description="Agent triggers evaluated against the JSON body.")

    @field_validator("path")
    @classmethod
    def path_suffix(cls, value: str) -> str:
        if not value or value.startswith("/") or value.endswith("/") or "//" in value:
            raise ValueError("webhook path must be a non-empty suffix without leading or trailing slashes")
        return value

    @property
    def endpoint(self) -> str:
        """The fixed-prefix POST route exposed by this webhook."""
        return f"/webhooks/{self.path}"

    @model_validator(mode="after")
    def unique_trigger_agents(self) -> "WebhookConfig":
        names = [trigger.name for trigger in self.triggers]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate webhook trigger agents: {duplicates}")
        return self
