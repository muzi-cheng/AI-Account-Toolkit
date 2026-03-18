from __future__ import annotations

from typing import Protocol

from app.domain.models.run_state import RunState


class RunStateRepository(Protocol):
    """运行状态仓储端口。"""

    def load(self) -> RunState:
        ...

    def save(self, state: RunState) -> RunState:
        ...
