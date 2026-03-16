"""配置模块。"""

from .config import StaticConfig
from .settings import load_config, load_run_state, save_run_state

__all__ = ["StaticConfig", "load_config", "load_run_state", "save_run_state"]
