"""兼容层：保留原 settings API，同时内部切换到新 loader / schema / repository。"""

from __future__ import annotations

from app.config.loader import load_run_state_model, load_settings, save_run_state_model
from app.domain.models.run_state import RunState


def load_settings_model(base_dir: str = None):
    return load_settings(base_dir)


def load_config(base_dir: str = None):
    """兼容旧逻辑：仍返回 dict，供 legacy main.py 使用。"""
    return load_settings(base_dir).to_dict()


def load_run_state(base_dir: str = None):
    """兼容旧逻辑：仍返回 dict。"""
    return load_run_state_model(base_dir).to_dict()


def save_run_state(state: dict, base_dir: str = None):
    """兼容旧逻辑：接受 dict，内部转换为 RunState 仓储保存。"""
    model = RunState.from_dict(state)
    return save_run_state_model(model, base_dir).to_dict()
