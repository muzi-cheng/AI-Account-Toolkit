from __future__ import annotations

import json
import os
from datetime import datetime

from app.domain.models.run_state import RunState


class JsonRunStateRepository:
    """基于 JSON 文件的运行状态仓储。"""

    def __init__(self, filepath: str, default_state: RunState | None = None):
        self.filepath = filepath
        self.default_state = default_state or RunState()

    def load(self) -> RunState:
        if not os.path.exists(self.filepath):
            return RunState.from_dict(self.default_state.to_dict())
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"⚠️ 加载 {os.path.basename(self.filepath)} 失败: {e}")
            return RunState.from_dict(self.default_state.to_dict())

        merged = self.default_state.to_dict()
        if isinstance(data, dict):
            merged.update(data)
        return RunState.from_dict(merged)

    def save(self, state: RunState) -> RunState:
        payload = self.default_state.to_dict()
        payload.update((state or self.default_state).to_dict())
        payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
        os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return RunState.from_dict(payload)
