import json
import os
from pathlib import Path
from typing import Any, Optional


class ConfigManager:
    """基于 JSON 文件的配置管理器，支持多级嵌套 key 的读写。"""

    def __init__(self, path: Optional[str] = None):
        if path is None:
            # 默认放在项目根目录的 config/user.json
            root = Path(__file__).resolve().parents[2]
            path = root / "config" / "user.json"
        self._path = Path(path)
        self._config: dict = {}
        self.load()

    def load(self) -> dict:
        """加载配置；若文件不存在，则加载 default.json 并保存。"""
        if self._path.exists():
            with open(self._path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
            return self._config

        # 回退到默认配置
        default_path = self._path.with_name("default.json")
        if default_path.exists():
            with open(default_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
        else:
            self._config = {}
        self.save()
        return self._config

    def save(self) -> None:
        """将当前配置写回文件。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, ensure_ascii=False, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        """
        支持点号分隔的多级 key，例如：
            get("asr.app_id")
            get("llm.api_key")
        """
        keys = key.split(".")
        val = self._config
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    def set(self, key: str, value: Any) -> None:
        """支持点号分隔的多级 key 写入。"""
        keys = key.split(".")
        cfg = self._config
        for k in keys[:-1]:
            if k not in cfg or not isinstance(cfg[k], dict):
                cfg[k] = {}
            cfg = cfg[k]
        cfg[keys[-1]] = value
        self.save()

    @property
    def raw(self) -> dict:
        return self._config
