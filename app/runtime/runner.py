"""
ChatGPT 批量自动注册工具 (并发版) - Cloudflare 邮箱版
依赖: pip install curl_cffi
功能: 使用 Cloudflare 域名邮箱，并发自动注册 ChatGPT 账号，自动获取 OTP 验证码
"""

import os
import itertools
import re
import uuid
import json
import random
import string
import time
import threading
import traceback
import secrets
import hashlib
import base64
from pathlib import Path
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from urllib.parse import urlparse, parse_qs, urlencode, quote

from curl_cffi import requests as curl_requests

from app.application.use_cases.token_maintenance import (
    MaintainAccountsDependencies,
    MaintainAccountsUseCase,
    TokenCheckDependencies,
    TokenCheckUseCase,
)
from app.bootstrap import build_container
from app.cli.main import build_parser
from app.config.settings import load_config, load_run_state, save_run_state
from app.infrastructure.mail.cloudflare_mail_provider import CloudflareMailProvider
from app.infrastructure.openai import build_sentinel_token
from app.utils.booleans import as_bool

# ================= 加载配置 =================

_BASE_DIR = str(Path(__file__).resolve().parents[2])
_CONFIG = load_config(_BASE_DIR)
CLOUDFLARE_API_BASE = _CONFIG["cloudflare_api_base"]
CLOUDFLARE_DOMAIN = _CONFIG["cloudflare_domain"]
CLOUDFLARE_JWT_TOKEN = _CONFIG["cloudflare_jwt_token"]
CLOUDFLARE_POLL_ATTEMPTS = max(1, int(_CONFIG.get("cloudflare_poll_attempts", 3)))
CLOUDFLARE_POLL_INTERVAL = max(1, int(_CONFIG.get("cloudflare_poll_interval", 5)))
LOG_MODE = str(_CONFIG.get("log_mode", "dev") or "dev").strip().lower()
IS_PROD_LOG = LOG_MODE in ("prod", "production")
DEFAULT_TOTAL_ACCOUNTS = _CONFIG["total_accounts"]
DEFAULT_MAX_WORKERS = _CONFIG["max_workers"]
DEFAULT_PROXY_POOL = [p for p in (_CONFIG.get("proxy_pool") or []) if str(p).strip()]
DEFAULT_OUTPUT_FILE = _CONFIG["output_file"]
ENABLE_OAUTH = as_bool(_CONFIG.get("enable_oauth", True))
OAUTH_REQUIRED = as_bool(_CONFIG.get("oauth_required", True))
OAUTH_ISSUER = _CONFIG["oauth_issuer"].rstrip("/")
OAUTH_CLIENT_ID = _CONFIG["oauth_client_id"]
OAUTH_REDIRECT_URI = _CONFIG["oauth_redirect_uri"]
TOKEN_BASE_DIR = _CONFIG.get("token_storage_dir") or _CONFIG.get("token_json_dir") or "codex_tokens"
ACCOUNTS_DETAIL_FILE = _CONFIG.get("accounts_detail_file", "registered_accounts_details.jsonl")
LOCAL_ACCOUNTS_FILE = _CONFIG.get("local_accounts_file", "local/accounts.json")
SERVICE_TOKEN_DIRS = {
    "local": ((_CONFIG.get("service_token_dirs") or {}).get("local") or "local").strip(),
    "cliproxyapi": ((_CONFIG.get("service_token_dirs") or {}).get("cliproxyapi") or "cliproxyapi").strip(),
    "sub2api": ((_CONFIG.get("service_token_dirs") or {}).get("sub2api") or "sub2api").strip(),
}
UPLOAD_TARGETS = [str(x).strip().lower() for x in (_CONFIG.get("upload_targets") or []) if str(x).strip()]
CLIPROXYAPI_API_BASE_URL = (_CONFIG.get("cliproxyapi_api_base_url", "") or "").rstrip("/")
CLIPROXYAPI_API_PATH = (_CONFIG.get("cliproxyapi_api_path", "/v0/management/auth-files") or "/v0/management/auth-files").strip()
if not CLIPROXYAPI_API_PATH.startswith("/"):
    CLIPROXYAPI_API_PATH = f"/{CLIPROXYAPI_API_PATH}"
CLIPROXYAPI_API_URL = f"{CLIPROXYAPI_API_BASE_URL}{CLIPROXYAPI_API_PATH}" if CLIPROXYAPI_API_BASE_URL else ""
CLIPROXYAPI_API_TOKEN = (_CONFIG.get("cliproxyapi_api_token", "") or "").strip()
CLIPROXYAPI_DELETE_PATH = (_CONFIG.get("cliproxyapi_delete_path", "/v0/management/auth-files/{filename}") or "").strip()
CLIPROXYAPI_DELETE_METHOD = (_CONFIG.get("cliproxyapi_delete_method", "DELETE") or "DELETE").strip().upper()
SUB2API_URL = _CONFIG.get("sub2api_url", "").rstrip("/")
SUB2API_TOKEN = _CONFIG.get("sub2api_token", "")
SUB2API_PLATFORM = _CONFIG.get("sub2api_platform", "openai")
SUB2API_TYPE = _CONFIG.get("sub2api_type", "refresh_token")
SUB2API_IMPORT_PATH = _CONFIG.get("sub2api_import_path", "/api/v1/admin/accounts/data")
SUB2API_AUTH_MODE = (_CONFIG.get("sub2api_auth_mode", "bearer") or "bearer").strip().lower()
SUB2API_COOKIE = _CONFIG.get("sub2api_cookie", "")
SUB2API_API_KEY = _CONFIG.get("sub2api_api_key", "")
SUB2API_SKIP_DEFAULT_GROUP_BIND = as_bool(_CONFIG.get("sub2api_skip_default_group_bind", True))
SUB2API_ACCOUNT_TYPE = _CONFIG.get("sub2api_account_type", "oauth")
SUB2API_ACCOUNT_CONCURRENCY = int(_CONFIG.get("sub2api_account_concurrency", 10))
SUB2API_ACCOUNT_PRIORITY = int(_CONFIG.get("sub2api_account_priority", 1))
SUB2API_ACCOUNT_RATE_MULTIPLIER = float(_CONFIG.get("sub2api_account_rate_multiplier", 1))
SUB2API_ACCOUNT_AUTO_PAUSE_ON_EXPIRED = as_bool(_CONFIG.get("sub2api_account_auto_pause_on_expired", True))
SUB2API_TEMP_UNSCHEDULABLE_ENABLED = as_bool(_CONFIG.get("sub2api_temp_unschedulable_enabled", False))
_sub2api_temp_unschedulable_rules = _CONFIG.get("sub2api_temp_unschedulable_rules", []) or []
SUB2API_TEMP_UNSCHEDULABLE_RULES = _sub2api_temp_unschedulable_rules if isinstance(_sub2api_temp_unschedulable_rules, list) else []
SUB2API_GROUP_IDS = _CONFIG.get("sub2api_group_ids", []) or []
SUB2API_MODEL_MAPPING = _CONFIG.get("sub2api_model_mapping", {}) or {}
POST_ACCOUNT_WAIT_MIN_SECONDS = max(0.0, float(_CONFIG.get("post_account_wait_min_seconds", 20.0)))
POST_ACCOUNT_WAIT_MAX_SECONDS = max(POST_ACCOUNT_WAIT_MIN_SECONDS, float(_CONFIG.get("post_account_wait_max_seconds", 60.0)))
MAINTAIN_REGISTER_RETRY_LIMIT = max(0, int(_CONFIG.get("maintain_register_retry_limit", 0) or 0))
TOKEN_CHECK_URL = (_CONFIG.get("token_check_url", "https://chatgpt.com/backend-api/wham/usage") or "https://chatgpt.com/backend-api/wham/usage").strip()
TOKEN_CHECK_TIMEOUT = max(1.0, float(_CONFIG.get("token_check_timeout", 12) or 12))
TOKEN_CHECK_SLEEP = max(0.0, float(_CONFIG.get("token_check_sleep", 0.2) or 0.2))
TOKEN_CHECK_INPUT_FILE = _CONFIG.get("token_check_input_file", "codex_tokens/local/accounts.json") or "codex_tokens/local/accounts.json"
TOKEN_CHECK_REPORT_FILE = _CONFIG.get("token_check_report_file", "codex_tokens/token_check_report.json") or "codex_tokens/token_check_report.json"
MAINTAIN_ENABLED = as_bool(_CONFIG.get("maintain_enabled", True))
MAINTAIN_CHECK_INTERVAL_SECONDS = max(10, int(_CONFIG.get("maintain_check_interval_seconds", 1800) or 1800))

if not UPLOAD_TARGETS:
    # 兼容旧配置：未配置 upload_targets 时按现有服务配置自动启用
    if CLIPROXYAPI_API_URL and CLIPROXYAPI_API_TOKEN:
        UPLOAD_TARGETS.append("cliproxyapi")
    if SUB2API_URL and (SUB2API_TOKEN or SUB2API_COOKIE or SUB2API_API_KEY):
        UPLOAD_TARGETS.append("sub2api")

if not CLOUDFLARE_JWT_TOKEN:
    print("⚠️ 警告: 未设置 cloudflare_jwt_token，Cloudflare 模式将无法拉取邮件")

# 全局线程锁
_print_lock = threading.Lock()
_file_lock = threading.Lock()
_batch_progress_lock = threading.Lock()
_batch_target_reached_event = threading.Event()
_batch_target_success = 0
_batch_success_completed = 0
DEFAULT_UA = "codex_cli_rs/universal (Windows)"


def _is_key_log_message(message: str):
    msg = str(message or "")
    key_prefixes = (
        "[FAIL]", "[OK]", "[Post]", "[Batch]", "[Info]", "[Cloudflare]",
        "[CliProxyAPI]", "[Sub2API]", "[OAuth] 开始获取 Codex Token", "[OAuth] Token 已保存",
        "[OAuth] Codex Token 获取成功", "[OAuth] token 交换失败", "[OAuth] OAuth 获取失败",
    )
    return msg.startswith("第 ") or msg.startswith(key_prefixes)


def _should_emit_log(message: str):
    if not IS_PROD_LOG:
        return True
    return _is_key_log_message(message)


def _global_print(message: str):
    if _should_emit_log(message):
        with _print_lock:
            print(message)


def _format_traceback():
    try:
        return traceback.format_exc()
    except Exception:
        return ""


def _safe_json_response(resp, fallback: dict | None = None):
    try:
        return resp.json()
    except Exception:
        data = dict(fallback or {})
        txt = str(getattr(resp, "text", "") or "")
        if txt:
            data.setdefault("text", txt[:500])
        data.setdefault("status", getattr(resp, "status_code", None))
        data.setdefault("final_url", str(getattr(resp, "url", "") or ""))
        return data


def _reset_batch_success_target(target_success: int):
    """重置批次成功目标计数。"""
    global _batch_target_success, _batch_success_completed
    with _batch_progress_lock:
        _batch_target_success = max(0, int(target_success or 0))
        _batch_success_completed = 0
        _batch_target_reached_event.clear()


def _mark_batch_success():
    """标记一次成功注册；返回 (success_completed, target, just_reached)。"""
    global _batch_success_completed
    with _batch_progress_lock:
        _batch_success_completed += 1
        completed = _batch_success_completed
        target = _batch_target_success
        just_reached = False
        if target > 0 and completed >= target and not _batch_target_reached_event.is_set():
            _batch_target_reached_event.set()
            just_reached = True
    return completed, target, just_reached


def _base_dir():
    return _BASE_DIR


def _abs_path(path: str):
    return path if os.path.isabs(path) else os.path.join(_base_dir(), path)


def _tokens_root():
    root = _abs_path(TOKEN_BASE_DIR)
    os.makedirs(root, exist_ok=True)
    return root


def _normalize_token_artifact_path(path_value: str, default_filename: str):
    """强制将注册流程生成文件约束到 TOKEN_BASE_DIR 内。"""
    root = Path(_tokens_root()).resolve()
    raw = (path_value or default_filename or "").strip() or default_filename
    raw_norm = raw.replace("\\", "/")
    root_name = Path(TOKEN_BASE_DIR).name

    # 兼容配置写成 codex_tokens/xxx，避免变成 codex_tokens/codex_tokens/xxx
    if raw_norm == root_name:
        raw = default_filename
    elif raw_norm.startswith(f"{root_name}/"):
        raw = raw_norm[len(root_name) + 1:]
    elif raw_norm.startswith(f"./{root_name}/"):
        raw = raw_norm[len(root_name) + 3:]

    if os.path.isabs(raw):
        raw_path = Path(raw).resolve()
        try:
            common = os.path.commonpath([str(root), str(raw_path)])
        except ValueError:
            common = ""

        if common == str(root):
            # 允许使用位于 TOKEN_BASE_DIR 内的绝对路径，避免把 local/accounts.json
            # 错误降级成 accounts.json，导致巡检清理时删不到本地账号。
            candidate = raw_path
        else:
            # 对于 TOKEN_BASE_DIR 之外的绝对路径，仍然降级为文件名，避免越界写入。
            candidate = root / Path(raw).name
    else:
        candidate = root / raw

    candidate = candidate.resolve()
    try:
        common = os.path.commonpath([str(root), str(candidate)])
    except ValueError:
        common = ""
    if common != str(root):
        candidate = (root / Path(raw).name).resolve()

    candidate.parent.mkdir(parents=True, exist_ok=True)
    return str(candidate)


ARTIFACT_OUTPUT_FILE = _normalize_token_artifact_path(DEFAULT_OUTPUT_FILE, "registered_accounts.txt")
ARTIFACT_ACCOUNTS_DETAIL_FILE = _normalize_token_artifact_path(ACCOUNTS_DETAIL_FILE, "registered_accounts_details.jsonl")
ARTIFACT_LOCAL_ACCOUNTS_FILE = _normalize_token_artifact_path(LOCAL_ACCOUNTS_FILE, "local/accounts.json")


def _prepare_artifact_dirs():
    """启动时预创建产物目录，保证注册前目录可用。"""
    _tokens_root()
    for p in (
        ARTIFACT_OUTPUT_FILE,
        ARTIFACT_ACCOUNTS_DETAIL_FILE,
        ARTIFACT_LOCAL_ACCOUNTS_FILE,
    ):
        Path(p).parent.mkdir(parents=True, exist_ok=True)


def _service_enabled(service_name: str):
    return service_name.lower() in set(UPLOAD_TARGETS)


def _service_token_dir(service_name: str):
    service_key = service_name.lower()
    sub_dir = SERVICE_TOKEN_DIRS.get(service_key, service_key) or service_key
    full_dir = os.path.join(_tokens_root(), sub_dir)
    os.makedirs(full_dir, exist_ok=True)
    return full_dir


def _service_token_filename(email: str):
    """统一服务侧 JSON 文件名：保留邮箱原样（包含 @）。"""
    raw = str(email or "").strip()
    safe = re.sub(r"[^a-zA-Z0-9.@_-]", "_", raw)
    if not safe:
        safe = uuid.uuid4().hex
    return f"{safe}.json"


def _safe_text_response(resp, limit: int = 1000):
    try:
        txt = str(getattr(resp, "text", "") or "")
    except Exception:
        txt = ""
    return txt[:limit]


def _write_json(filepath: str, data: dict):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _append_account_detail(record: dict):
    detail_path = ARTIFACT_ACCOUNTS_DETAIL_FILE
    detail_dir = os.path.dirname(detail_path)
    if detail_dir:
        os.makedirs(detail_dir, exist_ok=True)
    with _file_lock:
        with open(detail_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _upsert_local_accounts_summary(token_data: dict):
    """维护 local/accounts.json：按 email 去重更新，作为可重建服务文件的统一数据源。"""
    email = str(token_data.get("email") or "").strip()
    if not email:
        return None

    account_meta = token_data.get("account") or {}
    entry = {
        "email": email,
        "chatgpt_password": account_meta.get("chatgpt_password", ""),
        "mailbox_password": account_meta.get("mailbox_password", ""),
        "name": account_meta.get("name", ""),
        "birthdate": account_meta.get("birthdate", ""),
        "access_token": token_data.get("access_token", ""),
        "refresh_token": token_data.get("refresh_token", ""),
        "id_token": token_data.get("id_token", ""),
        "account_id": token_data.get("account_id", ""),
        "expired": token_data.get("expired", ""),
        "created_at": token_data.get("created_at", ""),
        "last_refresh": token_data.get("last_refresh", ""),
        "source": token_data.get("source", "chatgpt_register"),
        "type": token_data.get("type", "codex"),
    }

    path = ARTIFACT_LOCAL_ACCOUNTS_FILE
    with _file_lock:
        base = {"version": 1, "updated_at": "", "accounts": []}
        data = base
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                data = base

        accounts = data.get("accounts")
        if not isinstance(accounts, list):
            accounts = []

        replaced = False
        for idx, item in enumerate(accounts):
            if isinstance(item, dict) and str(item.get("email", "")).strip().lower() == email.lower():
                accounts[idx] = entry
                replaced = True
                break
        if not replaced:
            accounts.append(entry)

        data["version"] = 1
        data["updated_at"] = datetime.now(tz=timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S+08:00")
        data["accounts"] = accounts
        _write_json(path, data)

    return path


# Chrome 指纹配置: impersonate 与 sec-ch-ua 必须匹配真实浏览器
_CHROME_PROFILES = [
    {
        "major": 131, "impersonate": "chrome131",
        "build": 6778, "patch_range": (69, 205),
        "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    },
    {
        "major": 133, "impersonate": "chrome133a",
        "build": 6943, "patch_range": (33, 153),
        "sec_ch_ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
    },
    {
        "major": 136, "impersonate": "chrome136",
        "build": 7103, "patch_range": (48, 175),
        "sec_ch_ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    },
    {
        "major": 142, "impersonate": "chrome142",
        "build": 7540, "patch_range": (30, 150),
        "sec_ch_ua": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
    },
]


def _random_chrome_version():
    profile = random.choice(_CHROME_PROFILES)
    major = profile["major"]
    build = profile["build"]
    patch = random.randint(*profile["patch_range"])
    full_ver = f"{major}.0.{build}.{patch}"
    ua = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{full_ver} Safari/537.36"
    return profile["impersonate"], major, full_ver, ua, profile["sec_ch_ua"]


def _random_delay(low=0.3, high=1.0):
    time.sleep(random.uniform(low, high))


def _make_trace_headers():
    trace_id = random.randint(10**17, 10**18 - 1)
    parent_id = random.randint(10**17, 10**18 - 1)
    tp = f"00-{uuid.uuid4().hex}-{format(parent_id, '016x')}-01"
    return {
        "traceparent": tp, "tracestate": "dd=s:1;o:rum",
        "x-datadog-origin": "rum", "x-datadog-sampling-priority": "1",
        "x-datadog-trace-id": str(trace_id), "x-datadog-parent-id": str(parent_id),
    }


def _generate_pkce():
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def _extract_code_from_url(url: str):
    if not url or "code=" not in url:
        return None
    try:
        return parse_qs(urlparse(url).query).get("code", [None])[0]
    except Exception:
        return None


def _decode_jwt_payload(token: str):
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return {}


def _build_sub2api_payload(email: str, token_data: dict):
    refresh_token = token_data.get("refresh_token", "")
    access_token = token_data.get("access_token", "")
    id_token = token_data.get("id_token", "")
    account_id = token_data.get("account_id", "")
    expires_at = token_data.get("expired", "")

    credentials = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "email": email,
        "client_id": OAUTH_CLIENT_ID,
        "chatgpt_account_id": account_id,
        "model_mapping": SUB2API_MODEL_MAPPING,
        "temp_unschedulable_enabled": SUB2API_TEMP_UNSCHEDULABLE_ENABLED,
        "temp_unschedulable_rules": SUB2API_TEMP_UNSCHEDULABLE_RULES,
    }
    if expires_at:
        credentials["expires_at"] = expires_at

    account_payload = {
        "name": email,
        "platform": SUB2API_PLATFORM,
        "group_ids": SUB2API_GROUP_IDS,
        "type": SUB2API_ACCOUNT_TYPE,
        "credentials": credentials,
        "extra": {
            "email": email,
            "openai_oauth_responses_websockets_v2_enabled": True,
            "openai_oauth_responses_websockets_v2_mode": "passthrough",
        },
        "concurrency": SUB2API_ACCOUNT_CONCURRENCY,
        "priority": SUB2API_ACCOUNT_PRIORITY,
        "rate_multiplier": SUB2API_ACCOUNT_RATE_MULTIPLIER,
        "auto_pause_on_expired": SUB2API_ACCOUNT_AUTO_PAUSE_ON_EXPIRED,
    }
    return {
        "data": {
            "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "proxies": [],
            "accounts": [account_payload],
        },
        "skip_default_group_bind": SUB2API_SKIP_DEFAULT_GROUP_BIND,
    }


def _save_codex_tokens(email: str, tokens: dict, account_info: dict = None):
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    id_token = tokens.get("id_token", "")

    if not access_token:
        return

    payload = _decode_jwt_payload(access_token)
    auth_info = payload.get("https://api.openai.com/auth", {})
    account_id = auth_info.get("chatgpt_account_id", "") or tokens.get("account_id", "")

    exp_timestamp = payload.get("exp")
    expired_str = ""
    if isinstance(exp_timestamp, int) and exp_timestamp > 0:
        exp_dt = datetime.fromtimestamp(exp_timestamp, tz=timezone(timedelta(hours=8)))
        expired_str = exp_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    if not expired_str:
        expired_str = str(tokens.get("expired") or "")

    now = datetime.now(tz=timezone(timedelta(hours=8)))
    token_data = {
        "type": "codex",
        "source": "chatgpt_register",
        "email": email,
        "expired": expired_str,
        "id_token": id_token,
        "account_id": account_id,
        "access_token": access_token,
        "last_refresh": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "refresh_token": refresh_token,
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "account": account_info or {},
    }

    saved_files = {}
    # 仅维护 local/accounts.json（不再写 local/邮箱.json）
    accounts_summary_path = _upsert_local_accounts_summary(token_data)
    if accounts_summary_path:
        saved_files["local_accounts"] = accounts_summary_path

    # 为 CliProxyAPI 上传准备独立目录文件
    if _service_enabled("cliproxyapi"):
        cliproxyapi_dir = _service_token_dir("cliproxyapi")
        cliproxyapi_path = os.path.join(cliproxyapi_dir, _service_token_filename(email))
        with _file_lock:
            _write_json(cliproxyapi_path, token_data)
        saved_files["cliproxyapi"] = cliproxyapi_path

        if CLIPROXYAPI_API_URL and CLIPROXYAPI_API_TOKEN:
            _upload_token_to_cliproxyapi(cliproxyapi_path)
        else:
            with _print_lock:
                print("[CliProxyAPI] 已启用 cliproxyapi 上传目标，但未配置 cliproxyapi_api_base_url / cliproxyapi_api_token")

    # 为 sub2api 保存请求载荷并上传
    if _service_enabled("sub2api"):
        sub2api_payload = _build_sub2api_payload(email, token_data)
        s2a_dir = _service_token_dir("sub2api")
        s2a_path = os.path.join(s2a_dir, _service_token_filename(email))
        with _file_lock:
            _write_json(s2a_path, sub2api_payload)
        saved_files["sub2api"] = s2a_path

        if SUB2API_URL and (SUB2API_TOKEN or SUB2API_COOKIE or SUB2API_API_KEY):
            _upload_token_to_sub2api(email, sub2api_payload)
        else:
            with _print_lock:
                print("[Sub2API] 已启用 sub2api 上传目标，但未配置 sub2api_url 与鉴权")

    return token_data, saved_files


def _upload_token_to_cliproxyapi(filepath: str):
    """上传 Token JSON 文件到 CliProxyAPI 管理平台"""
    mp = None
    try:
        from curl_cffi import CurlMime

        filename = os.path.basename(filepath)
        mp = CurlMime()
        mp.addpart(
            name="file",
            content_type="application/json",
            filename=filename,
            local_path=filepath,
        )

        session = curl_requests.Session()

        resp = session.post(
            CLIPROXYAPI_API_URL,
            multipart=mp,
            headers={"Authorization": f"Bearer {CLIPROXYAPI_API_TOKEN}"},
            verify=False,
            timeout=30,
        )

        if resp.status_code == 200:
            with _print_lock:
                print("[CliProxyAPI] Token JSON 已上传到管理平台")
        else:
            with _print_lock:
                print(f"[CliProxyAPI] 上传失败: {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        with _print_lock:
            print(f"[CliProxyAPI] 上传异常: {e}")
    finally:
        if mp:
            mp.close()


def _upload_token_to_sub2api(email: str, payload: dict):
    """将账号和 token 导入到 sub2api 平台（/api/v1/admin/accounts/data）"""
    try:
        headers = {"Content-Type": "application/json"}
        if SUB2API_AUTH_MODE == "cookie" and SUB2API_COOKIE:
            headers["Cookie"] = SUB2API_COOKIE
        elif SUB2API_AUTH_MODE in ("x-api-key", "apikey", "api_key") and SUB2API_API_KEY:
            headers["x-api-key"] = SUB2API_API_KEY
        elif SUB2API_TOKEN:
            headers["Authorization"] = f"Bearer {SUB2API_TOKEN}"
        else:
            with _print_lock:
                print("[Sub2API] 未配置鉴权信息：请在 config.py 配置 sub2api_token / sub2api_cookie / sub2api_api_key")
            return

        endpoint = f"{SUB2API_URL}{SUB2API_IMPORT_PATH}"
        
        session = curl_requests.Session()

        resp = session.post(
            endpoint,
            json=payload,
            headers=headers,
            verify=False,
            timeout=30
        )
        
        if resp.status_code in (200, 201, 204):
            with _print_lock:
                print(f"[Sub2API] {email} 成功导入到 Sub2API!")

            # 导入成功后，按邮箱查账号 ID，再执行一次分组更新
            if SUB2API_GROUP_IDS:
                account_id = _sub2api_find_account_id_by_email(session, headers, email)
                if account_id is None:
                    with _print_lock:
                        print(f"[Sub2API] 导入成功，但未通过邮箱定位账号ID: {email}")
                else:
                    updated = _sub2api_update_account_groups(session, headers, account_id, SUB2API_GROUP_IDS)
                    if updated:
                        with _print_lock:
                            print(f"[Sub2API] 已更新账号分组 account_id={account_id}, group_ids={SUB2API_GROUP_IDS}")
                    else:
                        with _print_lock:
                            print(f"[Sub2API] 账号分组更新失败 account_id={account_id}")
        else:
            with _print_lock:
                print(f"[Sub2API] 上传失败: {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        with _print_lock:
            print(f"[Sub2API] 上传异常: {e}")


def _build_sub2api_auth_headers():
    headers = {"Content-Type": "application/json"}
    if SUB2API_AUTH_MODE == "cookie" and SUB2API_COOKIE:
        headers["Cookie"] = SUB2API_COOKIE
    elif SUB2API_AUTH_MODE in ("x-api-key", "apikey", "api_key") and SUB2API_API_KEY:
        headers["x-api-key"] = SUB2API_API_KEY
    elif SUB2API_TOKEN:
        headers["Authorization"] = f"Bearer {SUB2API_TOKEN}"
    return headers


def _delete_remote_sub2api_account(email: str):
    if not SUB2API_URL:
        return {"ok": False, "skipped": True, "reason": "sub2api_url_not_configured"}

    headers = _build_sub2api_auth_headers()
    if len(headers) <= 1:
        return {"ok": False, "skipped": True, "reason": "sub2api_auth_not_configured"}

    try:
        session = curl_requests.Session()
        account_id = _sub2api_find_account_id_by_email(session, headers, email)
        if account_id is None:
            return {"ok": False, "skipped": True, "reason": "account_not_found"}

        endpoint = f"{SUB2API_URL}/api/v1/admin/accounts/{account_id}"
        resp = session.delete(endpoint, headers=headers, verify=False, timeout=30)
        ok = resp.status_code in (200, 202, 204)
        return {
            "ok": ok,
            "status": resp.status_code,
            "account_id": account_id,
            "reason": "deleted" if ok else _safe_text_response(resp, 300),
        }
    except Exception as e:
        return {"ok": False, "reason": f"exception:{type(e).__name__}:{e}"}


def _delete_remote_cliproxyapi_file(filename: str):
    if not CLIPROXYAPI_API_BASE_URL:
        return {"ok": False, "skipped": True, "reason": "cliproxyapi_api_base_url_not_configured"}
    if not CLIPROXYAPI_API_TOKEN:
        return {"ok": False, "skipped": True, "reason": "cliproxyapi_api_token_not_configured"}
    if not CLIPROXYAPI_DELETE_PATH:
        return {"ok": False, "skipped": True, "reason": "cliproxyapi_delete_path_not_configured"}

    try:
        path = CLIPROXYAPI_DELETE_PATH.format(filename=quote(filename, safe=""))
    except Exception:
        path = CLIPROXYAPI_DELETE_PATH

    if not path.startswith("/"):
        path = f"/{path}"

    endpoint = f"{CLIPROXYAPI_API_BASE_URL.rstrip('/')}{path}"
    try:
        session = curl_requests.Session()
        resp = session.request(
            method=CLIPROXYAPI_DELETE_METHOD,
            url=endpoint,
            headers={"Authorization": f"Bearer {CLIPROXYAPI_API_TOKEN}"},
            verify=False,
            timeout=30,
        )
        ok = resp.status_code in (200, 202, 204)
        return {
            "ok": ok,
            "status": resp.status_code,
            "reason": "deleted" if ok else _safe_text_response(resp, 300),
            "endpoint": endpoint,
        }
    except Exception as e:
        return {"ok": False, "reason": f"exception:{type(e).__name__}:{e}", "endpoint": endpoint}


def _sub2api_find_account_id_by_email(session, headers: dict, email: str):
    """通过 /admin/accounts 按邮箱检索账号并返回 ID。"""
    if not SUB2API_URL or not email:
        return None

    endpoint = f"{SUB2API_URL}/api/v1/admin/accounts"
    # 优先使用 search=email；兼容部分后端只认 page/page_size
    params_candidates = [
        {"page": 1, "page_size": 20, "search": email, "lite": "true"},
        {"page": 1, "page_size": 50, "search": email},
        {"page": 1, "page_size": 100},
    ]

    for params in params_candidates:
        try:
            resp = session.get(
                endpoint,
                params=params,
                headers=headers,
                verify=False,
                timeout=30,
            )
        except Exception:
            continue

        if resp.status_code != 200:
            continue

        try:
            data = resp.json()
        except Exception:
            continue

        account_id = _extract_account_id_from_list_payload(data, email)
        if account_id is not None:
            return account_id

    return None


def _extract_account_id_from_list_payload(data, email: str):
    """兼容不同分页结构，从列表响应中按邮箱匹配账号 ID。"""
    if not isinstance(data, dict):
        return None

    # 常见结构：{ items: [...] } / { data: [...] } / { data: { items: [...] } }
    possible_lists = []
    if isinstance(data.get("items"), list):
        possible_lists.append(data.get("items"))
    if isinstance(data.get("data"), list):
        possible_lists.append(data.get("data"))
    if isinstance(data.get("results"), list):
        possible_lists.append(data.get("results"))

    data_obj = data.get("data")
    if isinstance(data_obj, dict):
        if isinstance(data_obj.get("items"), list):
            possible_lists.append(data_obj.get("items"))
        if isinstance(data_obj.get("results"), list):
            possible_lists.append(data_obj.get("results"))
        if isinstance(data_obj.get("accounts"), list):
            possible_lists.append(data_obj.get("accounts"))

    target_email = str(email or "").strip().lower()
    if not target_email:
        return None

    for arr in possible_lists:
        for item in arr:
            if not isinstance(item, dict):
                continue
            item_email = str(item.get("name") or item.get("email") or "").strip().lower()
            if item_email != target_email:
                continue
            account_id = item.get("id")
            if isinstance(account_id, int):
                return account_id
            # 兼容字符串数字
            if isinstance(account_id, str) and account_id.isdigit():
                return int(account_id)

    return None


def _sub2api_update_account_groups(session, headers: dict, account_id: int, group_ids: list):
    """调用 PUT /admin/accounts/{id} 更新 group_ids。"""
    if not SUB2API_URL or not account_id:
        return False

    endpoint = f"{SUB2API_URL}/api/v1/admin/accounts/{account_id}"
    try:
        resp = session.put(
            endpoint,
            json={"group_ids": group_ids, "proxy_id": 1},
            headers=headers,
            verify=False,
            timeout=30,
        )
    except Exception:
        return False

    return resp.status_code in (200, 201, 204)


def _token_check_input_path(path_value: str = ""):
    raw = str(path_value or TOKEN_CHECK_INPUT_FILE or ARTIFACT_LOCAL_ACCOUNTS_FILE).strip()
    return _normalize_token_artifact_path(raw, "local/accounts.json")


def _token_check_report_path(path_value: str = ""):
    raw = str(path_value or TOKEN_CHECK_REPORT_FILE or "codex_tokens/token_check_report.json").strip()
    return _normalize_token_artifact_path(raw, "token_check_report.json")


def _load_local_accounts_for_check(path_value: str = ""):
    input_path = _token_check_input_path(path_value)
    if not os.path.exists(input_path):
        return input_path, []

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return input_path, []

    accounts = data.get("accounts", []) if isinstance(data, dict) else []
    if not isinstance(accounts, list):
        accounts = []
    return input_path, accounts


def _load_valid_local_account_entries(path_value: str = ""):
    input_path, raw_accounts = _load_local_accounts_for_check(path_value)
    valid_accounts = []
    for idx, entry in enumerate(raw_accounts, start=1):
        item = _build_check_account_record(entry, idx)
        if item:
            valid_accounts.append(item)
    return input_path, valid_accounts


def _count_local_accounts(path_value: str = ""):
    input_path, valid_accounts = _load_valid_local_account_entries(path_value)
    return {
        "path": input_path,
        "count": len(valid_accounts),
        "accounts": valid_accounts,
    }


def _build_check_account_record(entry: dict, index: int):
    if not isinstance(entry, dict):
        return None
    email = str(entry.get("email") or "").strip()
    access_token = str(entry.get("access_token") or "").strip()
    account_id = str(entry.get("account_id") or "").strip()
    if not email or not access_token or not account_id:
        return None
    return {
        "index": index,
        "email": email,
        "account_id": account_id,
        "access_token": access_token,
        "entry": entry,
    }


def _is_deactivated_401(status_code: int, response_text: str, response_json=None):
    if int(status_code or 0) != 401:
        return False

    text = str(response_text or "").lower()
    keywords = ("deactivated", "invalidated")
    if any(k in text for k in keywords):
        return True

    if isinstance(response_json, dict):
        payload_text = json.dumps(response_json, ensure_ascii=False).lower()
        if any(k in payload_text for k in keywords):
            return True

    return False


def _check_one_local_account(account: dict, proxy_url: str = "", url: str = TOKEN_CHECK_URL, timeout: float = TOKEN_CHECK_TIMEOUT):
    session = curl_requests.Session()
    if proxy_url:
        session.proxies = {"http": proxy_url, "https": proxy_url}

    headers = {
        "accept": "application/json",
        "user-agent": DEFAULT_UA,
        "authorization": f"Bearer {account['access_token']}",
        "chatgpt-account-id": account["account_id"],
    }

    result = {
        "status": 0,
        "ok": False,
        "response_text": "",
        "response_json": None,
        "reason": "",
        "proxy": proxy_url,
        "should_delete": False,
    }

    try:
        resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        result["status"] = int(resp.status_code or 0)
        result["response_text"] = _safe_text_response(resp, 1000)
        try:
            result["response_json"] = resp.json()
        except Exception:
            result["response_json"] = None
        result["ok"] = result["status"] == 200
        result["should_delete"] = _is_deactivated_401(result["status"], result["response_text"], result["response_json"])
        result["reason"] = "deactivated_401" if result["should_delete"] else ("ok" if result["ok"] else f"http_{result['status']}")
        return result
    except Exception as e:
        result["reason"] = f"request_error:{type(e).__name__}:{e}"
        return result


def _remove_local_account_from_accounts_file(email: str, account_id: str, input_path: str = ""):
    path = _token_check_input_path(input_path)
    if not os.path.exists(path):
        return {"ok": False, "reason": "accounts_file_not_found", "path": path}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"ok": False, "reason": f"invalid_accounts_json:{e}", "path": path}

    if not isinstance(data, dict):
        data = {"version": 1, "updated_at": "", "accounts": []}

    accounts = data.get("accounts", [])
    if not isinstance(accounts, list):
        accounts = []

    before = len(accounts)
    kept = []
    removed = 0
    for item in accounts:
        item_email = str((item or {}).get("email") or "").strip().lower() if isinstance(item, dict) else ""
        item_account_id = str((item or {}).get("account_id") or "").strip() if isinstance(item, dict) else ""
        if item_email == str(email or "").strip().lower() or (account_id and item_account_id == account_id):
            removed += 1
            continue
        kept.append(item)

    data["accounts"] = kept
    data["updated_at"] = datetime.now(tz=timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    _write_json(path, data)
    return {"ok": True, "removed": removed, "before": before, "after": len(kept), "path": path}


def _delete_local_service_files(email: str):
    filename = _service_token_filename(email)
    deleted = []
    missing = []
    for service_name in ("cliproxyapi", "sub2api"):
        path = os.path.join(_service_token_dir(service_name), filename)
        if os.path.exists(path):
            try:
                os.remove(path)
                deleted.append(path)
            except Exception:
                missing.append(path)
        else:
            missing.append(path)
    return {"ok": True, "deleted": deleted, "missing": missing, "filename": filename}


def run_token_check_cleanup(input_path: str = "", report_path: str = ""):
    _prepare_artifact_dirs()
    check_input_path, raw_accounts = _load_local_accounts_for_check(input_path)
    report_output_path = _token_check_report_path(report_path)

    if not raw_accounts:
        result = {
            "ok": False,
            "reason": "no_accounts_found",
            "input_path": check_input_path,
            "report_path": report_output_path,
            "summary": {"total": 0, "ok": 0, "deactivated_401": 0, "kept": 0, "deleted": 0, "request_error": 0},
            "items": [],
        }
        _write_json(report_output_path, result)
        return result

    accounts = []
    for idx, entry in enumerate(raw_accounts, start=1):
        item = _build_check_account_record(entry, idx)
        if item:
            accounts.append(item)

    proxies = [str(p).strip() for p in (DEFAULT_PROXY_POOL or []) if str(p).strip()]
    proxy_cycle = itertools.cycle(proxies) if proxies else None

    items = []
    summary = {
        "total": len(accounts),
        "ok": 0,
        "deactivated_401": 0,
        "kept": 0,
        "deleted": 0,
        "request_error": 0,
    }

    print(f"[TokenCheck] 开始巡检，共 {len(accounts)} 个账号")
    print(f"[TokenCheck] 数据源: {check_input_path}")
    print(f"[TokenCheck] 代理池: {proxies if proxies else '无(直连)'}")

    for idx, account in enumerate(accounts, start=1):
        proxy_url = next(proxy_cycle) if proxy_cycle else ""
        check_result = _check_one_local_account(account, proxy_url=proxy_url)

        row = {
            "index": idx,
            "email": account["email"],
            "account_id": account["account_id"],
            "status": check_result["status"],
            "proxy": proxy_url,
            "reason": check_result["reason"],
            "should_delete": check_result["should_delete"],
            "response_excerpt": (check_result.get("response_text") or "")[:300],
            "local_cleanup": None,
            "sub2api_delete": None,
            "cliproxyapi_delete": None,
            "local_files_delete": None,
        }

        if check_result["ok"]:
            summary["ok"] += 1
            summary["kept"] += 1
        elif check_result["should_delete"]:
            summary["deactivated_401"] += 1

            row["sub2api_delete"] = _delete_remote_sub2api_account(account["email"])
            row["cliproxyapi_delete"] = _delete_remote_cliproxyapi_file(_service_token_filename(account["email"]))
            row["local_files_delete"] = _delete_local_service_files(account["email"])
            row["local_cleanup"] = _remove_local_account_from_accounts_file(account["email"], account["account_id"], check_input_path)
            summary["deleted"] += 1
        else:
            summary["kept"] += 1
            if check_result["status"] == 0:
                summary["request_error"] += 1

        items.append(row)
        print(
            f"[TokenCheck] [{idx}/{len(accounts)}] email={account['email']} status={check_result['status']} "
            f"delete={'yes' if check_result['should_delete'] else 'no'} proxy={proxy_url or '直连'}"
        )

        if TOKEN_CHECK_SLEEP > 0:
            time.sleep(TOKEN_CHECK_SLEEP)

    result = {
        "ok": True,
        "input_path": check_input_path,
        "report_path": report_output_path,
        "summary": summary,
        "items": items,
    }
    _write_json(report_output_path, result)
    print("[TokenCheck] 巡检完成")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[TokenCheck] 报告已写入: {report_output_path}")
    return result


def run_maintain_once(target_total: int, max_workers: int, proxy_pool=None, check_input_path: str = "", report_path: str = ""):
    """执行一次保号周期：巡检 -> 删除失效 -> 补足到目标数量。"""
    _prepare_artifact_dirs()

    cycle_started_at = datetime.now().isoformat(timespec="seconds")
    cleanup_result = run_token_check_cleanup(input_path=check_input_path, report_path=report_path)
    local_state = _count_local_accounts(check_input_path)
    current_count = int(local_state["count"])
    target_total = max(0, int(target_total or 0))
    before_register_count = current_count
    deficit = max(0, target_total - current_count)

    register_attempts = []
    attempt_round = 0
    while deficit > 0:
        attempt_round += 1
        print(f"[Maintain] 当前本地有效账号 {current_count} 个，低于目标 {target_total}，开始第 {attempt_round} 次补注册，缺口 {deficit} 个")
        attempt_result = run_batch(
            total_accounts=deficit,
            output_file=ARTIFACT_OUTPUT_FILE,
            max_workers=max_workers,
            proxy_pool=proxy_pool,
        )
        register_attempts.append(attempt_result)

        local_state = _count_local_accounts(check_input_path)
        current_count = int(local_state["count"])
        deficit = max(0, target_total - current_count)
        if deficit <= 0:
            break

        if MAINTAIN_REGISTER_RETRY_LIMIT > 0 and attempt_round >= MAINTAIN_REGISTER_RETRY_LIMIT:
            print(f"[Maintain] 已达到补注册重试上限 {MAINTAIN_REGISTER_RETRY_LIMIT}，本轮停止")
            break

        wait_s = random.uniform(POST_ACCOUNT_WAIT_MIN_SECONDS, POST_ACCOUNT_WAIT_MAX_SECONDS) if POST_ACCOUNT_WAIT_MAX_SECONDS > 0 else 0
        print(f"[Maintain] 仍缺少 {deficit} 个账号，等待 {wait_s:.1f}s 后继续补注册")
        if wait_s > 0:
            time.sleep(wait_s)

    if not register_attempts:
        print(f"[Maintain] 当前本地有效账号 {current_count} 个，已达到目标 {target_total}，无需补注册")

    register_result = {
        "ok": all(item.get("ok") for item in register_attempts) if register_attempts else True,
        "attempts": register_attempts,
        "total": sum(int(item.get("total", 0) or 0) for item in register_attempts),
        "success": sum(int(item.get("success", 0) or 0) for item in register_attempts),
        "fail": sum(int(item.get("fail", 0) or 0) for item in register_attempts),
        "elapsed": sum(float(item.get("elapsed", 0) or 0) for item in register_attempts),
        "output_file": ARTIFACT_OUTPUT_FILE,
        "error": "" if not register_attempts else "; ".join([str(item.get("error") or "") for item in register_attempts if item.get("error")]),
    }

    final_state = _count_local_accounts(check_input_path)
    final_count = int(final_state["count"])
    ok = final_count >= target_total

    summary = {
        "ok": ok,
        "target_total": target_total,
        "before_register_count": before_register_count,
        "after_register_count": final_count,
        "registered_deficit": deficit,
        "cleanup": cleanup_result,
        "register": register_result,
        "started_at": cycle_started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "local_accounts_path": final_state["path"],
    }
    print("[Maintain] 单次保号周期完成")
    print(json.dumps({
        "target_total": target_total,
        "before_register_count": before_register_count,
        "after_register_count": final_count,
        "registered_deficit": deficit,
        "register_success": register_result.get("success", 0),
        "register_fail": register_result.get("fail", 0),
    }, ensure_ascii=False, indent=2))
    return summary


def run_maintain_loop(
    target_total: int,
    max_workers: int,
    proxy_pool=None,
    interval_seconds: int = MAINTAIN_CHECK_INTERVAL_SECONDS,
    maintain_use_case=None,
    check_input_path: str = "",
    report_path: str = "",
):
    """持续保号：周期巡检 + 自动补号。"""
    interval_seconds = max(10, int(interval_seconds or MAINTAIN_CHECK_INTERVAL_SECONDS))
    cycle_index = 0

    while True:
        cycle_index += 1
        print(f"\n[Maintain] ===== 第 {cycle_index} 轮保号开始 =====")

        state = load_run_state(_BASE_DIR)
        state.update({
            "status": "running",
            "message": f"maintain_cycle_{cycle_index}_started",
            "last_run_id": datetime.now().strftime("%Y%m%d%H%M%S"),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": "",
            "planned_total_accounts": int(target_total),
        })
        save_run_state(state, _BASE_DIR)

        try:
            if maintain_use_case is not None:
                result = maintain_use_case.execute(
                    target_total=target_total,
                    max_workers=max_workers,
                    proxy_pool=proxy_pool,
                    check_input_path=check_input_path,
                    report_path=report_path,
                )
            else:
                result = run_maintain_once(
                    target_total=target_total,
                    max_workers=max_workers,
                    proxy_pool=proxy_pool,
                    check_input_path=check_input_path,
                    report_path=report_path,
                )
            state = load_run_state(_BASE_DIR)
            state.update({
                "status": "done" if result.get("ok") else "error",
                "message": "maintain_cycle_finished" if result.get("ok") else "maintain_cycle_incomplete",
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "planned_total_accounts": int(target_total),
                "completed_accounts": int(result.get("after_register_count", 0) or 0),
                "success_count": int(result.get("after_register_count", 0) or 0),
                "fail_count": max(0, int(target_total) - int(result.get("after_register_count", 0) or 0)),
            })
            save_run_state(state, _BASE_DIR)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            with _print_lock:
                print(f"[Maintain] 保号周期异常: {e}")
                tb_text = _format_traceback()
                if not IS_PROD_LOG and tb_text and tb_text.strip() and tb_text.strip() != "NoneType: None":
                    print(tb_text.rstrip())

            state = load_run_state(_BASE_DIR)
            state.update({
                "status": "error",
                "message": f"maintain_cycle_exception: {e}",
                "finished_at": datetime.now().isoformat(timespec="seconds"),
            })
            save_run_state(state, _BASE_DIR)

        print(f"[Maintain] 本轮结束，{interval_seconds}s 后开始下一轮（Ctrl+C 可停止）")
        time.sleep(interval_seconds)


def _generate_password(length=14):
    lower = string.ascii_lowercase
    upper = string.ascii_uppercase
    digits = string.digits
    special = "!@#$%&*"
    pwd = [random.choice(lower), random.choice(upper),
           random.choice(digits), random.choice(special)]
    all_chars = lower + upper + digits + special
    pwd += [random.choice(all_chars) for _ in range(length - 4)]
    random.shuffle(pwd)
    return "".join(pwd)




def _random_name():
    first = random.choice([
        "James", "Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia",
        "Lucas", "Mia", "Mason", "Isabella", "Logan", "Charlotte", "Alexander",
        "Amelia", "Benjamin", "Harper", "William", "Evelyn", "Henry", "Abigail",
        "Sebastian", "Emily", "Jack", "Elizabeth",
    ])
    last = random.choice([
        "Smith", "Johnson", "Brown", "Davis", "Wilson", "Moore", "Taylor",
        "Clark", "Hall", "Young", "Anderson", "Thomas", "Jackson", "White",
        "Harris", "Martin", "Thompson", "Garcia", "Robinson", "Lewis",
        "Walker", "Allen", "King", "Wright", "Scott", "Green",
    ])
    return f"{first} {last}"


def _random_birthdate():
    y = random.randint(1985, 2002)
    m = random.randint(1, 12)
    d = random.randint(1, 28)
    return f"{y}-{m:02d}-{d:02d}"


class ChatGPTRegister:
    BASE = "https://chatgpt.com"
    AUTH = "https://auth.openai.com"

    def __init__(self, proxy: str = None, tag: str = ""):
        self.tag = tag  # 线程标识，用于日志
        self.device_id = str(uuid.uuid4())
        self.auth_session_logging_id = str(uuid.uuid4())
        self.impersonate, self.chrome_major, self.chrome_full, self.ua, self.sec_ch_ua = _random_chrome_version()

        self.session = curl_requests.Session(impersonate=self.impersonate)

        self.proxy = proxy
        if self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}

        self.session.headers.update({
            "User-Agent": self.ua,
            "Accept-Language": random.choice([
                "en-US,en;q=0.9", "en-US,en;q=0.9,zh-CN;q=0.8",
                "en,en-US;q=0.9", "en-US,en;q=0.8",
            ]),
            "sec-ch-ua": self.sec_ch_ua, "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"', "sec-ch-ua-arch": '"x86"',
            "sec-ch-ua-bitness": '"64"',
            "sec-ch-ua-full-version": f'"{self.chrome_full}"',
            "sec-ch-ua-platform-version": f'"{random.randint(10, 15)}.0.0"',
        })

        self.session.cookies.set("oai-did", self.device_id, domain="chatgpt.com")
        self._callback_url = None
        self.cf_service = CloudflareMailProvider(
            api_base=CLOUDFLARE_API_BASE,
            domain=CLOUDFLARE_DOMAIN,
            jwt_token=CLOUDFLARE_JWT_TOKEN,
            proxies={"http": self.proxy, "https": self.proxy} if self.proxy else None,
        )

    def _log(self, step, method, url, status, body=None):
        if IS_PROD_LOG:
            return
        lines = [
            f"\n{'='*60}",
            f"[Step] {step}",
            f"[{method}] {url}",
            f"[Status] {status}",
        ]
        if body:
            try:
                lines.append(f"[Response] {json.dumps(body, indent=2, ensure_ascii=False)[:1000]}")
            except Exception:
                lines.append(f"[Response] {str(body)[:1000]}")
        lines.append(f"{'='*60}")
        with _print_lock:
            print("\n".join(lines))

    def _print(self, msg):
        _global_print(msg)

    def _http_request(self, method: str, url: str, step: str = "", max_retries: int = 2, **kwargs):
        """统一请求入口：对网络层异常做有限重试，避免单次抖动中断流程。"""
        total_attempts = max(1, int(max_retries or 0) + 1)
        last_error = None

        for attempt in range(1, total_attempts + 1):
            try:
                return self.session.request(method=method, url=url, **kwargs)
            except Exception as e:
                last_error = e
                self._print(
                    f"[HTTP] {step or method} 请求异常 ({attempt}/{total_attempts}): {e}"
                )
                if attempt < total_attempts:
                    time.sleep(random.uniform(0.6, 1.5))

        raise Exception(f"{step or method} 请求失败: {last_error}")

    # ==================== Cloudflare 临时邮箱 ====================

    def create_temp_email(self):
        """创建 Cloudflare 域名邮箱，返回 (email, password, mail_token)

        兼容主流程字段：
        - password: Cloudflare 模式没有邮箱密码，返回 email 占位
        - mail_token: Cloudflare 模式直接使用 email 作为拉取邮件标识
        """
        if not self.cf_service:
            raise Exception("Cloudflare 邮件服务未初始化")

        email, placeholder = self.cf_service.create_email()
        return email, placeholder, email

    def _extract_verification_code(self, email_content: str):
        """从邮件内容提取 6 位验证码"""
        if not email_content:
            return None

        patterns = [
            r"Verification code:?\s*(\d{6})",
            r"code is\s*(\d{6})",
            r"代码为[:：]?\s*(\d{6})",
            r"验证码[:：]?\s*(\d{6})",
            r">\s*(\d{6})\s*<",
            r"(?<![#&])\b(\d{6})\b",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, email_content, re.IGNORECASE)
            for code in matches:
                if code == "177010":  # 已知误判
                    continue
                return code
        return None

    def wait_for_verification_email(self, mail_token: str, timeout: int = 120, initial_wait: float = 0):
        """等待并提取 OpenAI 验证码"""
        if not self.cf_service:
            self._print("[OTP-CF] Cloudflare 邮件服务未初始化")
            return None

        attempts = CLOUDFLARE_POLL_ATTEMPTS
        interval = CLOUDFLARE_POLL_INTERVAL
        self._print(f"[OTP-CF] 等待验证码邮件 (最多 {attempts} 次，每次间隔 {interval}s)...")

        initial_wait = max(0.0, float(initial_wait or 0))
        if initial_wait > 0:
            self._print(f"[OTP-CF] 首次拉取前等待 {initial_wait:.1f}s，确保验证码邮件已送达")
            time.sleep(initial_wait)

        for i in range(attempts):
            time.sleep(interval)
            content = self.cf_service.fetch_first_email(mail_token)
            if content:
                clean = re.sub(r"<[^>]+>", " ", str(content)).replace("=3D", "=").replace("=\n", "")
                code = self._extract_verification_code(clean)
                if code:
                    self._print(f"[OTP-CF] 验证码: {code}")
                    return code

            self._print(f"[OTP-CF] 第 {i + 1}/{attempts} 次未获取到验证码")

        self._print(f"[OTP-CF] 超时 ({attempts * interval}s)")
        return None

    def _collect_oauth_otp_candidates(self, mail_token: str, tried_codes: set):
        """收集 OAuth 流程可尝试的验证码列表"""
        if not self.cf_service:
            return []
        content = self.cf_service.fetch_first_email(mail_token)
        if not content:
            return []
        clean = re.sub(r"<[^>]+>", " ", str(content)).replace("=3D", "=").replace("=\n", "")
        code = self._extract_verification_code(clean)
        if code and code not in tried_codes:
            return [code]
        return []

    # ==================== 注册流程 ====================

    def visit_homepage(self):
        url = f"{self.BASE}/"
        r = self._http_request("GET", url, step="visit_homepage", headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }, allow_redirects=True)
        self._log("0. Visit homepage", "GET", url, r.status_code,
                   {"cookies_count": len(self.session.cookies)})

    def get_csrf(self) -> str:
        url = f"{self.BASE}/api/auth/csrf"
        r = self._http_request(
            "GET", url, step="get_csrf", headers={"Accept": "application/json", "Referer": f"{self.BASE}/"}
        )
        data = _safe_json_response(r)
        token = data.get("csrfToken", "")
        self._log("1. Get CSRF", "GET", url, r.status_code, data)
        if not token:
            raise Exception("Failed to get CSRF token")
        return token

    def signin(self, email: str, csrf: str) -> str:
        url = f"{self.BASE}/api/auth/signin/openai"
        params = {
            "prompt": "login", "ext-oai-did": self.device_id,
            "auth_session_logging_id": self.auth_session_logging_id,
            "screen_hint": "login_or_signup", "login_hint": email,
        }
        form_data = {"callbackUrl": f"{self.BASE}/", "csrfToken": csrf, "json": "true"}
        r = self._http_request("POST", url, step="signin", params=params, data=form_data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json", "Referer": f"{self.BASE}/", "Origin": self.BASE,
        })
        data = _safe_json_response(r)
        authorize_url = data.get("url", "")
        self._log("2. Signin", "POST", url, r.status_code, data)
        if not authorize_url:
            raise Exception("Failed to get authorize URL")
        return authorize_url

    def authorize(self, url: str) -> str:
        r = self._http_request("GET", url, step="authorize", headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{self.BASE}/", "Upgrade-Insecure-Requests": "1",
        }, allow_redirects=True)
        final_url = str(r.url)
        self._log("3. Authorize", "GET", url, r.status_code, {"final_url": final_url})
        return final_url

    def register(self, email: str, password: str):
        url = f"{self.AUTH}/api/accounts/user/register"
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                    "Referer": f"{self.AUTH}/create-account/password", "Origin": self.AUTH}
        headers.update(_make_trace_headers())
        r = self._http_request("POST", url, step="register", json={"username": email, "password": password}, headers=headers)
        try: data = r.json()
        except Exception: data = {"text": r.text[:500]}
        self._log("4. Register", "POST", url, r.status_code, data)
        return r.status_code, data

    def send_otp(self):
        url = f"{self.AUTH}/api/accounts/email-otp/send"
        r = self._http_request("GET", url, step="send_otp", headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{self.AUTH}/create-account/password", "Upgrade-Insecure-Requests": "1",
        }, allow_redirects=True)
        try: data = r.json()
        except Exception: data = {"final_url": str(r.url), "status": r.status_code}
        self._log("5. Send OTP", "GET", url, r.status_code, data)
        return r.status_code, data

    def validate_otp(self, code: str):
        url = f"{self.AUTH}/api/accounts/email-otp/validate"
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                    "Referer": f"{self.AUTH}/email-verification", "Origin": self.AUTH}
        headers.update(_make_trace_headers())
        r = self._http_request("POST", url, step="validate_otp", json={"code": code}, headers=headers)
        try: data = r.json()
        except Exception: data = {"text": r.text[:500]}
        self._log("6. Validate OTP", "POST", url, r.status_code, data)
        return r.status_code, data

    def create_account(self, name: str, birthdate: str):
        url = f"{self.AUTH}/api/accounts/create_account"
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                    "Referer": f"{self.AUTH}/about-you", "Origin": self.AUTH}
        headers.update(_make_trace_headers())
        r = self._http_request("POST", url, step="create_account", json={"name": name, "birthdate": birthdate}, headers=headers)
        try: data = r.json()
        except Exception: data = {"text": r.text[:500]}
        self._log("7. Create Account", "POST", url, r.status_code, data)
        if isinstance(data, dict):
            cb = data.get("continue_url") or data.get("url") or data.get("redirect_url")
            if cb:
                self._callback_url = cb
        return r.status_code, data

    def callback(self, url: str = None):
        if not url:
            url = self._callback_url
        if not url:
            self._print("[!] No callback URL, skipping.")
            return None, None
        r = self._http_request("GET", url, step="callback", headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }, allow_redirects=True)
        self._log("8. Callback", "GET", url, r.status_code, {"final_url": str(r.url)})
        return r.status_code, {"final_url": str(r.url)}

    # ==================== 自动注册主流程 ====================

    def run_register(self, email, password, name, birthdate, mail_token):
        """执行注册流程"""
        self.visit_homepage()
        _random_delay(0.3, 0.8)
        csrf = self.get_csrf()
        _random_delay(0.2, 0.5)
        auth_url = self.signin(email, csrf)
        _random_delay(0.3, 0.8)

        final_url = self.authorize(auth_url)
        final_path = urlparse(final_url).path
        _random_delay(0.3, 0.8)

        self._print(f"Authorize → {final_path}")

        need_otp = False

        if "create-account/password" in final_path:
            self._print("全新注册流程")
            _random_delay(0.5, 1.0)
            status, data = self.register(email, password)
            if status != 200:
                raise Exception(f"Register 失败 ({status}): {data}")
            # register 之后可能还需要 send_otp（全新注册流程中 OTP 不一定在 authorize 时发送）
            _random_delay(0.3, 0.8)
            otp_send_status, otp_send_data = self.send_otp()
            if otp_send_status != 200:
                raise Exception(f"发送验证码失败 ({otp_send_status}): {otp_send_data}")
            need_otp = True
        elif "email-verification" in final_path or "email-otp" in final_path:
            self._print("跳到 OTP 验证阶段 (authorize 已触发 OTP，不再重复发送)")
            # 不调用 send_otp()，因为 authorize 重定向到 email-verification 时服务器已发送 OTP
            need_otp = True
        elif "about-you" in final_path:
            self._print("跳到填写信息阶段")
            _random_delay(0.5, 1.0)
            self.create_account(name, birthdate)
            _random_delay(0.3, 0.5)
            self.callback()
            return True
        elif "callback" in final_path or "chatgpt.com" in final_url:
            self._print("账号已完成注册")
            return True
        else:
            self._print(f"未知跳转: {final_url}")
            self.register(email, password)
            otp_send_status, otp_send_data = self.send_otp()
            if otp_send_status != 200:
                raise Exception(f"发送验证码失败 ({otp_send_status}): {otp_send_data}")
            need_otp = True

        if need_otp:
            # 等待验证码
            otp_code = self.wait_for_verification_email(
                mail_token,
                initial_wait=0,
            )
            if not otp_code:
                raise Exception("未能获取验证码")

            _random_delay(0.3, 0.8)
            status, data = self.validate_otp(otp_code)
            if status != 200:
                self._print("验证码失败，重试...")
                otp_send_status, otp_send_data = self.send_otp()
                if otp_send_status != 200:
                    raise Exception(f"重试发送验证码失败 ({otp_send_status}): {otp_send_data}")
                otp_code = self.wait_for_verification_email(
                    mail_token,
                    timeout=60,
                    initial_wait=0,
                )
                if not otp_code:
                    raise Exception("重试后仍未获取验证码")
                _random_delay(0.3, 0.8)
                status, data = self.validate_otp(otp_code)
                if status != 200:
                    raise Exception(f"验证码失败 ({status}): {data}")

        _random_delay(0.5, 1.5)
        status, data = self.create_account(name, birthdate)
        if status != 200:
            raise Exception(f"Create account 失败 ({status}): {data}")
        _random_delay(0.2, 0.5)
        self.callback()
        return True

    def _decode_oauth_session_cookie(self):
        jar = getattr(self.session.cookies, "jar", None)
        if jar is not None:
            cookie_items = list(jar)
        else:
            cookie_items = []

        for c in cookie_items:
            name = getattr(c, "name", "") or ""
            if "oai-client-auth-session" not in name:
                continue

            raw_val = (getattr(c, "value", "") or "").strip()
            if not raw_val:
                continue

            candidates = [raw_val]
            try:
                from urllib.parse import unquote

                decoded = unquote(raw_val)
                if decoded != raw_val:
                    candidates.append(decoded)
            except Exception:
                pass

            for val in candidates:
                try:
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]

                    part = val.split(".")[0] if "." in val else val
                    pad = 4 - len(part) % 4
                    if pad != 4:
                        part += "=" * pad
                    raw = base64.urlsafe_b64decode(part)
                    data = json.loads(raw.decode("utf-8"))
                    if isinstance(data, dict):
                        return data
                except Exception:
                    continue
        return None

    def _oauth_allow_redirect_extract_code(self, url: str, referer: str = None):
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": self.ua,
        }
        if referer:
            headers["Referer"] = referer

        try:
            resp = self.session.get(
                url,
                headers=headers,
                allow_redirects=True,
                timeout=30,
                impersonate=self.impersonate,
            )
            final_url = str(resp.url)
            code = _extract_code_from_url(final_url)
            if code:
                self._print("[OAuth] allow_redirect 命中最终 URL code")
                return code

            for r in getattr(resp, "history", []) or []:
                loc = r.headers.get("Location", "")
                code = _extract_code_from_url(loc)
                if code:
                    self._print("[OAuth] allow_redirect 命中 history Location code")
                    return code
                code = _extract_code_from_url(str(r.url))
                if code:
                    self._print("[OAuth] allow_redirect 命中 history URL code")
                    return code
        except Exception as e:
            maybe_localhost = re.search(r'(https?://localhost[^\s\'\"]+)', str(e))
            if maybe_localhost:
                code = _extract_code_from_url(maybe_localhost.group(1))
                if code:
                    self._print("[OAuth] allow_redirect 从 localhost 异常提取 code")
                    return code
            self._print(f"[OAuth] allow_redirect 异常: {e}")

        return None

    def _oauth_follow_for_code(self, start_url: str, referer: str = None, max_hops: int = 16):
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": self.ua,
        }
        if referer:
            headers["Referer"] = referer

        current_url = start_url
        last_url = start_url

        for hop in range(max_hops):
            try:
                resp = self.session.get(
                    current_url,
                    headers=headers,
                    allow_redirects=False,
                    timeout=30,
                    impersonate=self.impersonate,
                )
            except Exception as e:
                maybe_localhost = re.search(r'(https?://localhost[^\s\'\"]+)', str(e))
                if maybe_localhost:
                    code = _extract_code_from_url(maybe_localhost.group(1))
                    if code:
                        self._print(f"[OAuth] follow[{hop + 1}] 命中 localhost 回调")
                        return code, maybe_localhost.group(1)
                self._print(f"[OAuth] follow[{hop + 1}] 请求异常: {e}")
                return None, last_url

            last_url = str(resp.url)
            self._print(f"[OAuth] follow[{hop + 1}] {resp.status_code} {last_url[:140]}")
            code = _extract_code_from_url(last_url)
            if code:
                return code, last_url

            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location", "")
                if not loc:
                    return None, last_url
                if loc.startswith("/"):
                    loc = f"{OAUTH_ISSUER}{loc}"
                code = _extract_code_from_url(loc)
                if code:
                    return code, loc
                current_url = loc
                headers["Referer"] = last_url
                continue

            return None, last_url

        return None, last_url

    def _oauth_submit_workspace_and_org(self, consent_url: str):
        session_data = self._decode_oauth_session_cookie()
        if not session_data:
            jar = getattr(self.session.cookies, "jar", None)
            if jar is not None:
                cookie_names = [getattr(c, "name", "") for c in list(jar)]
            else:
                cookie_names = list(self.session.cookies.keys())
            self._print(f"[OAuth] 无法解码 oai-client-auth-session, cookies={cookie_names[:12]}")
            return None

        workspaces = session_data.get("workspaces", [])
        if not workspaces:
            self._print("[OAuth] session 中没有 workspace 信息")
            return None

        workspace_id = (workspaces[0] or {}).get("id")
        if not workspace_id:
            self._print("[OAuth] workspace_id 为空")
            return None

        h = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": OAUTH_ISSUER,
            "Referer": consent_url,
            "User-Agent": self.ua,
            "oai-device-id": self.device_id,
        }
        h.update(_make_trace_headers())

        resp = self.session.post(
            f"{OAUTH_ISSUER}/api/accounts/workspace/select",
            json={"workspace_id": workspace_id},
            headers=h,
            allow_redirects=False,
            timeout=30,
            impersonate=self.impersonate,
        )
        self._print(f"[OAuth] workspace/select -> {resp.status_code}")

        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location", "")
            if loc.startswith("/"):
                loc = f"{OAUTH_ISSUER}{loc}"
            code = _extract_code_from_url(loc)
            if code:
                return code
            code, _ = self._oauth_follow_for_code(loc, referer=consent_url)
            if not code:
                code = self._oauth_allow_redirect_extract_code(loc, referer=consent_url)
            return code

        if resp.status_code != 200:
            self._print(f"[OAuth] workspace/select 失败: {resp.status_code}")
            return None

        try:
            ws_data = resp.json()
        except Exception:
            self._print("[OAuth] workspace/select 响应不是 JSON")
            return None

        ws_next = ws_data.get("continue_url", "")
        orgs = ws_data.get("data", {}).get("orgs", [])
        ws_page = (ws_data.get("page") or {}).get("type", "")
        self._print(f"[OAuth] workspace/select page={ws_page or '-'} next={(ws_next or '-')[:140]}")

        org_id = None
        project_id = None
        if orgs:
            org_id = (orgs[0] or {}).get("id")
            projects = (orgs[0] or {}).get("projects", [])
            if projects:
                project_id = (projects[0] or {}).get("id")

        if org_id:
            org_body = {"org_id": org_id}
            if project_id:
                org_body["project_id"] = project_id

            h_org = dict(h)
            if ws_next:
                h_org["Referer"] = ws_next if ws_next.startswith("http") else f"{OAUTH_ISSUER}{ws_next}"

            resp_org = self.session.post(
                f"{OAUTH_ISSUER}/api/accounts/organization/select",
                json=org_body,
                headers=h_org,
                allow_redirects=False,
                timeout=30,
                impersonate=self.impersonate,
            )
            self._print(f"[OAuth] organization/select -> {resp_org.status_code}")
            if resp_org.status_code in (301, 302, 303, 307, 308):
                loc = resp_org.headers.get("Location", "")
                if loc.startswith("/"):
                    loc = f"{OAUTH_ISSUER}{loc}"
                code = _extract_code_from_url(loc)
                if code:
                    return code
                code, _ = self._oauth_follow_for_code(loc, referer=h_org.get("Referer"))
                if not code:
                    code = self._oauth_allow_redirect_extract_code(loc, referer=h_org.get("Referer"))
                return code

            if resp_org.status_code == 200:
                try:
                    org_data = resp_org.json()
                except Exception:
                    self._print("[OAuth] organization/select 响应不是 JSON")
                    return None

                org_next = org_data.get("continue_url", "")
                org_page = (org_data.get("page") or {}).get("type", "")
                self._print(f"[OAuth] organization/select page={org_page or '-'} next={(org_next or '-')[:140]}")
                if org_next:
                    if org_next.startswith("/"):
                        org_next = f"{OAUTH_ISSUER}{org_next}"
                    code, _ = self._oauth_follow_for_code(org_next, referer=h_org.get("Referer"))
                    if not code:
                        code = self._oauth_allow_redirect_extract_code(org_next, referer=h_org.get("Referer"))
                    return code

        if ws_next:
            if ws_next.startswith("/"):
                ws_next = f"{OAUTH_ISSUER}{ws_next}"
            code, _ = self._oauth_follow_for_code(ws_next, referer=consent_url)
            if not code:
                code = self._oauth_allow_redirect_extract_code(ws_next, referer=consent_url)
            return code

        return None

    def perform_codex_oauth_login_http(self, email: str, password: str, mail_token: str = None):
        self._print("[OAuth] 开始执行 Codex OAuth 纯协议流程...")

        # 兼容两种 domain 形式，确保 auth 域也带 oai-did
        self.session.cookies.set("oai-did", self.device_id, domain=".auth.openai.com")
        self.session.cookies.set("oai-did", self.device_id, domain="auth.openai.com")

        code_verifier, code_challenge = _generate_pkce()
        state = secrets.token_urlsafe(24)

        authorize_params = {
            "response_type": "code",
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": "openid profile email offline_access",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        authorize_url = f"{OAUTH_ISSUER}/oauth/authorize?{urlencode(authorize_params)}"

        def _oauth_json_headers(referer: str):
            h = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": OAUTH_ISSUER,
                "Referer": referer,
                "User-Agent": self.ua,
                "oai-device-id": self.device_id,
            }
            h.update(_make_trace_headers())
            return h

        def _bootstrap_oauth_session():
            self._print("[OAuth] 1/7 GET /oauth/authorize")
            try:
                r = self.session.get(
                    authorize_url,
                    headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Referer": f"{self.BASE}/",
                        "Upgrade-Insecure-Requests": "1",
                        "User-Agent": self.ua,
                    },
                    allow_redirects=True,
                    timeout=30,
                    impersonate=self.impersonate,
                )
            except Exception as e:
                self._print(f"[OAuth] /oauth/authorize 异常: {e}")
                return False, ""

            final_url = str(r.url)
            redirects = len(getattr(r, "history", []) or [])
            self._print(f"[OAuth] /oauth/authorize -> {r.status_code}, final={(final_url or '-')[:140]}, redirects={redirects}")

            has_login = any(getattr(c, "name", "") == "login_session" for c in self.session.cookies)
            self._print(f"[OAuth] login_session: {'已获取' if has_login else '未获取'}")

            if not has_login:
                self._print("[OAuth] 未拿到 login_session，尝试访问 oauth2 auth 入口")
                oauth2_url = f"{OAUTH_ISSUER}/api/oauth/oauth2/auth"
                try:
                    r2 = self.session.get(
                        oauth2_url,
                        headers={
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                            "Referer": authorize_url,
                            "Upgrade-Insecure-Requests": "1",
                            "User-Agent": self.ua,
                        },
                        params=authorize_params,
                        allow_redirects=True,
                        timeout=30,
                        impersonate=self.impersonate,
                    )
                    final_url = str(r2.url)
                    redirects2 = len(getattr(r2, "history", []) or [])
                    self._print(f"[OAuth] /api/oauth/oauth2/auth -> {r2.status_code}, final={(final_url or '-')[:140]}, redirects={redirects2}")
                except Exception as e:
                    self._print(f"[OAuth] /api/oauth/oauth2/auth 异常: {e}")

                has_login = any(getattr(c, "name", "") == "login_session" for c in self.session.cookies)
                self._print(f"[OAuth] login_session(重试): {'已获取' if has_login else '未获取'}")

            return has_login, final_url

        def _post_authorize_continue(referer_url: str):
            sentinel_authorize = build_sentinel_token(
                self.session,
                self.device_id,
                flow="authorize_continue",
                user_agent=self.ua,
                sec_ch_ua=self.sec_ch_ua,
                impersonate=self.impersonate,
            )
            if not sentinel_authorize:
                self._print("[OAuth] authorize_continue 的 sentinel token 获取失败")
                return None

            headers_continue = _oauth_json_headers(referer_url)
            headers_continue["openai-sentinel-token"] = sentinel_authorize

            try:
                return self.session.post(
                    f"{OAUTH_ISSUER}/api/accounts/authorize/continue",
                    json={"username": {"kind": "email", "value": email}},
                    headers=headers_continue,
                    timeout=30,
                    allow_redirects=False,
                    impersonate=self.impersonate,
                )
            except Exception as e:
                self._print(f"[OAuth] authorize/continue 异常: {e}")
                return None

        _, authorize_final_url = _bootstrap_oauth_session()
        if not authorize_final_url:
            return None

        continue_referer = authorize_final_url if authorize_final_url.startswith(OAUTH_ISSUER) else f"{OAUTH_ISSUER}/log-in"

        self._print("[OAuth] 2/7 POST /api/accounts/authorize/continue")
        resp_continue = _post_authorize_continue(continue_referer)
        if resp_continue is None:
            return None

        self._print(f"[OAuth] /authorize/continue -> {resp_continue.status_code}")
        if resp_continue.status_code == 400 and "invalid_auth_step" in (resp_continue.text or ""):
            self._print("[OAuth] invalid_auth_step，重新 bootstrap 后重试一次")
            _, authorize_final_url = _bootstrap_oauth_session()
            if not authorize_final_url:
                return None
            continue_referer = authorize_final_url if authorize_final_url.startswith(OAUTH_ISSUER) else f"{OAUTH_ISSUER}/log-in"
            resp_continue = _post_authorize_continue(continue_referer)
            if resp_continue is None:
                return None
            self._print(f"[OAuth] /authorize/continue(重试) -> {resp_continue.status_code}")

        if resp_continue.status_code != 200:
            self._print(f"[OAuth] 邮箱提交失败: {resp_continue.text[:180]}")
            return None

        try:
            continue_data = resp_continue.json()
        except Exception:
            self._print("[OAuth] authorize/continue 响应解析失败")
            return None

        continue_url = continue_data.get("continue_url", "")
        page_type = (continue_data.get("page") or {}).get("type", "")
        self._print(f"[OAuth] continue page={page_type or '-'} next={(continue_url or '-')[:140]}")

        self._print("[OAuth] 3/7 POST /api/accounts/password/verify")
        sentinel_pwd = build_sentinel_token(
            self.session,
            self.device_id,
            flow="password_verify",
            user_agent=self.ua,
            sec_ch_ua=self.sec_ch_ua,
            impersonate=self.impersonate,
        )
        if not sentinel_pwd:
            self._print("[OAuth] password_verify 的 sentinel token 获取失败")
            return None

        headers_verify = _oauth_json_headers(f"{OAUTH_ISSUER}/log-in/password")
        headers_verify["openai-sentinel-token"] = sentinel_pwd

        try:
            resp_verify = self.session.post(
                f"{OAUTH_ISSUER}/api/accounts/password/verify",
                json={"password": password},
                headers=headers_verify,
                timeout=30,
                allow_redirects=False,
                impersonate=self.impersonate,
            )
        except Exception as e:
            self._print(f"[OAuth] password/verify 异常: {e}")
            return None

        self._print(f"[OAuth] /password/verify -> {resp_verify.status_code}")
        if resp_verify.status_code != 200:
            self._print(f"[OAuth] 密码校验失败: {resp_verify.text[:180]}")
            return None

        try:
            verify_data = resp_verify.json()
        except Exception:
            self._print("[OAuth] password/verify 响应解析失败")
            return None

        continue_url = verify_data.get("continue_url", "") or continue_url
        page_type = (verify_data.get("page") or {}).get("type", "") or page_type
        self._print(f"[OAuth] verify page={page_type or '-'} next={(continue_url or '-')[:140]}")

        need_oauth_otp = (
            page_type == "email_otp_verification"
            or "email-verification" in (continue_url or "")
            or "email-otp" in (continue_url or "")
        )

        if need_oauth_otp:
            self._print("[OAuth] 4/7 检测到邮箱 OTP 验证")
            if not mail_token:
                self._print("[OAuth] OAuth 阶段需要邮箱 OTP，但未提供 mail_token")
                return None

            headers_otp = _oauth_json_headers(f"{OAUTH_ISSUER}/email-verification")
            stale_codes = set(self._collect_oauth_otp_candidates(mail_token, set()))
            if stale_codes:
                self._print(f"[OAuth] 检测到历史验证码 {len(stale_codes)} 个，等待新验证码")
            tried_codes = set()
            otp_success = False
            otp_deadline = time.time() + 120

            while time.time() < otp_deadline and not otp_success:
                candidate_codes = self._collect_oauth_otp_candidates(mail_token, tried_codes.union(stale_codes))

                if not candidate_codes:
                    elapsed = int(120 - max(0, otp_deadline - time.time()))
                    self._print(f"[OAuth] OTP 等待中... ({elapsed}s/120s)")
                    time.sleep(2)
                    continue

                for otp_code in candidate_codes:
                    tried_codes.add(otp_code)
                    self._print(f"[OAuth] 尝试 OTP: {otp_code}")
                    try:
                        resp_otp = self.session.post(
                            f"{OAUTH_ISSUER}/api/accounts/email-otp/validate",
                            json={"code": otp_code},
                            headers=headers_otp,
                            timeout=30,
                            allow_redirects=False,
                            impersonate=self.impersonate,
                        )
                    except Exception as e:
                        self._print(f"[OAuth] email-otp/validate 异常: {e}")
                        continue

                    self._print(f"[OAuth] /email-otp/validate -> {resp_otp.status_code}")
                    if resp_otp.status_code != 200:
                        self._print(f"[OAuth] OTP 无效，继续尝试下一条: {resp_otp.text[:160]}")
                        continue

                    try:
                        otp_data = resp_otp.json()
                    except Exception:
                        self._print("[OAuth] email-otp/validate 响应解析失败")
                        continue

                    continue_url = otp_data.get("continue_url", "") or continue_url
                    page_type = (otp_data.get("page") or {}).get("type", "") or page_type
                    self._print(f"[OAuth] OTP 验证通过 page={page_type or '-'} next={(continue_url or '-')[:140]}")
                    otp_success = True
                    break

                if not otp_success:
                    time.sleep(2)

            if not otp_success:
                self._print(f"[OAuth] OAuth 阶段 OTP 验证失败，已尝试 {len(tried_codes)} 个验证码")
                return None

        code = None
        consent_url = continue_url
        if consent_url and consent_url.startswith("/"):
            consent_url = f"{OAUTH_ISSUER}{consent_url}"

        if not consent_url and "consent" in page_type:
            consent_url = f"{OAUTH_ISSUER}/sign-in-with-chatgpt/codex/consent"

        if consent_url:
            code = _extract_code_from_url(consent_url)

        if not code and consent_url:
            self._print("[OAuth] 5/7 跟随 continue_url 提取 code")
            code, _ = self._oauth_follow_for_code(consent_url, referer=f"{OAUTH_ISSUER}/log-in/password")

        consent_hint = (
            ("consent" in (consent_url or ""))
            or ("sign-in-with-chatgpt" in (consent_url or ""))
            or ("workspace" in (consent_url or ""))
            or ("organization" in (consent_url or ""))
            or ("consent" in page_type)
            or ("organization" in page_type)
        )

        if not code and consent_hint:
            if not consent_url:
                consent_url = f"{OAUTH_ISSUER}/sign-in-with-chatgpt/codex/consent"
            self._print("[OAuth] 6/7 执行 workspace/org 选择")
            code = self._oauth_submit_workspace_and_org(consent_url)

        if not code:
            fallback_consent = f"{OAUTH_ISSUER}/sign-in-with-chatgpt/codex/consent"
            self._print("[OAuth] 6/7 回退 consent 路径重试")
            code = self._oauth_submit_workspace_and_org(fallback_consent)
            if not code:
                code, _ = self._oauth_follow_for_code(fallback_consent, referer=f"{OAUTH_ISSUER}/log-in/password")

        if not code:
            self._print("[OAuth] 未获取到 authorization code")
            return None

        self._print("[OAuth] 7/7 POST /oauth/token")
        token_resp = self.session.post(
            f"{OAUTH_ISSUER}/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": self.ua},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": OAUTH_REDIRECT_URI,
                "client_id": OAUTH_CLIENT_ID,
                "code_verifier": code_verifier,
            },
            timeout=60,
            impersonate=self.impersonate,
        )
        self._print(f"[OAuth] /oauth/token -> {token_resp.status_code}")

        if token_resp.status_code != 200:
            self._print(f"[OAuth] token 交换失败: {token_resp.status_code} {token_resp.text[:200]}")
            return None

        try:
            data = token_resp.json()
        except Exception:
            self._print("[OAuth] token 响应解析失败")
            return None

        if not data.get("access_token"):
            self._print("[OAuth] token 响应缺少 access_token")
            return None

        self._print("[OAuth] Codex Token 获取成功")
        return data


# ==================== 并发批量注册 ====================

def _register_one(idx, total, registration_proxy):
    """单个注册任务 (在线程中运行)"""
    reg = None
    try:
        with _print_lock:
            print(f"[Proxy] [账号 {idx}] 使用代理: {registration_proxy or '无(直连)'}")

        reg = ChatGPTRegister(proxy=registration_proxy, tag=f"{idx}")

        # 1. 创建临时邮箱
        reg._print("[Cloudflare] 创建域名邮箱...")
        email, email_pwd, mail_token = reg.create_temp_email()
        tag = email.split("@")[0]
        reg.tag = tag  # 更新 tag

        chatgpt_password = _generate_password()
        name = _random_name()
        birthdate = _random_birthdate()

        if not IS_PROD_LOG:
            with _print_lock:
                print(f"\n{'='*60}")
                print(f"  [{idx}/{total}] 注册: {email}")
                print(f"  ChatGPT密码: {chatgpt_password}")
                print(f"  邮箱密码: {email_pwd}")
                print(f"  姓名: {name} | 生日: {birthdate}")
                print(f"{'='*60}")

        # 2. 执行注册流程
        reg.run_register(email, chatgpt_password, name, birthdate, mail_token)

        # 3. OAuth（可选）
        oauth_ok = True
        if ENABLE_OAUTH:
            reg._print("[OAuth] 开始获取 Codex Token...")
            tokens = reg.perform_codex_oauth_login_http(email, chatgpt_password, mail_token=mail_token)
            oauth_ok = bool(tokens and tokens.get("access_token"))
            if oauth_ok:
                account_record = {
                    "email": email,
                    "chatgpt_password": chatgpt_password,
                    "mailbox_password": email_pwd,
                    "name": name,
                    "birthdate": birthdate,
                }
                _save_codex_tokens(email, tokens, account_info=account_record)
                reg._print("[OAuth] Token 已保存")
            else:
                msg = "OAuth 获取失败"
                if OAUTH_REQUIRED:
                    raise Exception(f"{msg}（oauth_required=true）")
                reg._print(f"[OAuth] {msg}（按配置继续）")

        _, _, just_reached_target = _mark_batch_success()
        if just_reached_target:
            reg._print(f"[Batch] 已达到目标注册数量({_batch_target_success})，等待在途任务完成后退出")

        reg._print(f"第 {idx} 个账号注册成功，账号邮箱：{email}")

        if POST_ACCOUNT_WAIT_MAX_SECONDS > 0 and not _batch_target_reached_event.is_set():
            wait_s = random.uniform(POST_ACCOUNT_WAIT_MIN_SECONDS, POST_ACCOUNT_WAIT_MAX_SECONDS)
            reg._print(f"[Post] 账号处理完成，等待 {wait_s:.1f}s（若已达目标将提前结束等待）")
            remaining = wait_s
            while remaining > 0 and not _batch_target_reached_event.is_set():
                step = min(0.5, remaining)
                time.sleep(step)
                remaining -= step

        with _print_lock:
            print(f"\n[OK] {email} 注册成功!")
        return True, email, None

    except Exception as e:
        error_msg = str(e)
        tb_text = _format_traceback()
        with _print_lock:
            print(f"\n[FAIL] [{idx}] 注册失败: {error_msg} | 代理: {registration_proxy or '无(直连)'}")
            if not IS_PROD_LOG and tb_text and tb_text.strip() and tb_text.strip() != "NoneType: None":
                print(tb_text.rstrip())
        return False, None, error_msg


def run_batch(total_accounts: int = 3, output_file="registered_accounts.txt",
              max_workers=3, proxy_pool=None):
    """并发批量注册"""

    total_accounts = max(0, int(total_accounts or 0))
    _reset_batch_success_target(total_accounts)

    _prepare_artifact_dirs()
    output_file = _normalize_token_artifact_path(output_file, "registered_accounts.txt")
    proxy_pool = [str(p).strip() for p in (proxy_pool or []) if str(p).strip()]

    if not CLOUDFLARE_JWT_TOKEN:
        print("❌ 错误: 未设置 cloudflare_jwt_token")
        print("   请在 config.py 中设置 cloudflare_jwt_token")
        return {
            "ok": False,
            "total": total_accounts,
            "success": 0,
            "fail": total_accounts,
            "elapsed": 0,
            "output_file": output_file,
            "error": "missing_cloudflare_jwt_token",
        }

    if total_accounts == 0:
        print("[Info] total_accounts=0，无需注册，程序退出")
        return {
            "ok": True,
            "total": 0,
            "success": 0,
            "fail": 0,
            "elapsed": 0,
            "output_file": output_file,
            "error": "",
        }

    actual_workers = max(1, min(int(max_workers or 1), total_accounts))
    print(f"\n{'#'*60}")
    print(f"  ChatGPT 批量自动注册")
    print(f"  注册数量: {total_accounts} | 并发数: {actual_workers}")
    print(f"  邮箱提供方: Cloudflare")
    print(f"  Cloudflare API: {CLOUDFLARE_API_BASE}")
    print(f"  Cloudflare 域名: {CLOUDFLARE_DOMAIN}")
    print(f"  Cloudflare OTP轮询: {CLOUDFLARE_POLL_ATTEMPTS} 次 x {CLOUDFLARE_POLL_INTERVAL}s")
    print(f"  OAuth: {'开启' if ENABLE_OAUTH else '关闭'} | required: {'是' if OAUTH_REQUIRED else '否'}")
    if ENABLE_OAUTH:
        print(f"  OAuth Issuer: {OAUTH_ISSUER}")
        print(f"  OAuth Client: {OAUTH_CLIENT_ID}")
        print(f"  Token输出目录: {_abs_path(TOKEN_BASE_DIR)}")
        print(f"  服务目录映射: {SERVICE_TOKEN_DIRS}")
        print(f"  上传目标: {UPLOAD_TARGETS}")
    print(f"  账号完成后等待: {POST_ACCOUNT_WAIT_MIN_SECONDS:.1f}s ~ {POST_ACCOUNT_WAIT_MAX_SECONDS:.1f}s")
    if proxy_pool:
        print(f"  注册代理池: {len(proxy_pool)} 个 (轮询分配)")
    else:
        print("  注册代理: 无")
    print(f"{'#'*60}\n")

    success_count = 0
    fail_count = 0
    start_time = time.time()

    try:
        with ThreadPoolExecutor(max_workers=actual_workers) as executor:
            futures = {}
            next_idx = 1
            stop_submit_logged = False

            def _submit_one(task_idx: int):
                assigned_proxy = None
                if proxy_pool:
                    assigned_proxy = proxy_pool[(task_idx - 1) % len(proxy_pool)]
                future = executor.submit(
                    _register_one, task_idx, total_accounts, assigned_proxy
                )
                futures[future] = task_idx

            # 先灌满并发槽
            while next_idx <= total_accounts and len(futures) < actual_workers and not _batch_target_reached_event.is_set():
                _submit_one(next_idx)
                next_idx += 1

            # 动态补位：达到目标后停止提交新任务，只等待在途任务完成
            while futures:
                done_set, _ = wait(set(futures.keys()), return_when=FIRST_COMPLETED)
                for future in done_set:
                    idx = futures.pop(future)
                    try:
                        ok, email, err = future.result()
                        if ok:
                            success_count += 1
                        else:
                            fail_count += 1
                            print(f"  [账号 {idx}] 失败: {err}")
                    except Exception as e:
                        fail_count += 1
                        with _print_lock:
                            print(f"[FAIL] 账号 {idx} 线程异常: {e}")

                if _batch_target_reached_event.is_set():
                    if next_idx <= total_accounts and not stop_submit_logged:
                        with _print_lock:
                            print(f"[Batch] 已达到目标注册数量({total_accounts})，停止提交新任务，等待 {len(futures)} 个在途任务完成...")
                        stop_submit_logged = True
                    continue

                while next_idx <= total_accounts and len(futures) < actual_workers:
                    _submit_one(next_idx)
                    next_idx += 1
    except Exception as e:
        elapsed = time.time() - start_time
        with _print_lock:
            print(f"[FAIL] 批量任务发生未捕获异常: {e}")
            tb_text = _format_traceback()
            if not IS_PROD_LOG and tb_text and tb_text.strip() and tb_text.strip() != "NoneType: None":
                print(tb_text.rstrip())
        return {
            "ok": False,
            "total": total_accounts,
            "success": success_count,
            "fail": max(fail_count, total_accounts - success_count),
            "elapsed": elapsed,
            "output_file": output_file,
            "error": f"run_batch_exception: {e}",
        }

    elapsed = time.time() - start_time
    avg = elapsed / total_accounts if total_accounts else 0
    print(f"\n{'#'*60}")
    print(f"  注册完成! 耗时 {elapsed:.1f} 秒")
    print(f"  总数: {total_accounts} | 成功: {success_count} | 失败: {fail_count}")
    print(f"  平均速度: {avg:.1f} 秒/个")
    print(f"{'#'*60}")
    return {
        "ok": fail_count == 0,
        "total": total_accounts,
        "success": success_count,
        "fail": fail_count,
        "elapsed": elapsed,
        "output_file": output_file,
        "error": "" if fail_count == 0 else "partial_or_full_failure",
    }


def _build_runtime_container():
    container = build_container(_BASE_DIR)

    token_check_use_case = TokenCheckUseCase(
        deps=TokenCheckDependencies(
            prepare_artifacts=_prepare_artifact_dirs,
            load_local_accounts_for_check=_load_local_accounts_for_check,
            build_check_account_record=_build_check_account_record,
            check_one_local_account=_check_one_local_account,
            delete_remote_sub2api_account=_delete_remote_sub2api_account,
            delete_remote_cliproxyapi_file=_delete_remote_cliproxyapi_file,
            delete_local_service_files=_delete_local_service_files,
            remove_local_account_from_accounts_file=_remove_local_account_from_accounts_file,
            resolve_report_path=_token_check_report_path,
            service_token_filename=_service_token_filename,
            write_json=_write_json,
            print_fn=print,
            sleep=time.sleep,
            proxy_pool=list(DEFAULT_PROXY_POOL),
            token_check_sleep=TOKEN_CHECK_SLEEP,
        )
    )
    maintain_accounts_use_case = MaintainAccountsUseCase(
        deps=MaintainAccountsDependencies(
            prepare_artifacts=_prepare_artifact_dirs,
            token_check_use_case=token_check_use_case,
            count_local_accounts=_count_local_accounts,
            run_batch=run_batch,
            print_fn=print,
            sleep=time.sleep,
            random_uniform=random.uniform,
            artifact_output_file=ARTIFACT_OUTPUT_FILE,
            retry_limit=MAINTAIN_REGISTER_RETRY_LIMIT,
            wait_min_seconds=POST_ACCOUNT_WAIT_MIN_SECONDS,
            wait_max_seconds=POST_ACCOUNT_WAIT_MAX_SECONDS,
        )
    )

    container.token_check_use_case = token_check_use_case
    container.maintain_accounts_use_case = maintain_accounts_use_case
    return container


def main():
    parser = build_parser()
    args = parser.parse_args()
    container = _build_runtime_container()

    if args.command == "check-tokens":
        result = container.token_check_use_case.execute(input_path=args.input, report_path=args.report)
        return 0 if result.get("ok") else 1

    if args.command == "maintain":
        print("=" * 60)
        print("  ChatGPT 账号持续保号工具")
        print("=" * 60)
        proxy_pool = list(DEFAULT_PROXY_POOL)
        total_accounts = DEFAULT_TOTAL_ACCOUNTS
        max_workers = DEFAULT_MAX_WORKERS
        interval = int(args.interval or MAINTAIN_CHECK_INTERVAL_SECONDS)
        run_maintain_loop(
            target_total=total_accounts,
            max_workers=max_workers,
            proxy_pool=proxy_pool,
            interval_seconds=interval,
            maintain_use_case=container.maintain_accounts_use_case,
            check_input_path="",
            report_path="",
        )
        return 0

    print("=" * 60)
    print("  ChatGPT 批量自动注册工具")
    print("=" * 60)

    # 检查邮箱配置
    if not CLOUDFLARE_JWT_TOKEN:
        print("\n⚠️  警告: 未设置 cloudflare_jwt_token")
        print("   Cloudflare 模式将无法拉取验证码邮件")
        print("   请先在 config.py 设置 cloudflare_jwt_token")
        current_state = load_run_state(_BASE_DIR)
        current_state.update({
            "status": "error",
            "message": "missing_cloudflare_jwt_token",
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        })
        save_run_state(current_state, _BASE_DIR)
        return 1

    proxy_pool = list(DEFAULT_PROXY_POOL)

    if proxy_pool:
        print(f"[Info] 使用代理池: {', '.join(proxy_pool)}")
    else:
        print("[Info] 未配置代理池，注册流程将不使用代理")

    # 直接使用配置文件中的数量和并发，不再交互式输入
    total_accounts = DEFAULT_TOTAL_ACCOUNTS
    max_workers = DEFAULT_MAX_WORKERS

    _prepare_artifact_dirs()
    print(f"[Info] 统一产物目录: {_tokens_root()}")

    state = load_run_state(_BASE_DIR)
    state.update({
        "status": "running",
        "message": "batch_register_started",
        "last_run_id": datetime.now().strftime("%Y%m%d%H%M%S"),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": "",
        "planned_total_accounts": int(total_accounts),
        "completed_accounts": 0,
        "success_count": 0,
        "fail_count": 0,
        "elapsed_seconds": 0,
        "total_runs": int(state.get("total_runs", 0) or 0) + 1,
    })
    save_run_state(state, _BASE_DIR)

    try:
        if MAINTAIN_ENABLED:
            print(f"[Info] maintain_enabled=true，进入持续保号模式，目标账号数: {total_accounts}，巡检周期: {MAINTAIN_CHECK_INTERVAL_SECONDS}s")
            run_maintain_loop(
                target_total=total_accounts,
                max_workers=max_workers,
                proxy_pool=proxy_pool,
                interval_seconds=MAINTAIN_CHECK_INTERVAL_SECONDS,
                maintain_use_case=container.maintain_accounts_use_case,
            )
            return 0

        result = run_batch(total_accounts=total_accounts, output_file=ARTIFACT_OUTPUT_FILE,
                           max_workers=max_workers, proxy_pool=proxy_pool)
    except KeyboardInterrupt:
        print("\n[Info] 已收到停止信号，程序退出")
        state = load_run_state(_BASE_DIR)
        state.update({
            "status": "idle",
            "message": "stopped_by_user",
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        })
        save_run_state(state, _BASE_DIR)
        return 130
    except Exception as e:
        with _print_lock:
            print(f"[FAIL] 主流程异常: {e}")
            tb_text = _format_traceback()
            if not IS_PROD_LOG and tb_text and tb_text.strip() and tb_text.strip() != "NoneType: None":
                print(tb_text.rstrip())
        result = {
            "ok": False,
            "total": int(total_accounts or 0),
            "success": 0,
            "fail": int(total_accounts or 0),
            "elapsed": 0,
            "output_file": ARTIFACT_OUTPUT_FILE,
            "error": f"main_exception: {e}",
        }

    state = load_run_state(_BASE_DIR)
    state.update({
        "status": "done" if result.get("ok") else "error",
        "message": result.get("error", "") or "batch_register_finished",
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "planned_total_accounts": int(result.get("total", total_accounts) or 0),
        "completed_accounts": int((result.get("success", 0) or 0) + (result.get("fail", 0) or 0)),
        "success_count": int(result.get("success", 0) or 0),
        "fail_count": int(result.get("fail", 0) or 0),
        "elapsed_seconds": round(float(result.get("elapsed", 0) or 0), 2),
    })
    save_run_state(state, _BASE_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
