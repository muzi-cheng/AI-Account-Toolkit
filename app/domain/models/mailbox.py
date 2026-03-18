from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Mailbox:
    """邮箱提供方返回的收件箱信息。"""

    email: str
    access_key: str = ""
