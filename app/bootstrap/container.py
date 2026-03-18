from __future__ import annotations

from dataclasses import dataclass
import os

from app.config.loader import load_settings
from app.config.config import StaticConfig
from app.application.use_cases import MaintainAccountsUseCase, TokenCheckUseCase
from app.domain.models.run_state import RunState
from app.domain.models.settings import AppSettings
from app.infrastructure.mail.cloudflare_mail_provider import CloudflareMailProvider
from app.infrastructure.persistence.json_run_state_repository import JsonRunStateRepository


@dataclass(slots=True)
class AppContainer:
    base_dir: str
    settings: AppSettings
    mail_provider: CloudflareMailProvider
    run_state_repository: JsonRunStateRepository
    token_check_use_case: TokenCheckUseCase | None = None
    maintain_accounts_use_case: MaintainAccountsUseCase | None = None


def build_container(base_dir: str) -> AppContainer:
    settings = load_settings(base_dir)
    root = StaticConfig.project_root(base_dir)
    run_state_path = os.path.join(root, StaticConfig.RUN_STATE_FILE)
    return AppContainer(
        base_dir=root,
        settings=settings,
        mail_provider=CloudflareMailProvider(
            api_base=settings.cloudflare_api_base,
            domain=settings.cloudflare_domain,
            jwt_token=settings.cloudflare_jwt_token,
        ),
        run_state_repository=JsonRunStateRepository(
            filepath=run_state_path,
            default_state=RunState.from_dict(StaticConfig.DEFAULT_RUN_STATE),
        ),
        token_check_use_case=None,
        maintain_accounts_use_case=None,
    )
