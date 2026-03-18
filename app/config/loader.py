from __future__ import annotations

import copy
import importlib.util
import json
import os

from app.config.config import StaticConfig
from app.domain.models.run_state import RunState
from app.domain.models.settings import AppSettings
from app.infrastructure.persistence.json_run_state_repository import JsonRunStateRepository


_LEGACY_CONFIG_KEYS = ("ak_file", "rk_file")


def _read_json(filepath: str):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"⚠️ 加载 {os.path.basename(filepath)} 失败: {e}")
        return {}


def _read_py_config(filepath: str):
    if not os.path.exists(filepath):
        return {}
    try:
        spec = importlib.util.spec_from_file_location("chatgpt_register_user_config", filepath)
        if spec is None or spec.loader is None:
            return {}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        data = {}

        config_dict = getattr(module, "CONFIG", None)
        if isinstance(config_dict, dict):
            data.update(config_dict)

        for key in StaticConfig.DEFAULTS.keys():
            if hasattr(module, key):
                data[key] = getattr(module, key)

        return data
    except Exception as e:
        print(f"⚠️ 加载 {os.path.basename(filepath)} 失败: {e}")
        return {}


def load_settings(base_dir: str | None = None) -> AppSettings:
    root = StaticConfig.project_root(base_dir)
    config = copy.deepcopy(StaticConfig.DEFAULTS)
    user_config_path = os.path.join(root, StaticConfig.USER_CONFIG_FILE)

    py_config = _read_py_config(user_config_path)
    if py_config:
        config.update(py_config)

    # 历史字段兼容：允许旧配置保留 ak_file/rk_file，不影响新模型。
    for key in _LEGACY_CONFIG_KEYS:
        config.pop(key, None)

    config["upload_targets"] = [
        str(x).strip().lower() for x in (config.get("upload_targets") or []) if str(x).strip()
    ]
    config["proxy_pool"] = list(config.get("proxy_pool", []) or [])
    return AppSettings.from_dict(config)


def load_run_state_model(base_dir: str | None = None) -> RunState:
    root = StaticConfig.project_root(base_dir)
    state_path = os.path.join(root, StaticConfig.RUN_STATE_FILE)
    repo = JsonRunStateRepository(
        filepath=state_path,
        default_state=RunState.from_dict(StaticConfig.DEFAULT_RUN_STATE),
    )
    return repo.load()


def save_run_state_model(state: RunState, base_dir: str | None = None) -> RunState:
    root = StaticConfig.project_root(base_dir)
    state_path = os.path.join(root, StaticConfig.RUN_STATE_FILE)
    repo = JsonRunStateRepository(
        filepath=state_path,
        default_state=RunState.from_dict(StaticConfig.DEFAULT_RUN_STATE),
    )
    return repo.save(state)
