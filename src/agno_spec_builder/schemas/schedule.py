"""Declarative schedule configuration retained in the built graph."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ScheduleKind = Literal["agent", "team", "workflow"]
_ROUTE_PREFIX: dict[ScheduleKind, str] = {
    "agent": "/agent",
    "team": "/team",
    "workflow": "/workflow",
}


class ScheduleConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(description="Unique schedule name.")
    cron: str = Field(description="Standard five-field cron expression.")
    kind: ScheduleKind
    slug: str
    method: str = "POST"
    payload: dict[str, Any] | None = None
    timezone: str = "UTC"

    @property
    def endpoint(self) -> str:
        return f"{_ROUTE_PREFIX[self.kind]}/{self.slug}/run"
