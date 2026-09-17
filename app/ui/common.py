"""通用玻璃窗口基类（无边框圆角卡片 + 自定义标题栏 + 可拖拽）。

所有工具窗口（待办/闹钟/计时/设置/场景）继承此基类，保证视觉风格统一。
"""

import sys

from PyQt6.QtCore import Qt, QPoint, QPointF, QRectF, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

from app.core import assets
from app.core.i18n import tr
from app.ui.style import GLASS_STYLE, COLOR


def keep_on_top(widget, bring_to_front=False, activate=False):
    """重申窗口置顶；定时调用不抢焦点，避免盖住用户正在使用的本软件页面。"""
    if widget is None:
        return
    try:
        widget.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        if bring_to_front and widget.isVisible():
            widget.raise_()
            if activate:
                widget.activateWindow()
    except RuntimeError:
        return
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        flags = 0x0001 | 0x0002 | 0x0010 | 0x0040
        if not activate:
            flags |= 0x0010
        ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, flags)
    except Exception:  # noqa: BLE001
        pass


def release_topmost(widget):
    """将窗口从系统 TopMost 层释放，避免遮挡其他软件的对话框。"""
    if widget is None:
        return
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        flags = 0x0001 | 0x0002 | 0x0010 | 0x0040
        ctypes.windll.user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, flags)
    except Exception:  # noqa: BLE001
        pass


class PeekCard(QWidget):
    """圆角实底卡片，右下角沿底边露出与播放器一致的人物背景。"""

    def __init__(self, parent=None, radius=20, opacity=0.70, scale=1.18):
        super().__init__(parent)
        self.radius = radius
        self.opacity = opacity
        self.scale = scale
        self.bubu = QPixmap(assets.find_image("bubu_cutout") or "")

    def paintEvent(self, e):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rounded = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
        painter.setBrush(QColor("#fffaf5"))
        painter.drawRoundedRect(rounded, self.radius, self.radius)
        if self.bubu.isNull():
            return
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), self.radius, self.radius)
        painter.setClipPath(clip)
        painter.setOpacity(self.opacity)
        self._paint_bubu_peek(
            painter,
            mouth_pos=QPointF(self.width() - 18, self.height() - 24),
            scale=self.scale,
        )

    def _paint_bubu_peek(self, painter, mouth_pos, scale):
        mouth_in_source = QPointF(self.bubu.width() * 0.52, self.bubu.height() * 0.62)
        painter.save()
        painter.translate(mouth_pos)
        painter.rotate(-45)
        painter.scale(scale, scale)
        painter.drawPixmap(QPointF(-mouth_in_source.x(), -mouth_in_source.y()), self.bubu)
        painter.restore()


class NoticeDialog(QDialog):
    def __init__(self, parent, title: str, message: str):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedSize(320, 190)
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        card = QWidget(self)
        card.setStyleSheet(
            "QWidget{background:#fffaf5;border:1px solid rgba(255,255,255,0.70);border-radius:18px;}"
            "QLabel#noticeTitle{color:#3d2b1f;font-size:16px;font-weight:800;}"
            "QLabel#noticeText{color:#8d7a68;font-size:12px;font-weight:600;}"
            "QPushButton#noticeBtn{background:#ff7613;border:1.5px solid #ff7613;border-radius:16px;color:#fff;font-size:12px;font-weight:700;padding:0 14px;}"
            "QPushButton#noticeBtn:hover{background:#ffa940;border-color:#ffa940;}"
        )
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(180, 120, 50, 32))
        card.setGraphicsEffect(shadow)
        root.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        title_l = QLabel(title)
        title_l.setObjectName("noticeTitle")
        title_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_l = QLabel(message)
        msg_l.setObjectName("noticeText")
        msg_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_l.setWordWrap(True)
        lay.addWidget(title_l)
        lay.addWidget(msg_l, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton(tr("确定"))
        ok.setObjectName("noticeBtn")
        ok.setFixedSize(72, 34)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        row.addStretch(1)
        lay.addLayout(row)


class GlassWindow(QDialog):
    def __init__(self, ctx, title: str, width: int = 420, height: int = 560):
        super().__init__()
        self.ctx = ctx
        self._drag_pos = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(width, height)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.container = QWidget(self)
        self.container.setStyleSheet(GLASS_STYLE)
        self.container.setObjectName("GlassWindow")
        self.container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(self.container)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(180, 120, 50, 42))
        self.container.setGraphicsEffect(shadow)
        root.addWidget(self.container)

        croot = QVBoxLayout(self.container)
        croot.setContentsMargins(0, 0, 0, 0)
        croot.setSpacing(0)

        # 标题栏
        bar = QWidget()
        bar.setObjectName("window-bar")
        bar.setFixedHeight(46)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(18, 0, 12, 0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("window-title")
        bl.addWidget(self.title_label)
        bl.addStretch(1)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;color:#a08e7a;font-size:14px;}"
            "QPushButton:hover{color:#e53935;background:rgba(229,57,53,0.08);border-radius:8px;}"
        )
        close_btn.clicked.connect(self.close)
        bl.addWidget(close_btn)
        croot.addWidget(bar)

        # 主体
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        croot.addWidget(self.body, 1)

        bar.mousePressEvent = self._bar_press
        bar.mouseMoveEvent = self._bar_move

    def set_title(self, title: str):
        self.title_label.setText(title)

    def set_body_widget(self, widget: QWidget):
        old = self.body_layout.takeAt(0)
        if old is not None:
            w = old.widget()
            if w:
                w.deleteLater()
        self.body_layout.addWidget(widget)

    def _bar_press(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.pos()

    def _bar_move(self, e):
        if self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def closeEvent(self, e):  # noqa: N802
        if hasattr(self, "on_close"):
            self.on_close()
        super().closeEvent(e)


UPLOAD_QSS = """
QWidget#UploadCard {
    background: #fffaf5;
    border: 1px solid rgba(255,255,255,0.60);
    border-radius: 20px;
}
QLabel#UploadTitle {
    color: #3d2b1f;
    font-size: 15px;
    font-weight: 800;
    background: transparent;
}
QPushButton#uploadYes {
    background: #f97510;
    border: none;
    border-radius: 16px;
    color: #fff;
    font-size: 13px;
    font-weight: 800;
}
QPushButton#uploadYes:hover { background: #ffa940; }
QPushButton#uploadNo {
    background: rgba(160,142,122,0.10);
    border: 1.5px solid rgba(249,117,16,0.12);
    border-radius: 16px;
    color: #a08e7a;
    font-size: 13px;
    font-weight: 800;
}
QPushButton#uploadNo:hover { background: rgba(249,117,16,0.10); color: #f97510; }
"""


class UploadPrompt(QDialog):
    """人物脚下的上传确认对话框（类计时器玻璃卡片风格，与软件 UI 一致）。

    两种形态：
    - confirm：标题 + 『是/否』两个按钮（用于音频文件确认上传）
    - info：单行提示 + 一个『好嘟』按钮（用于上传成功 / 不支持该文件）
    """

    accepted = pyqtSignal()
    rejected = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(300, 158)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(0)

        self.card = PeekCard(self, scale=0.9)
        self.card.setObjectName("UploadCard")
        self.card.setStyleSheet(UPLOAD_QSS)
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(180, 120, 50, 40))
        self.card.setGraphicsEffect(shadow)
        root.addWidget(self.card)

        card_lay = QVBoxLayout(self.card)
        # 底部留白避开 bubu 探头（右下角）
        card_lay.setContentsMargins(20, 18, 20, 34)
        card_lay.setSpacing(14)

        self.title_l = QLabel("")
        self.title_l.setObjectName("UploadTitle")
        self.title_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_l.setWordWrap(True)
        card_lay.addWidget(self.title_l)
        card_lay.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch(1)
        self.yes_b = QPushButton("是")
        self.yes_b.setObjectName("uploadYes")
        self.yes_b.setFixedSize(84, 36)
        self.yes_b.clicked.connect(lambda: self.accepted.emit())
        self.no_b = QPushButton("否")
        self.no_b.setObjectName("uploadNo")
        self.no_b.setFixedSize(84, 36)
        self.no_b.clicked.connect(lambda: self.rejected.emit())
        btn_row.addWidget(self.yes_b)
        btn_row.addWidget(self.no_b)
        btn_row.addStretch(1)
        card_lay.addLayout(btn_row)

    def configure_confirm(self, title: str, yes_text: str = "是", no_text: str = "否"):
        self.title_l.setText(title)
        self.yes_b.setText(yes_text)
        self.yes_b.setVisible(True)
        self.no_b.setVisible(True)
        self.no_b.setText(no_text)

    def configure_info(self, title: str, btn_text: str = "好嘟"):
        self.title_l.setText(title)
        self.yes_b.setText(btn_text)
        self.yes_b.setVisible(True)
        self.no_b.setVisible(False)

    def show_near(self, pos: QPoint):
        self.move(pos)
        self.show()
        self.raise_()
