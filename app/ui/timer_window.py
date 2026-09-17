"""计时器窗口：待机（时:分:秒输入 + 启动）/ 运行（倒计时 + 总时长 + 暂停/取消）。"""

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QIntValidator, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog, QWidget, QLabel, QPushButton, QLineEdit, QHBoxLayout, QVBoxLayout,
    QStackedWidget, QGraphicsDropShadowEffect,
)

from app.core import config
from app.core.voice import say
from app.core.i18n import tr
from app.ui.common import PeekCard


TIMER_QSS = """
QWidget#timerCard {
    background: #fffaf5;
    border: 1px solid rgba(255,255,255,0.60);
    border-radius: 20px;
}
QWidget#timerPage {
    background: transparent;
}
QLabel#timerLabel {
    color: #a08e7a;
    font-size: 14px;
    font-weight: 700;
}
QLabel#timerDisplay {
    color: #f97510;
    font-family: "Cascadia Code", Consolas, monospace;
    font-size: 39px;
    font-weight: 800;
    letter-spacing: 1px;
}
QLabel#timerTotal {
    color: #a08e7a;
    font-size: 13px;
    font-weight: 500;
}
QLabel#timerSep {
    color: #a08e7a;
    font-size: 24px;
    font-weight: 800;
}
QLineEdit#timerInput {
    background: rgba(249,117,16,0.04);
    border: 1.5px solid rgba(249,117,16,0.12);
    border-radius: 7px;
    color: #3d2b1f;
    font-family: "Cascadia Code", Consolas, monospace;
    font-size: 21px;
    font-weight: 800;
    selection-background-color: rgba(249,117,16,0.20);
    selection-color: #3d2b1f;
}
QLineEdit#timerInput:focus {
    background: #fff;
    border-color: #f97510;
}
QPushButton#timerPause {
    background: rgba(255,183,77,0.15);
    border: 1.5px solid rgba(255,183,77,0.44);
    border-radius: 20px;
    color: #f97510;
    font-size: 14px;
    font-weight: 800;
    padding: 0 21px;
}
QPushButton#timerCancel {
    background: rgba(160,142,122,0.10);
    border: 1.5px solid rgba(249,117,16,0.12);
    border-radius: 20px;
    color: #a08e7a;
    font-size: 14px;
    font-weight: 800;
    padding: 0 21px;
}
QPushButton#timerPause:hover,
QPushButton#timerCancel:hover {
    background: rgba(249,117,16,0.10);
    border-color: rgba(249,117,16,0.25);
    color: #f97510;
}
QPushButton#timerBack {
    background: transparent;
    border: none;
    border-radius: 6px;
}
QPushButton#timerBack:hover {
    background: rgba(249,117,16,0.08);
}
"""


class OrangeBarButton(QPushButton):
    def paintEvent(self, e):  # noqa: N802
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#f97510"), 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        y = self.height() // 2
        painter.drawLine(6, y, self.width() - 6, y)


class OrangeCloseButton(QPushButton):
    def paintEvent(self, e):  # noqa: N802
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#f97510"), 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        cx = self.width() // 2
        cy = self.height() // 2
        painter.drawLine(cx - 5, cy - 5, cx + 5, cy + 5)
        painter.drawLine(cx + 5, cy - 5, cx - 5, cy + 5)


class OrangePillButton(QPushButton):
    def __init__(self, text=""):
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QPushButton{background:transparent;border:none;padding:0;margin:0;}")

    def paintEvent(self, e):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor("#ffa940") if self.underMouse() else QColor("#f97510")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(self.rect(), self.height() / 2, self.height() / 2)

        font = QFont(self.font())
        font.setPixelSize(16)
        font.setWeight(QFont.Weight.ExtraBold)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class TimerWindow(QDialog):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.total = 0
        self.remain = 0
        self._drag_pos = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(305, 253)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(0)

        self.card = PeekCard(self, scale=0.92)
        self.card.setObjectName("timerCard")
        self.card.setStyleSheet(TIMER_QSS)
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.card.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 7)
        shadow.setColor(QColor(180, 120, 50, 32))
        self.card.setGraphicsEffect(shadow)
        root.addWidget(self.card)

        self.back_b = OrangeBarButton(self.card)
        self.back_b.setObjectName("timerBack")
        self.back_b.setFixedSize(22, 18)
        self.back_b.setToolTip(tr("最小化"))
        self.back_b.clicked.connect(self.showMinimized)
        self.back_b.raise_()

        self.close_b = OrangeCloseButton(self.card)
        self.close_b.setObjectName("timerBack")
        self.close_b.setFixedSize(22, 18)
        self.close_b.setToolTip(tr("关闭"))
        self.close_b.clicked.connect(self.close)
        self.close_b.raise_()

        card_lay = QVBoxLayout(self.card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.setSpacing(0)

        self.stack = QStackedWidget()
        card_lay.addWidget(self.stack)

        self._build_idle_page()
        self._build_run_page()

        self.back_b.raise_()
        self.close_b.raise_()

        self.card.mousePressEvent = self._drag_press
        self.card.mouseMoveEvent = self._drag_move
        self.card.setFocus()

    def _build_idle_page(self):
        idle = QWidget()
        idle.setObjectName("timerPage")
        il = QVBoxLayout(idle)
        il.setContentsMargins(28, 29, 28, 28)
        il.setSpacing(0)

        self.idle_label = QLabel("⏱️ " + tr("设置时间"))
        self.idle_label.setObjectName("timerLabel")
        self.idle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        il.addWidget(self.idle_label)
        il.addSpacing(21)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(11)
        row.addStretch(1)
        self.h = self._time_input("00")
        self.m = self._time_input("05")
        self.s = self._time_input("00")
        row.addWidget(self.h)
        row.addWidget(self._sep())
        row.addWidget(self.m)
        row.addWidget(self._sep())
        row.addWidget(self.s)
        row.addStretch(1)
        il.addLayout(row)
        il.addSpacing(21)

        start_row = QHBoxLayout()
        start_row.addStretch(1)
        self.start_b = OrangePillButton(tr("启动"))
        self.start_b.setFixedSize(78, 39)
        self.start_b.clicked.connect(self._start)
        start_row.addWidget(self.start_b)
        start_row.addStretch(1)
        il.addLayout(start_row)
        il.addStretch(1)
        self.stack.addWidget(idle)

    def _build_run_page(self):
        run = QWidget()
        run.setObjectName("timerPage")
        rl = QVBoxLayout(run)
        rl.setContentsMargins(24, 29, 24, 27)
        rl.setSpacing(0)

        self.run_label = QLabel("⏱️ " + tr("计时中"))
        self.run_label.setObjectName("timerLabel")
        self.run_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.run_label)
        rl.addSpacing(20)

        self.disp = QLabel("00:05:00")
        self.disp.setObjectName("timerDisplay")
        self.disp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.disp)
        rl.addSpacing(20)

        self.total_l = QLabel(f"{tr('总时长')}：00:05:00")
        self.total_l.setObjectName("timerTotal")
        self.total_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.total_l)
        rl.addSpacing(20)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        self.pause_b = QPushButton(tr("暂停"))
        self.cancel_b = QPushButton(tr("取消"))
        self.pause_b.setObjectName("timerPause")
        self.cancel_b.setObjectName("timerCancel")
        self.pause_b.setFixedSize(81, 41)
        self.cancel_b.setFixedSize(81, 41)
        self.pause_b.clicked.connect(self._toggle_pause)
        self.cancel_b.clicked.connect(self._cancel)
        btn_row.addWidget(self.pause_b)
        btn_row.addWidget(self.cancel_b)
        btn_row.addStretch(1)
        rl.addLayout(btn_row)
        rl.addStretch(1)
        self.stack.addWidget(run)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if hasattr(self, "back_b"):
            self.close_b.move(self.card.width() - self.close_b.width() - 14, 12)
            self.back_b.move(self.close_b.x() - self.back_b.width() - 8, 12)
            self.back_b.raise_()
            self.close_b.raise_()

    def _time_input(self, value):
        edit = QLineEdit(value)
        edit.setObjectName("timerInput")
        edit.setFixedSize(62, 48)
        edit.setMaxLength(2)
        edit.setValidator(QIntValidator(0, 99, edit))
        edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edit.editingFinished.connect(lambda e=edit: self._normalize_input(e))
        return edit

    def _sep(self):
        sep = QLabel(":")
        sep.setObjectName("timerSep")
        sep.setFixedWidth(13)
        sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return sep

    def _normalize_input(self, edit):
        value = int(edit.text() or "0")
        edit.setText(f"{value:02d}")

    def _bounded_value(self, edit, limit):
        value = int(edit.text() or "0")
        value = max(0, min(limit, value))
        edit.setText(f"{value:02d}")
        return value

    def _fmt(self, sec):
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _start(self):
        h = self._bounded_value(self.h, 99)
        m = self._bounded_value(self.m, 59)
        s = self._bounded_value(self.s, 59)
        self.total = h * 3600 + m * 60 + s
        if self.total <= 0:
            return
        self.remain = self.total
        self.disp.setText(self._fmt(self.remain))
        self.total_l.setText(f"{tr('总时长')}：{self._fmt(self.total)}")
        self.pause_b.setText(tr("暂停"))
        self.stack.setCurrentIndex(1)
        self._tick.start(1000)
        say(config.character.system_func.get("timer", {}).get("start", "计时器开始运行捏，好嘟"))

    def _on_tick(self):
        self.remain -= 1
        if self.remain <= 0:
            self.disp.setText("00:00:00")
            self._tick.stop()
            say(config.character.system_func.get("timer", {}).get("end", "时间已经到捏！嘻嘻"))
            self.stack.setCurrentIndex(0)
            return
        self.disp.setText(self._fmt(self.remain))

    def _toggle_pause(self):
        if self._tick.isActive():
            self._tick.stop()
            self.pause_b.setText(tr("启动"))
            say(config.character.system_func.get("timer", {}).get("pause", "计时器暂停捏"))
        else:
            self._tick.start(1000)
            self.pause_b.setText(tr("暂停"))

    def _cancel(self):
        self._tick.stop()
        self.stack.setCurrentIndex(0)

    def retranslate_ui(self):
        self.back_b.setToolTip(tr("最小化"))
        self.close_b.setToolTip(tr("关闭"))
        self.idle_label.setText("⏱️ " + tr("设置时间"))
        self.start_b.setText(tr("启动"))
        self.run_label.setText("⏱️ " + tr("计时中"))
        self.total_l.setText(f"{tr('总时长')}：{self._fmt(self.total or 300)}")
        self.pause_b.setText(tr("暂停") if self._tick.isActive() else tr("启动"))
        self.cancel_b.setText(tr("取消"))

    def _drag_press(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.pos()

    def _drag_move(self, e):
        if self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
            self.close()
            return
        super().keyPressEvent(e)
