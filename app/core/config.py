"""角色配置加载与用户设置持久化。

character_config.json 由开发需求文档派生，包含人设、饮品数值、台词、状态阈值等。
用户设置（语言/音量/尺寸/自启/工作时间等）单独持久化到 data/settings.json。
"""

import json
import os
import copy

from app.core import pathutil

CONFIG_PATH = os.path.join(pathutil.get_assets_dir(), "character_config.json")
SETTINGS_PATH = pathutil.data_file("settings.json")

DEFAULT_SETTINGS = {
    "language": "zh-CN",          # zh-CN / zh-TW / en
    "volume": 50,                 # 0-100
    "sizeScale": 100,             # 50-150 (%)
    "autostart": True,
    "workTime": {
        "morning": ["09:00", "12:00"],
        "afternoon": ["13:30", "18:00"],
    },
    "costume": "衬衫",
    "lastCleanupWeek": "",        # 每周一清理标记
    "voiceEngine": "sapi",         # sapi / gpt_sovits
}


class CharacterConfig:
    """只读加载角色配置。"""

    def __init__(self, path: str = CONFIG_PATH):
        self.path = path
        self._data = self._load()

    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"无法加载角色配置 {self.path}: {e}")

    # ---- 通用访问 ----
    def get(self, *keys, default=None):
        cur = self._data
        for k in keys:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return default
        return cur

    # ---- 便捷访问 ----
    @property
    def app_name(self) -> str:
        return self.get("basicSetting", "character", "appName", default="AT小PP")

    @property
    def copyright(self) -> str:
        return self.get("copyright", default="Copyright © 2026 Christopher Hsu. All rights reserved.")

    @property
    def boot_lines(self) -> list:
        return self.get("basicSetting", "bootLines", default=[])

    @property
    def status_config(self) -> list:
        return self.get("basicSetting", "statusConfig", default=[])

    @property
    def global_algorithm(self) -> dict:
        return self.get("basicSetting", "globalAlgorithm", default={})

    @property
    def drinks(self) -> dict:
        return self.get("drinks", default={})

    @property
    def costume(self) -> dict:
        return self.get("costume", default={})

    @property
    def work(self) -> dict:
        return self.get("work", default={})

    @property
    def home(self) -> dict:
        return self.get("home", default={})

    @property
    def system_func(self) -> dict:
        return self.get("systemFunc", default={})

    @property
    def install_uninstall(self) -> dict:
        return self.get("installUninstall", default={})


class Settings:
    """用户设置读写（带默认值合并）。"""

    def __init__(self, path: str = SETTINGS_PATH):
        self.path = path
        self._data = self._load()

    def _load(self) -> dict:
        data = copy.deepcopy(DEFAULT_SETTINGS)
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self._deep_update(data, saved)
        except FileNotFoundError:
            pass
        except Exception:  # noqa: BLE001
            pass
        return data

    @staticmethod
    def _deep_update(base: dict, override: dict):
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                Settings._deep_update(base[k], v)
            else:
                base[k] = v

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value, save: bool = True):
        self._data[key] = value
        if save:
            self.save()

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass


# 全局单例
character = CharacterConfig()
settings = Settings()
