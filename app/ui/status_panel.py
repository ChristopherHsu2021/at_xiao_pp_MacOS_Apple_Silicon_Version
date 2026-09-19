"""饮品状态面板：微醺值 / 清醒值 / 人物状态 / 系统时间。

作为宠物窗的子控件，喝酒、喝茶、喝饮料时显示并实时刷新。
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QWidget, QLabel, QHBoxLayout, QVBoxLayout, QSizePolicy

from app.core import config
from app.core.state import state
from app.core.i18n import tr


class Bar(QWidget):
    """横向进度条（圆角轨道 + 填充）。"""

    def __init__(self, color: str, width: int = 314, height: int = 8):
        super().__init__()
        self._w = width
        self._h = height
        self.setFixedSize(width, height)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.track = QWidget(self)
        self.track.setGeometry(0, 0, width, height)
        self.track.setStyleSheet(
            f"background: rgba(249,117,16,0.12); border-radius: {height // 2}px;"
        )
        self.fill = QWidget(self)
        self.fill.setGeometry(0, 0, width, height)
        self.fill.setStyleSheet(
            f"background: {color}; border-radius: {height // 2}px;"
        )

    def set_value(self, pct: int):
        pct = max(1, min(100, pct))
        self.fill.setFixedWidth(int(pct / 100.0 * self._w))


class StatusPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DrinkStatusPanel")
        self.setFixedSize(358, 215)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        state.valuesChanged.connect(self._on_values)
        self._on_values(state.intoxication, state.sober)
        self._tick()

    def _build(self):
        self.setStyleSheet(
            "QWidget#DrinkStatusPanel {"
            " background: #fff8ee; border: 1px solid rgba(255,255,255,0.72);"
            " border-radius: 20px;"
            "}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(21, 21, 22, 22)
        root.setSpacing(15)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.icon = QLabel("🍺")
        self.icon.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #f97510, stop:1 #ffa940);"
            " border: none; border-radius: 10px; color: #fff; font-size: 18px;"
        )
        self.icon.setFixedSize(41, 41)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drink_name = QLabel(tr("伏特加"))
        self.drink_name.setStyleSheet("font-size: 14px; font-weight: 800; color: #3d2b1f;")
        self.drink_sub = QLabel("")
        self.drink_sub.setStyleSheet("font-size: 11px; color: #a08e7a;")
        meta = QVBoxLayout()
        meta.setSpacing(1)
        meta.addWidget(self.drink_name)
        meta.addWidget(self.drink_sub)
        header.addWidget(self.icon)
        header.addLayout(meta)
        header.addStretch(1)
        self.time_label = QLabel("00:00:00")
        self.time_label.setStyleSheet(
            "font-size: 14px; font-weight: 800; color: #ff7613;"
            " font-family: Consolas, 'Cascadia Code', monospace;"
        )
        header.addWidget(self.time_label)
        root.addLayout(header)

        self.tipsy_bar = Bar("#ff7a1a", width=314, height=8)
        root.addLayout(self._row(tr("微醺值"), self.tipsy_bar, "tipsy_val"))
        self.sober_bar = Bar("#64bb6a", width=314, height=8)
        root.addLayout(self._row(tr("清醒值"), self.sober_bar, "sober_val"))

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        self.status_pill = QLabel(tr("清醒"))
        self.status_pill.setStyleSheet(
            "background: rgba(249,117,16,0.08); border: 1px solid rgba(249,117,16,0.28);"
            " color: #ff7613; font-size: 11px; font-weight: 800; padding: 6px 13px; border-radius: 13px;"
        )
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(
            "color: #9a8067; font-size: 11px; font-weight: 500;"
        )
        bottom.addWidget(self.status_pill)
        bottom.addStretch(1)
        bottom.addWidget(self.count_label)
        root.addLayout(bottom)

    def _row(self, label_text, bar, val_attr):
        v = QVBoxLayout()
        v.setSpacing(6)
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(label_text)
        lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lab.setStyleSheet(
            "font-size: 11px; color: #6b5744; font-weight: 500;"
        )
        val = QLabel("0%")
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        val.setStyleSheet(
            "font-size: 11px; font-weight: 800; color: #3d2b1f;"
        )
        setattr(self, val_attr, val)
        h.setSpacing(0)
        h.addWidget(lab)
        h.addStretch(1)
        h.addWidget(val)
        v.addLayout(h)
        v.addWidget(bar)
        return v

    def _tick(self):
        from datetime import datetime
        self.time_label.setText(datetime.now().strftime("%H:%M:%S"))

    def _on_values(self, intox, sober):
        intox = max(1, min(100, int(intox)))
        sober = max(1, min(100, int(sober)))
        self.tipsy_bar.set_value(intox)
        self.sober_bar.set_value(sober)
        self.tipsy_val.setText(f"{intox}%")
        self.sober_val.setText(f"{sober}%")
        self.status_pill.setText(f"● {self._status_label()}")
        if state.current_drink:
            self.drink_name.setText(state.current_drink)
            self.drink_sub.setText(self._drink_subtitle(state.current_drink))
            self.count_label.setText(tr("今日已饮用 {n} 杯").format(n=state.drinks_count))
        else:
            self.drink_name.setText(tr("AT小PP"))
            self.drink_sub.setText("")
            self.count_label.setText("")

    def _status_label(self):
        if state.status == "清醒":
            return tr("清醒")
        if state.status.endswith("中"):
            return state.status
        return f"{state.status}中"

    def _drink_subtitle(self, drink_name: str):
        abv = {
            "伏特加": "Vodka · 40% ABV",
            "威士忌": "Whisky · 40% ABV",
            "二锅头": "Erguotou · 52% ABV",
            "米酒": "Rice Wine · 12% ABV",
            "黄酒": "Huangjiu · 14% ABV",
            "白兰地": "Brandy · 40% ABV",
            "金酒": "Gin · 40% ABV",
        }
        if drink_name in abv:
            return abv[drink_name]
        for group in config.character.drinks.get("categoryList", []):
            if any(item.get("name") == drink_name for item in group.get("items", [])):
                return f"{group.get('category', '饮品')} · {drink_name}"
        return drink_name
