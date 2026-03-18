"""静态配置（工程化常量）。

这里放“不常变”的配置：基础路径、固定 API、默认值、版本号等。
运行中会变化的状态请放到 run_state.json。
"""

from __future__ import annotations

import os


class StaticConfig:
    APP_NAME = "chatgpt_register"
    APP_VERSION = "2.0.0"

    USER_CONFIG_FILE = "config.py"
    RUN_STATE_FILE = "run_state.json"

    DEFAULTS = {
        # 运行参数（可在根目录 config.py 覆盖）
        "total_accounts": 1,
        "max_workers": 1,
        "proxy_pool": [],

        # Cloudflare 邮件
        "cloudflare_api_base": "",
        "cloudflare_domain": "",
        "cloudflare_jwt_token": "",
        "cloudflare_poll_attempts": 3,
        "cloudflare_poll_interval": 5,
        "log_mode": "dev",

        # OAuth / OpenAI
        "enable_oauth": True,
        "oauth_required": True,
        "oauth_issuer": "https://auth.openai.com",
        "oauth_client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
        "oauth_redirect_uri": "http://localhost:1455/auth/callback",

        # 账号完成后的随机等待（用于降速/错峰）
        "post_account_wait_min_seconds": 20,
        "post_account_wait_max_seconds": 60,

        "maintain_register_retry_limit": 0,

        # 产物路径（统一收敛到 codex_tokens）
        "output_file": "codex_tokens/registered_accounts.txt",
        "token_json_dir": "codex_tokens",
        "token_storage_dir": "codex_tokens",
        "accounts_detail_file": "codex_tokens/registered_accounts_details.jsonl",
        "local_accounts_file": "codex_tokens/local/accounts.json",
        "service_token_dirs": {
            "local": "local",
            "cliproxyapi": "cliproxyapi",
            "sub2api": "sub2api",
        },

        # 上传（CliProxyAPI）
        "upload_targets": [],
        "cliproxyapi_api_base_url": "",
        "cliproxyapi_api_path": "/v0/management/auth-files",
        "cliproxyapi_api_token": "",
        "cliproxyapi_delete_path": "/v0/management/auth-files/{filename}",
        "cliproxyapi_delete_method": "DELETE",

        # Sub2API
        "sub2api_url": "",
        "sub2api_token": "",
        "sub2api_platform": "openai",
        "sub2api_type": "refresh_token",
        "sub2api_import_path": "/api/v1/admin/accounts/data",
        "sub2api_auth_mode": "bearer",
        "sub2api_cookie": "",
        "sub2api_api_key": "",
        "sub2api_skip_default_group_bind": True,
        "sub2api_no_proxy": True,
        "sub2api_account_type": "oauth",
        "sub2api_account_concurrency": 10,
        "sub2api_account_priority": 1,
        "sub2api_account_rate_multiplier": 1,
        "sub2api_account_auto_pause_on_expired": True,
        "sub2api_temp_unschedulable_enabled": True,
        "sub2api_temp_unschedulable_rules": [
            {
                "description": "服务不可用 - 暂停 30 分钟",
                "duration_minutes": 30,
                "error_code": 503,
                "keywords": ["unavailable", "maintenance"],
            },
            {
                "description": "触发限流 - 暂停 10 分钟",
                "duration_minutes": 10,
                "error_code": 429,
                "keywords": ["rate limit", "too many requests"],
            },
            {
                "description": "服务过载 - 暂停 60 分钟",
                "duration_minutes": 60,
                "error_code": 529,
                "keywords": ["overloaded", "too many"],
            },
        ],
        "sub2api_group_ids": [],
        "sub2api_groups": [],
        "sub2api_model_mapping": {
            "gpt-5": "gpt-5",
            "gpt-5-codex": "gpt-5-codex",
            "gpt-5-codex-mini": "gpt-5-codex-mini",
            "gpt-5.1": "gpt-5.1",
            "gpt-5.1-codex": "gpt-5.1-codex",
            "gpt-5.1-codex-max": "gpt-5.1-codex-max",
            "gpt-5.1-codex-mini": "gpt-5.1-codex-mini",
            "gpt-5.2": "gpt-5.2",
            "gpt-5.2-codex": "gpt-5.2-codex",
            "gpt-5.3-codex": "gpt-5.3-codex",
            "gpt-5.4": "gpt-5.4",
        },

        # 本地账号巡检 / 清理
        "token_check_url": "https://chatgpt.com/backend-api/wham/usage",
        "token_check_timeout": 12,
        "token_check_sleep": 0.2,
        "token_check_input_file": "codex_tokens/local/accounts.json",
        "token_check_report_file": "codex_tokens/token_check_report.json",

        # 持续保号 / 周期巡检
        "maintain_enabled": True,
        "maintain_check_interval_seconds": 1800,
    }

    DEFAULT_RUN_STATE = {
        "status": "idle",
        "message": "",
        "last_run_id": "",
        "started_at": "",
        "finished_at": "",
        "updated_at": "",
        "planned_total_accounts": 0,
        "completed_accounts": 0,
        "success_count": 0,
        "fail_count": 0,
        "elapsed_seconds": 0,
        "total_runs": 0,
    }

    @staticmethod
    def project_root(base_dir: str | None = None) -> str:
        if base_dir:
            return base_dir
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
