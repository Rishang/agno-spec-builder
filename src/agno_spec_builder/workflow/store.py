"""State-store contract and in-memory default for resumable workflow fan-out."""

from typing import Protocol


class FanoutStateStore(Protocol):
    def load(self, run_id: str) -> dict | None: ...
    def save(self, run_id: str, workflow_id: str, step_name: str, state: dict) -> None: ...
    def delete(self, run_id: str) -> None: ...


class InMemoryFanoutStore:
    def __init__(self) -> None:
        self._runs: dict[str, dict] = {}

    def load(self, run_id: str) -> dict | None:
        return self._runs.get(run_id)

    def save(self, run_id: str, workflow_id: str, step_name: str, state: dict) -> None:
        self._runs[run_id] = state

    def delete(self, run_id: str) -> None:
        self._runs.pop(run_id, None)
