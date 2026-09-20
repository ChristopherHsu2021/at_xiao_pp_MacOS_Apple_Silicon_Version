"""通用玻璃窗口基类（无边框圆角卡片 + 自定义标题栏 + 可拖拽）。

所有工具窗口（待办/闹钟/计时/设置/场景）继承此基类，保证视觉风格统一。
"""

from PyQt6.QtCore import Qt, QPoint, QPointF, QRectF, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QGraphicsDropShadowEffect, QApplication, QTextEdit, QLineEdit,
)
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

from app.core import assets
import sys

from app.core.i18n import tr
from app.ui.style import GLASS_STYLE, COLOR
from app.ui.mac_window import apply_stage_exempt, make_resizable
from app.ui.screen_fit import scale_qss, s

# SetWindowPos 标志：NOSIZE(0x1) | NOMOVE(0x2) | NOACTIVATE(0x10) | SHOWWINDOW(0x40)
_SWP_BASE = 0x0001 | 0x0002 | 0x0010 | 0x0040
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2


def popup_open():
    """当前是否有本程序的弹出窗口（下拉列表 / 日历 / 右键菜单 / 模态对话框）打开。

    这些弹出窗口都是独立顶层窗口：若此时再对卡片窗口「重申置顶 + 抢激活」，
    弹出窗口会因层级被压低而**被卡片盖住**，或直接失去激活而**立刻关闭**（看起来像闪退）。
    """
    try:
        return (QApplication.activePopupWidget() is not None
                or QApplication.activeModalWidget() is not None)
    except RuntimeError:
        return False


def _mac_set_window_level(widget, floating):
    """macOS 专属：置顶→NSFloatingWindowLevel；让路→NSNormalWindowLevel（保持可见、不隐藏）。

    与 Windows 的 SetWindowPos(TOPMOST / NOTOPMOST) 在跨平台语义上对等：
    - floating=True  等效于「所有软件顶层不被遮挡」；
    - floating=False 等效于「点击其它软件就让路」，窗口降到普通层级但**不隐藏**。
    其它平台（无 PyObjC）直接跳过，由各自原生分支处理。
    """
    if sys.platform != "darwin":
        return
    try:
        import objc
        from ctypes import c_void_p
        from AppKit import NSWindow, NSFloatingWindowLevel, NSNormalWindowLevel
        nsview = objc.objc_object(c_void_p=int(widget.winId()))
        nswindow = nsview.window()
        if nswindow is not None:
            nswindow.setLevel_(NSFloatingWindowLevel if floating else NSNormalWindowLevel)
    except Exception:  # noqa: BLE001
        # PyObjC 缺失 / 环境差异不应影响主流程
        pass


def keep_on_top(widget, bring_to_front=False, activate=False):
    """重申窗口置顶；定时调用不抢焦点，避免盖住用户正在使用的本软件页面。

    注意：只有标志确实缺失时才调用 setWindowFlag —— 该调用会**销毁并重建原生窗口句柄**，
    若此时正有下拉列表/日历弹窗打开，弹窗会被连带销毁（表现为下拉闪退、日历被遮挡）。
    """
    if widget is None:
        return
    try:
        if not (widget.windowFlags() & Qt.WindowType.WindowStaysOnTopHint):
            widget.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        if bring_to_front and widget.isVisible():
            widget.raise_()
            if activate:
                widget.activateWindow()
    except RuntimeError:
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        flags = _SWP_BASE
        if not activate:
            flags |= 0x0010
        ctypes.windll.user32.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, 0, 0, flags)
    except Exception:  # noqa: BLE001
        pass
    # macOS：置顶到浮层层级（与 Windows 的 TOPMOST 对等）
    _mac_set_window_level(widget, True)


def promote_popup_topmost():
    """把当前打开的弹出窗口（下拉列表 / 日历）顶到 TopMost 层最上方。

    卡片窗口本身常驻 TopMost，其弹出列表同样位于 TopMost 层但层级更低，
    会被卡片压住（即「年月日框被页面遮挡」）。这里在弹窗显示后立刻提升其 Z 序。
    """
    try:
        popup = QApplication.activePopupWidget()
    except RuntimeError:
        return
    if popup is None:
        return
    try:
        import ctypes
        hwnd = int(popup.winId())
        ctypes.windll.user32.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, 0, 0, _SWP_BASE)
    except Exception:  # noqa: BLE001
        pass


def promote_popup_soon():
    """在弹出窗口真正显示之后再提权（showPopup 内同步调用时窗口尚未创建）。"""
    QTimer.singleShot(0, promote_popup_topmost)


def release_topmost(widget):
    """将窗口从系统 TopMost 层释放，避免遮挡其他软件的对话框。"""
    if widget is None:
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        flags = _SWP_BASE
        ctypes.windll.user32.SetWindowPos(hwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, flags)
    except Exception:  # noqa: BLE001
        pass
    # macOS：降到普通层级（让路、不隐藏），与 Windows 的 NOTOPMOST 对等
    _mac_set_window_level(widget, False)


class PeekCard(QWidget):
    """圆角实底卡片，右下角沿底边露出与播放器一致的人物背景。"""

    def __init__(self, parent=None, radius=20, opacity=0.70, scale=1.18):
        super().__init__(parent)
        self.radius = radius
        self.opacity = opacity
        self.scale = scale
        self.bubu = QPixmap(assets.find_image("bubu_cutout") or "")
        # 添加/编辑页：卜卜以「底面 1/3 为半径的 1/4 圆区域」在右下角展示，
        # 大小随窗口缩放（quarter_radius = 卡片宽 / 3）；列表页 add_mode=False 保持原样。
        self.add_mode = False
        self.quarter_radius = 0.0
        # 添加/编辑页：卜卜整体沿 45° 左上平移，使嘴巴与眼睛完整露出（不被卡片右下角裁切），
        # 同时仍保持「底面 1/3 半径的 1/4 圆」贴角露出感（系数越大越往内、越小越贴角）。
        # 0.88 由实测反推：不透明外框相对锚点的最远距离 ≈ 0.85 * quarter_radius，
        # 故 >=0.85 即可让整只卜卜（含叶子/嘴巴/眼睛）完整落在卡片内，与窗口尺寸无关。
        self._face_shift_factor = 0.88

    def set_add_mode(self, on: bool):
        """切换添加/编辑页（True）与列表页（False）。列表页卜卜零改动。"""
        on = bool(on)
        if self.add_mode != on:
            self.add_mode = on
            self.update()

    def set_quarter_radius(self, r: float):
        """设置 1/4 圆区域半径（= 卡片宽 / 3），窗口缩放时同步更新。"""
        r = float(r)
        if abs(r - self.quarter_radius) > 0.5:
            self.quarter_radius = r
            self.update()

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
        if self.add_mode and self.quarter_radius > 0:
            # 添加/编辑页：卜卜锚定右下角附近，按 quarter_radius/200 缩放（随窗口），
            # 并整体沿 45° 左上平移 _face_shift_factor*quarter_radius，使嘴巴/眼睛完整露出；
            # 叶子可自然溢出 1/4 圆（不额外裁切叶部）。
            shift = self.quarter_radius * self._face_shift_factor
            self._paint_bubu_peek(
                painter,
                mouth_pos=QPointF(self.width() - shift, self.height() - shift),
                scale=self.quarter_radius / 200.0,
                mouth_in_source=QPointF(self.bubu.width() * 0.487, self.bubu.height() * 0.583),
            )
        else:
            # 列表页：保持原始小图 peek（scale=1.08），零 UI 改动。
            self._paint_bubu_peek(
                painter,
                mouth_pos=QPointF(self.width() - 18, self.height() - 24),
                scale=self.scale,
                mouth_in_source=QPointF(self.bubu.width() * 0.52, self.bubu.height() * 0.62),
            )

    def _paint_bubu_peek(self, painter, mouth_pos, scale, mouth_in_source):
        # mouth_in_source：源图中「嘴巴中心」的归一化坐标（由素材实测反推）。
        # 添加/编辑页用真实中心 (0.487, 0.583)，列表页保持原值 (0.52, 0.62) 零改动。
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
        self.setFixedSize(s(320), s(190))
        root = QVBoxLayout(self)
        root.setContentsMargins(s(6), s(6), s(6), s(6))
        card = QWidget(self)
        card.setStyleSheet(scale_qss(
            "QWidget{background:#fffaf5;border:1px solid rgba(255,255,255,0.70);border-radius:18px;}"
            "QLabel#noticeTitle{color:#3d2b1f;font-size:16px;font-weight:800;}"
            "QLabel#noticeText{color:#8d7a68;font-size:12px;font-weight:600;}"
            "QPushButton#noticeBtn{background:#ff7613;border:1.5px solid #ff7613;border-radius:16px;color:#fff;font-size:12px;font-weight:700;padding:0 14px;}"
            "QPushButton#noticeBtn:hover{background:#ffa940;border-color:#ffa940;}"
        ))
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(s(24))
        shadow.setOffset(0, s(8))
        shadow.setColor(QColor(180, 120, 50, 32))
        card.setGraphicsEffect(shadow)
        root.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(s(22), s(20), s(22), s(18))
        lay.setSpacing(s(12))
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
        ok.setFixedSize(s(72), s(34))
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
        # macOS：无边框窗口追加 NSResizableWindowMask，可由用户从边缘自由缩放。
        # 最小尺寸 = 默认尺寸（用户要求：只能从默认大小放大，不能缩小到默认之下）
        self.setMinimumSize(width, height)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.container = QWidget(self)
        self.container.setStyleSheet(GLASS_STYLE)
        self.container.setObjectName("GlassWindow")
        self.container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(self.container)
        shadow.setBlurRadius(s(22))
        shadow.setOffset(0, s(8))
        shadow.setColor(QColor(180, 120, 50, 42))
        self.container.setGraphicsEffect(shadow)
        root.addWidget(self.container)

        croot = QVBoxLayout(self.container)
        croot.setContentsMargins(0, 0, 0, 0)
        croot.setSpacing(0)

        # 标题栏
        bar = QWidget()
        bar.setObjectName("window-bar")
        bar.setFixedHeight(s(46))
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(s(18), 0, s(12), 0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("window-title")
        bl.addWidget(self.title_label)
        bl.addStretch(1)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(s(28), s(28))
        close_btn.setStyleSheet(scale_qss(
            "QPushButton{background:transparent;border:none;color:#a08e7a;font-size:14px;}"
            "QPushButton:hover{color:#e53935;background:rgba(229,57,53,0.08);border-radius:8px;}"
        ))
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

    def showEvent(self, e):  # noqa: N802
        # macOS 专属：把本窗口登记为「不受台前调度影响」——切到其它 App /
        # 舞台重排时不会被收进侧边条。只改窗口行为、**不动层级**，
        # 现有的置顶 / 让路（keep_on_top / release_topmost）语义保持不变。
        super().showEvent(e)
        apply_stage_exempt(self, tag=type(self).__name__)
        # macOS：无边框窗口追加 NSResizableWindowMask，可由用户从边缘自由缩放
        # （Windows 端该调用无效，沿用既有 ResizeGrip 自绘握把）
        make_resizable(self, tag=type(self).__name__)

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


UPLOAD_QSS = scale_qss("""
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
""")


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
        self.setFixedSize(s(300), s(158))

        root = QVBoxLayout(self)
        root.setContentsMargins(s(6), s(6), s(6), s(6))
        root.setSpacing(0)

        self.card = PeekCard(self, scale=0.9)
        self.card.setObjectName("UploadCard")
        self.card.setStyleSheet(UPLOAD_QSS)
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(s(22))
        shadow.setOffset(0, s(8))
        shadow.setColor(QColor(180, 120, 50, 40))
        self.card.setGraphicsEffect(shadow)
        root.addWidget(self.card)

        card_lay = QVBoxLayout(self.card)
        # 底部留白避开 bubu 探头（右下角）
        card_lay.setContentsMargins(s(20), s(18), s(20), s(34))
        card_lay.setSpacing(s(14))

        self.title_l = QLabel("")
        self.title_l.setObjectName("UploadTitle")
        self.title_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_l.setWordWrap(True)
        card_lay.addWidget(self.title_l)
        card_lay.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(s(12))
        btn_row.addStretch(1)
        self.yes_b = QPushButton(tr("是"))
        self.yes_b.setObjectName("uploadYes")
        self.yes_b.setFixedSize(s(84), s(36))
        self.yes_b.clicked.connect(lambda: self.accepted.emit())
        self.no_b = QPushButton(tr("否"))
        self.no_b.setObjectName("uploadNo")
        self.no_b.setFixedSize(s(84), s(36))
        self.no_b.clicked.connect(lambda: self.rejected.emit())
        btn_row.addWidget(self.yes_b)
        btn_row.addWidget(self.no_b)
        btn_row.addStretch(1)
        card_lay.addLayout(btn_row)

    def configure_confirm(self, title: str, yes_text: str = "是", no_text: str = "否"):
        self.title_l.setText(title)
        self.yes_b.setText(tr(yes_text))
        self.yes_b.setVisible(True)
        self.no_b.setVisible(True)
        self.no_b.setText(tr(no_text))

    def configure_info(self, title: str, btn_text: str = "好嘟"):
        self.title_l.setText(title)
        self.yes_b.setText(tr(btn_text))
        self.yes_b.setVisible(True)
        self.no_b.setVisible(False)

    def show_near(self, pos: QPoint):
        self.move(pos)
        self.show()
        self.raise_()


# ==================== 自绘右键菜单（编辑动作块，全局复用） ====================
# 严格对齐参考 HTML 的 #contextMenu / .context-menu-item：
# 白底、圆角 8px、投影 0 4px 16px rgba(0,0,0,0.18)，item 内边距 8px 14px、hover 灰 #f3f4f6。
#
# 为什么不用 QMenu：QMenu 自带原生图标与系统字体度量，无法复刻 HTML 的排版（左文案 + 右灰色
# 快捷键），且颜色随系统主题漂移；而 QTextEdit 出厂会弹 Qt 原生英文菜单（Undo/Redo/...），
# 与「软件语言设置」不一致。故统一用本类自绘。
CTX_MENU_CARD_QSS = scale_qss(
    "QWidget#ctxMenuCard{background:#ffffff;border:1px solid #e5e7eb;"
    "border-radius:8px;}"
)
CTX_MENU_ITEM_QSS = scale_qss(
    "QPushButton#ctxMenuItem{background:transparent;border:none;text-align:left;"
    "padding:0;}"
    "QPushButton#ctxMenuItem:hover{background:#f3f4f6;}"
)
CTX_MENU_TEXT_QSS = scale_qss("background:transparent;font-size:13px;color:#3d2b1f;")
CTX_MENU_SHORTCUT_QSS = scale_qss("background:transparent;font-size:12px;color:#a3a3a3;")

# 原生编辑动作 + 快捷键提示（文案走 i18n，跟随软件「语言」设置）
EDIT_MENU_ITEMS = ("撤销", "重做", None, "剪切", "复制", "粘贴", "删除", None, "全选")
# 快捷键提示（显示用）：macOS 统一用 ⌘（Cmd）；删除键用 ⌫。
EDIT_MENU_SHORTCUTS = {
    "撤销": "⌘Z", "重做": "⌘Y",
    "剪切": "⌘X", "复制": "⌘C", "粘贴": "⌘V",
    "删除": "⌫", "全选": "⌘A",
}


class EditContextMenu(QWidget):
    """自绘文本编辑右键菜单（顶层 Qt.Popup，避免被窗口边界裁切）。

    - 默认只含「原生编辑动作块」：撤销/重做/剪切/复制/粘贴/删除/全选（含快捷键提示），
      文案全部走 i18n，与软件语言设置一致。
    - 作为顶层弹出层呈现：可超出父窗显示，且「点击外部 / Esc 关闭」由 Qt.Popup 原生保证，
      无需再装全局事件过滤器。半透明背景 + 外留白让 HTML 投影（box-shadow）可见。
    - 子类可覆写 `_build_extra(layout)` 追加自定义项
      （如便签菜单的「复制任务 / 清空内容 / 便签背景」）。
    """

    CARD_WIDTH = s(206)     # 设计稿卡片宽
    PAD = s(14)             # 投影留白（四周）

    def __init__(self, parent=None, target=None):
        super().__init__(parent)
        # 右键落在哪个输入控件，编辑动作就作用于哪个（QLineEdit / QTextEdit）
        self.target = target
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlags(Qt.WindowType.Popup
                            | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(self.CARD_WIDTH + 2 * self.PAD)

        root = QVBoxLayout(self)
        root.setContentsMargins(self.PAD, self.PAD, self.PAD, self.PAD)   # 投影留白
        card = QWidget(self)
        card.setObjectName("ctxMenuCard")
        card.setStyleSheet(CTX_MENU_CARD_QSS)
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(s(16))
        shadow.setOffset(0, s(4))
        shadow.setColor(QColor(0, 0, 0, 46))        # rgba(0,0,0,0.18)
        card.setGraphicsEffect(shadow)
        root.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(s(4), s(4), s(4), s(4))
        lay.setSpacing(s(2))

        # 1) 原生编辑动作块（保留系统右键菜单的功能，文案走 i18n）
        for item in EDIT_MENU_ITEMS:
            if item is None:
                lay.addWidget(self._separator())
                continue
            lay.addWidget(self._row(tr(item), EDIT_MENU_SHORTCUTS.get(item, ""),
                                    lambda z=item: self._do_edit(z)))

        # 2) 子类扩展项（默认无）
        self._build_extra(lay)

    # ---------- 子类扩展点 ----------
    def _build_extra(self, lay):
        """追加自定义菜单项（默认无）。子类实现时自行决定是否先加分隔线。"""
        return

    # ---------- 行 / 分隔线 ----------
    def _row(self, text, shortcut, cb):
        """一行菜单项：左侧文案，右侧灰色快捷键提示（QPushButton 承载 hover 底色）。"""
        b = QPushButton()
        b.setObjectName("ctxMenuItem")
        b.setFixedHeight(s(34))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(CTX_MENU_ITEM_QSS)
        rl = QHBoxLayout(b)
        rl.setContentsMargins(s(14), 0, s(14), 0)
        rl.setSpacing(s(8))
        t = QLabel(text)
        t.setStyleSheet(CTX_MENU_TEXT_QSS)
        t.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        rl.addWidget(t)
        rl.addStretch(1)
        if shortcut:
            s = QLabel(shortcut)
            s.setStyleSheet(CTX_MENU_SHORTCUT_QSS)
            s.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            rl.addWidget(s)
        b.clicked.connect(lambda _checked=False, c=cb: self._trigger(c))
        return b

    @staticmethod
    def _separator():
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(s(8), s(3), s(8), s(3))
        wl.setSpacing(0)
        line = QWidget()
        line.setFixedHeight(s(1))
        line.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        line.setStyleSheet("background:#ececec;")
        wl.addWidget(line)
        return wrap

    # ---------- 原生编辑动作（作用于右键所在的那个输入控件） ----------
    def _do_edit(self, act):
        t = self.target
        if t is None:
            return
        try:
            if act == "撤销":
                t.undo()
            elif act == "重做":
                t.redo()
            elif act == "剪切":
                t.cut()
            elif act == "复制":
                t.copy()
            elif act == "粘贴":
                t.paste()
            elif act == "全选":
                t.selectAll()
            elif act == "删除":
                if isinstance(t, QTextEdit):
                    cur = t.textCursor()
                    cur.removeSelectedText()
                    t.setTextCursor(cur)
                elif isinstance(t, QLineEdit):
                    t.del_()          # 删除选区（或光标后一个字符）
            t.setFocus()
        except RuntimeError:
            pass

    def _trigger(self, cb):
        """关闭菜单后异步执行动作（先 close 再回调，避免动作里弹窗抢焦点）。

        坑（便签菜单点「复制任务/清空内容」崩溃的根因）：本类带 WA_DeleteOnClose，
        close() 之后 C++ 对象立即销毁、Python wrapper 变成悬空壳。若回调链里再次
        走到本方法（例如子类把回调又包了一层 _trigger），第二次 close() 就会抛
        RuntimeError: wrapped C/C++ object ... has been deleted。
        故此处捕获该异常：对象已销毁时跳过 close，动作照常异步执行（cb 通常指向
        业务窗口的方法，与菜单生命周期无关，执行是安全的）。
        """
        try:
            self.close()
        except RuntimeError:
            pass
        QTimer.singleShot(0, cb)

    def show_at(self, global_pos):
        """顶层弹出层：定位到鼠标处并夹紧到屏幕可用区域（不受父窗边界裁切）。"""
        parent = self.parentWidget()
        if parent is not None:
            old = getattr(parent, "_active_action_popup", None)
            if old is not None and old is not self:
                try:
                    old.close()
                except RuntimeError:
                    pass
            parent._active_action_popup = self
            self.destroyed.connect(
                lambda _obj=None, p=parent: setattr(p, "_active_action_popup", None))
        self.adjustSize()
        scr = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        if scr is not None:
            avail = scr.availableGeometry()
            x = max(avail.left(), min(global_pos.x(), avail.right() - self.width()))
            y = max(avail.top(), min(global_pos.y(), avail.bottom() - self.height()))
            self.move(x, y)
        else:
            self.move(global_pos)
        self.show()
        self.raise_()
        return self
