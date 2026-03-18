from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class AppSettings:
    """强类型应用配置。

    兼容当前工程仍大量使用 dict 的现状，因此同时保留 to_dict()。
    """

    total_accounts: int = 1
    max_workers: int = 1
    proxy_pool: list[str] = field(default_factory=list)
    cloudflare_api_base: str = ""
    cloudflare_domain: str = ""
    cloudflare_jwt_token: str = ""
    cloudflare_poll_attempts: int = 3
    cloudflare_poll_interval: int = 5
    log_mode: str = "dev"
    enable_oauth: bool = True
    oauth_required: bool = True
    oauth_issuer: str = "https://auth.openai.com"
    oauth_client_id: str = "app_EMoamEEZ73f0CkXaXp7hrann"
    oauth_redirect_uri: str = "http://localhost:1455/auth/callback"
    post_account_wait_min_seconds: float = 20
    post_account_wait_max_seconds: float = 60
    maintain_register_retry_limit: int = 0
    output_file: str = "codex_tokens/registered_accounts.txt"
    token_json_dir: str = "codex_tokens"
    token_storage_dir: str = "codex_tokens"
    accounts_detail_file: str = "codex_tokens/registered_accounts_details.jsonl"
    local_accounts_file: str = "codex_tokens/local/accounts.json"
    service_token_dirs: dict = field(default_factory=dict)
    upload_targets: list[str] = field(default_factory=list)
    cliproxyapi_api_base_url: str = ""
    cliproxyapi_api_path: str = "/v0/management/auth-files"
    cliproxyapi_api_token: str = ""
    cliproxyapi_delete_path: str = "/v0/management/auth-files/{filename}"
    cliproxyapi_delete_method: str = "DELETE"
    sub2api_url: str = ""
    sub2api_token: str = ""
    sub2api_platform: str = "openai"
    sub2api_type: str = "refresh_token"
    sub2api_import_path: str = "/api/v1/admin/accounts/data"
    sub2api_auth_mode: str = "bearer"
    sub2api_cookie: str = ""
    sub2api_api_key: str = ""
    sub2api_skip_default_group_bind: bool = True
    sub2api_no_proxy: bool = True
    sub2api_account_type: str = "oauth"
    sub2api_account_concurrency: int = 10
    sub2api_account_priority: int = 1
    sub2api_account_rate_multiplier: float = 1.0
    sub2api_account_auto_pause_on_expired: bool = True
    sub2api_temp_unschedulable_enabled: bool = True
    sub2api_temp_unschedulable_rules: list[dict] = field(default_factory=list)
    sub2api_group_ids: list[int] = field(default_factory=list)
    sub2api_groups: list[dict] = field(default_factory=list)
    sub2api_model_mapping: dict = field(default_factory=dict)
    token_check_url: str = "https://chatgpt.com/backend-api/wham/usage"
    token_check_timeout: float = 12
    token_check_sleep: float = 0.2
    token_check_input_file: str = "codex_tokens/local/accounts.json"
    token_check_report_file: str = "codex_tokens/token_check_report.json"
    maintain_enabled: bool = True
    maintain_check_interval_seconds: int = 1800

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "AppSettings":
        payload = dict(data or {})
        return cls(**{k: payload[k] for k in cls.__dataclass_fields__.keys() if k in payload})
