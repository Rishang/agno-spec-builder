"""State-store contract and in-memory default for resumable workflow fan-out."""

from typing import Protocol


class FanoutStateStore(Protocol):
    async def load(self, run_id: str) -> dict | None: ...
    async def save(self, run_id: str, workflow_id: str, step_name: str, state: dict) -> None: ...
    async def delete(self, run_id: str) -> None: ...


class InMemoryFanoutStore:
    def __init__(self) -> None:
        self._runs: dict[str, dict] = {}

    async def load(self, run_id: str) -> dict | None:
        return self._runs.get(run_id)

    async def save(self, run_id: str, workflow_id: str, step_name: str, state: dict) -> None:
        self._runs[run_id] = state

    async def delete(self, run_id: str) -> None:
        self._runs.pop(run_id, None)
