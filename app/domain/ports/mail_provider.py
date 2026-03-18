from __future__ import annotations

from typing import Protocol

from app.domain.models.mailbox import Mailbox


class MailProvider(Protocol):
    """邮件服务端口。"""

    def create_mailbox(self) -> Mailbox:
        ...

    def fetch_latest_email_content(self, mailbox: Mailbox) -> str | None:
        ...
