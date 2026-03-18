from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class RunState:
    status: str = "idle"
    message: str = ""
    last_run_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    updated_at: str = ""
    planned_total_accounts: int = 0
    completed_accounts: int = 0
    success_count: int = 0
    fail_count: int = 0
    elapsed_seconds: float = 0
    total_runs: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "RunState":
        payload = dict(data or {})
        return cls(
            status=str(payload.get("status", "idle") or "idle"),
            message=str(payload.get("message", "") or ""),
            last_run_id=str(payload.get("last_run_id", "") or ""),
            started_at=str(payload.get("started_at", "") or ""),
            finished_at=str(payload.get("finished_at", "") or ""),
            updated_at=str(payload.get("updated_at", "") or ""),
            planned_total_accounts=int(payload.get("planned_total_accounts", 0) or 0),
            completed_accounts=int(payload.get("completed_accounts", 0) or 0),
            success_count=int(payload.get("success_count", 0) or 0),
            fail_count=int(payload.get("fail_count", 0) or 0),
            elapsed_seconds=float(payload.get("elapsed_seconds", 0) or 0),
            total_runs=int(payload.get("total_runs", 0) or 0),
        )
