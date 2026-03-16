import copy
import importlib.util
import json
import os
from datetime import datetime

from .config import StaticConfig


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

        # 兼容旧格式：CONFIG = {...}
        config_dict = getattr(module, "CONFIG", None)
        if isinstance(config_dict, dict):
            data.update(config_dict)

        # 新格式：直接在 config.py 顶层定义变量（例如 total_accounts = 1）
        for key in StaticConfig.DEFAULTS.keys():
            if hasattr(module, key):
                data[key] = getattr(module, key)

        return data
    except Exception as e:
        print(f"⚠️ 加载 {os.path.basename(filepath)} 失败: {e}")
        return {}


def load_config(base_dir: str = None):
    """加载运行配置：静态默认(app/config/config.py) + 根目录动态覆盖(config.py)。"""
    root = StaticConfig.project_root(base_dir)
    config = copy.deepcopy(StaticConfig.DEFAULTS)
    user_config_path = os.path.join(root, StaticConfig.USER_CONFIG_FILE)

    py_config = _read_py_config(user_config_path)
    if py_config:
        config.update(py_config)

    # 规范 upload_targets
    targets = [str(x).strip().lower() for x in (config.get("upload_targets") or []) if str(x).strip()]
    config["upload_targets"] = targets

    config["proxy_pool"] = config.get("proxy_pool", []) or []
    return config


def load_run_state(base_dir: str = None):
    """加载运行状态：默认状态(config.py) + run_state.json 覆盖。"""
    root = StaticConfig.project_root(base_dir)
    state = copy.deepcopy(StaticConfig.DEFAULT_RUN_STATE)
    state_path = os.path.join(root, StaticConfig.RUN_STATE_FILE)
    file_state = _read_json(state_path)
    if file_state:
        state.update(file_state)
    return state


def save_run_state(state: dict, base_dir: str = None):
    """保存运行状态到 run_state.json。"""
    root = StaticConfig.project_root(base_dir)
    filepath = os.path.join(root, StaticConfig.RUN_STATE_FILE)
    merged = copy.deepcopy(StaticConfig.DEFAULT_RUN_STATE)
    merged.update(state or {})
    merged["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return merged