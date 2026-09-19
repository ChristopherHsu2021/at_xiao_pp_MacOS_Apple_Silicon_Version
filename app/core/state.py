"""全局状态：微醺值 / 清醒值 / 当前服装 / 闲置计时 等。

数值变化通过信号广播，状态面板订阅更新。
微醺/清醒值持久化到 data/state.json，跨会话保留。
"""

import os
import time
import random
from datetime import date

from PyQt6.QtCore import QObject, pyqtSignal

from app.core import config, pathutil

STATE_PATH = pathutil.data_file("state.json")


class AppState(QObject):
    valuesChanged = pyqtSignal(int, int)      # intoxication, sober
    statusChanged = pyqtSignal(str)           # status name
    outfitChanged = pyqtSignal(str)           # outfit name
    hiddenChanged = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        algo = config.character.global_algorithm
        self._intox = algo.get("initialIntoxication", 0)
        self._sober = algo.get("initialSober", 100)
        self._status = "清醒"
        self.current_outfit = config.character.costume.get("default", "衬衫")
        self.current_outfit_image = self._pick_outfit_image(self.current_outfit)
        self.current_drink = None
        self.drinks_count = 0
        self.drinks_day = self._today_key()
        self.hidden = False
        self.last_interaction = time.time()
        self._load_persist()
        self._ensure_today_drinks()
        self._clamp_values()
        self._recompute_status(emit=False)

    # ---------- 持久化 ----------
    def _load_persist(self):
        try:
            if os.path.exists(STATE_PATH):
                import json
                with open(STATE_PATH, "r", encoding="utf-8") as f:
                    d = json.load(f)
                self._intox = d.get("intoxication", self._intox)
                self._sober = d.get("sober", self._sober)
                self.drinks_count = d.get("drinks_count", 0)
                self.drinks_day = d.get("drinks_day", self.drinks_day)
                self.current_drink = d.get("current_drink")
        except Exception:  # noqa: BLE001
            pass

    def _today_key(self):
        return date.today().isoformat()

    def _ensure_today_drinks(self):
        today = self._today_key()
        if self.drinks_day != today:
            self.drinks_day = today
            self.drinks_count = 0
            self.current_drink = None

    def _clamp_values(self):
        self._intox = max(1, min(100, int(self._intox)))
        self._sober = max(1, min(100, int(self._sober)))

    def _save_persist(self):
        try:
            self._ensure_today_drinks()
            import json
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "intoxication": self._intox,
                    "sober": self._sober,
                    "drinks_count": self.drinks_count,
                    "drinks_day": self.drinks_day,
                    "current_drink": self.current_drink,
                }, f, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass

    # ---------- 属性 ----------
    @property
    def intoxication(self):
        return self._intox

    @property
    def sober(self):
        return self._sober

    @property
    def status(self):
        return self._status

    # ---------- 数值运算 ----------
    def drink(self, item_cfg: dict):
        self._ensure_today_drinks()
        add = item_cfg.get("intoxicationAdd", 0)
        sub = item_cfg.get("soberSub", 0)
        self._intox = min(100, self._intox + add)
        self._sober = max(1, self._sober - sub)
        if item_cfg.get("name"):
            self.current_drink = item_cfg["name"]
            self.drinks_count += 1
        self._after_change()

    def decay(self):
        """按配置周期衰减：微醺-2，清醒+1。"""
        self._intox = max(1, self._intox - config.character.global_algorithm
                          .get("timeDecay", {}).get("intoxicationDecay", 2))
        self._sober = min(100, self._sober + config.character.global_algorithm
                          .get("timeDecay", {}).get("soberRecover", 1))
        self._after_change()

    def _after_change(self):
        self._ensure_today_drinks()
        self._clamp_values()
        self._save_persist()
        self._recompute_status()
        self.valuesChanged.emit(self._intox, self._sober)

    def _recompute_status(self, emit: bool = True):
        old = self._status
        for s in config.character.status_config:
            lo = s.get("min", 0)
            hi = s.get("max", 100)
            if lo <= self._intox <= hi:
                self._status = s.get("status", "清醒")
                break
        if emit and old != self._status:
            self.statusChanged.emit(self._status)

    def status_lines(self) -> list:
        for s in config.character.status_config:
            if s.get("status") == self._status:
                return s.get("lines", [])
        return []

    # ---------- 服装 ----------
    def set_outfit(self, name: str):
        self.current_outfit = name
        self.current_outfit_image = self._pick_outfit_image(name)
        config.settings.set("costume", name)
        self.outfitChanged.emit(name)

    def _pick_outfit_image(self, name: str):
        try:
            from app.core import assets
            choices = assets.get_costume_images(name)
            return random.choice(choices) if choices else None
        except Exception:  # noqa: BLE001
            return None

    # ---------- 闲置 ----------
    def mark_interaction(self):
        self.last_interaction = time.time()

    def is_idle(self, seconds: int) -> bool:
        return (time.time() - self.last_interaction) >= seconds

    def idle_minutes(self) -> float:
        return (time.time() - self.last_interaction) / 60.0

    # ---------- 隐身 ----------
    def set_hidden(self, hidden: bool):
        if self.hidden != hidden:
            self.hidden = hidden
            self.hiddenChanged.emit(hidden)


# 全局单例
state = AppState()
