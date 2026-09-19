"""待办清单窗口：全选 / 添加 / 删除 / 勾选划线，本地持久化，每周一清理。

页面拆分：
- 列表页（默认视图）：渲染与交互保持原样，仅「点击任务标题文字」改为无行为（右键菜单仍可编辑/删除）。
- 添加/编辑页：按 index.html 设计重建（标题输入 + 富文本编辑器 + 提醒 + 优先级 + 保存/取消）。
- 窗口改为可缩放（无边框边缘/角落拖拽），布局随窗口宽度自适应；卜卜 PeekCard 背景摆放与透明度不变。
"""

from PyQt6.QtWidgets import (
    QDialog, QWidget, QLabel, QPushButton, QLineEdit, QTextEdit, QDateTimeEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QBoxLayout, QAbstractButton, QCalendarWidget, QSizePolicy, QFrame,
    QGraphicsDropShadowEffect, QComboBox, QApplication, QGraphicsView, QGraphicsScene,
    QGraphicsProxyWidget, QGraphicsRotation,
)
from PyQt6.QtCore import (
    Qt, QDateTime, QTimer, QEvent, QSize, QRectF, QPropertyAnimation, QEasingCurve,
    pyqtProperty,
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QCursor, QIcon, QPainterPath, QVector3D, QPalette,
)

from app.core import todo, config
from app.core import alarm as alarm_mod
from app.core.voice import say
from app.core.i18n import tr
from app.ui.common import (
    PeekCard, NoticeDialog, promote_popup_topmost,
    EditContextMenu, CTX_MENU_TEXT_QSS,
)
from app.ui.context_menu import ActionPopupMenu, ACTION_POPUP_QSS
from app.ui.rich_editor import RichEditor, svg_icon


WINDOW_QSS = """
QWidget#GlassWindow {
    background: #fffaf5;
    border: 1px solid rgba(255,255,255,0.60);
    border-radius: 20px;
}
QWidget#window-bar {
    background: transparent;
    border-bottom: 1px solid rgba(249,117,16,0.12);
    border-top-left-radius: 20px;
    border-top-right-radius: 20px;
}
QWidget#todo-body,
QWidget#task-list-widget,
QWidget#add-panel {
    background: transparent;
}
QLabel#window-title {
    font-size: 15px;
    font-weight: 700;
    color: #3d2b1f;
}
QPushButton#todoSecondary,
QPushButton#todoDanger {
    background: transparent;
    border: 1.5px solid rgba(249,117,16,0.16);
    border-radius: 16px;
    color: #6b5744;
    font-size: 12px;
    font-weight: 600;
    padding: 0 10px;
}
QPushButton#todoSecondary:hover,
QPushButton#todoDanger:hover {
    background: rgba(249,117,16,0.08);
    color: #f97510;
}
QPushButton#todoPrimary {
    background: #ff7613;
    border: 1.5px solid #ff7613;
    border-radius: 16px;
    color: #fff;
    font-size: 12px;
    font-weight: 700;
    padding: 0 14px;
}
QPushButton#todoPrimary:hover { background: #ffa940; border-color: #ffa940; }
QLineEdit, QDateTimeEdit {
    background: rgba(255,248,240,0.72);
    border: 1.5px solid rgba(249,117,16,0.18);
    border-radius: 8px;
    color: #3d2b1f;
    font-size: 13px;
    padding: 0 12px;
}
QDateTimeEdit {
    padding-right: 34px;
}
QDateTimeEdit::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 30px;
    border: none;
    background: transparent;
}
QDateTimeEdit::down-arrow {
    image: none;
    width: 0;
    height: 0;
}
QLineEdit:focus, QDateTimeEdit:focus { border-color: rgba(249,117,16,0.34); background: #fffaf5; }
QDateTimeEdit:disabled { color: rgba(160,142,122,0.46); background: rgba(255,248,240,0.45); }
QLineEdit::placeholder { color: rgba(160,142,122,0.34); }
QScrollArea { border: none; background: transparent; border-bottom-left-radius: 20px; border-bottom-right-radius: 20px; }
QScrollBar:vertical { width: 4px; background: transparent; margin: 6px 0; }
QScrollBar::handle:vertical { background: rgba(160,142,122,0.35); border-radius: 2px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
/* 添加/编辑页：标题输入 + 字段标签 + 优先级 chips + 底部按钮（对齐 index.html） */
QLineEdit#titleInput {
    border: 1.5px solid #F1E4D3; border-radius: 14px;
    background: #FFFDFA; font-size: 16px; font-weight: 600; color: #3B2A1A;
    padding: 0 16px;
}
QLineEdit#titleInput:focus { border-color: #F97316; background: #fff; }
QLabel#fieldLabel { font-size: 13px; font-weight: 600; color: #8A7358; }
QLabel#fieldLabelReq { color: #F97316; font-weight: 700; }
QLabel#fieldHint { font-weight: 400; color: #B7A187; font-size: 12px; }
QFrame#editorFrame {
    border: 1.5px solid #F1E4D3; border-radius: 14px; overflow: hidden;
    background: transparent;
}
QFrame#editorFrame[focused="true"] { border-color: #F97316; }
QPushButton#todoChip {
    border: 1.5px solid #F1E4D3; background: #FFFDFA; border-radius: 11px;
    color: #6b5744; font-size: 13px; font-weight: 600; padding: 10px 8px;
}
QPushButton#todoChip:hover { border-color: #F2C79B; }
QPushButton#todoChip[prio="low"][active="true"] { background: #EDF7EC; border-color: #67B26F; color: #4C9A54; }
QPushButton#todoChip[prio="mid"][active="true"] { background: #FFF7EE; border-color: #F97316; color: #EA6A1F; }
QPushButton#todoChip[prio="high"][active="true"] { background: #FDECEC; border-color: #E5534C; color: #C53D36; }
QPushButton#todoClose {
    border: none; background: transparent; border-radius: 10px;
    color: #8A7358; font-size: 18px;
}
QPushButton#todoClose:hover { background: #FFF7EE; color: #3B2A1A; }
/* 添加/编辑页底部操作栏（对齐 index.html 的 .modal-foot）
   注意：背景与顶部分隔线由 PanelFooter 自绘 —— 实底在右侧留出缺口，
   让卡片右下角的卜卜露出区完整可见。 */
QPushButton#panelCancel {
    background: #FFFFFF; border: 1.5px solid #F1E4D3; border-radius: 13px;
    color: #8A7358; font-size: 14px; font-weight: 600; padding: 0 16px;
}
QPushButton#panelCancel:hover { border-color: #E7C9A6; color: #3B2A1A; }
QPushButton#panelSave {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #F97316,stop:1 #EA6A1F);
    border: none; border-radius: 13px; color: #FFFFFF;
    font-size: 14px; font-weight: 700; padding: 0 18px;
}
QPushButton#panelSave:hover {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #FF8A2B,stop:1 #F0741F);
}
QPushButton#panelSave:pressed { background: #E0600E; }
"""


CHECK_QSS = """
QCheckBox { spacing: 0px; }
QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border: 2px solid rgba(160,142,122,0.30);
    border-radius: 6px;
    background: transparent;
}
QCheckBox::indicator:checked {
    background: #ff7613;
    border-color: #ff7613;
}
"""

LABEL_QSS = "font-size:13px;color:#3d2b1f;font-weight:500;"
DONE_LABEL_QSS = "font-size:13px;color:#a08e7a;font-weight:500;text-decoration:line-through;"
# 列表行右侧信息标签（对齐 index.html 的 .tag / .tag.p-low / .tag.p-mid / .tag.p-high：
# 小号圆角标签，低=绿 / 中=橙 / 高=红）。
# 注意：QSS 的 border-radius 在大半径（如 999px）时会被 Qt 完全忽略（实测 8px 才生效），
# 故改用自绘的 TagLabel（见下方类），确保圆角真实可见、文字不裁切。
TAG_BG, TAG_FG = "#F4F0E8", "#8A7358"
_TAG_PRIO_COLORS = {"低": ("#EDF7EC", "#4C9A54"),
                    "中": ("#FFF7EE", "#EA6A1F"),
                    "高": ("#FDECEC", "#C53D36")}


def priority_tag_colors(prio: str):
    """优先级标签配色（与 index.html 的 .tag.p-low/.p-mid/.p-high 一致）。"""
    return _TAG_PRIO_COLORS.get(prio, (TAG_BG, TAG_FG))


class TagLabel(QLabel):
    """自绘圆角标签：用 QPainter 画圆角矩形背景（radius 指定，默认胶囊形），
    避免 QSS border-radius 大半径被 Qt 忽略导致圆角不生效；
    文字居中绘制，不会被裁切。用于列表行右侧的「提醒时间 / 优先级」标签。"""

    def __init__(self, text="", bg=TAG_BG, fg=TAG_FG, radius=8, parent=None):
        super().__init__(text, parent)
        self._bg = QColor(bg)
        self._fg = QColor(fg)
        self._radius = float(radius)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setContentsMargins(10, 3, 10, 3)

    def set_colors(self, bg, fg):
        self._bg, self._fg = QColor(bg), QColor(fg)
        self.update()

    def paintEvent(self, e):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._bg)
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), self._radius, self._radius)
        painter.setPen(self._fg)
        painter.setFont(self.font())
        painter.drawText(self.rect(),
                         int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter),
                         self.text())

class ElideLabel(QLabel):
    """单行标题标签：宽度不足时右侧省略号；鼠标悬停时横向滑动展示完整文字。

    关键：覆盖 minimumSizeHint 返回极小宽度，允许在 HBoxLayout 中被压缩，
    把剩余空间让给右侧的「提醒时间 / 优先级」标签（Fixed 不收缩），避免遮挡它们。
    显示长度随右侧标签宽度自动变化（有提醒时间则更短，无则更长）—— 纯由布局 + 重绘决定。
    """

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._full = text or ""
        self._offset = 0.0
        self._hover = False
        self._done = False
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(0)
        # Ignored：布局可把它压到极小宽度（不让长标题撑宽 / 挤压右侧标签）
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setMouseTracking(True)

    # ---- 允许被布局压缩（否则长标题会因 minimumSizeHint 撑宽、挤压/遮挡右侧标签） ----
    def minimumSizeHint(self):  # noqa: N802
        return QSize(1, self.fontMetrics().height())

    def sizeHint(self):  # noqa: N802
        return QSize(60, self.fontMetrics().height())

    # ---- 悬停滑动用的偏移属性（QPropertyAnimation 驱动） ----
    def _get_offset(self):
        return self._offset

    def _set_offset(self, v):
        self._offset = v
        self.update()

    offset = pyqtProperty(float, _get_offset, _set_offset)

    def setText(self, text):  # noqa: N802
        self._full = text or ""
        super().setText(self._full)
        self.setToolTip(self._full or None)  # 悬停 tooltip 兜底：仍可看全（与滑动并存）

    def set_done(self, done):
        self._done = bool(done)
        self.update()

    def _available(self):
        return max(0, self.width())

    def paintEvent(self, event):  # noqa: N802
        fm = self.fontMetrics()
        avail = self._available()
        full_w = fm.horizontalAdvance(self._full)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(self.rect())  # 防止左移滑动时画到标签区域外（遮挡左右控件）
        painter.setFont(self.font())
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        rect = self.rect()
        if full_w <= avail or not self._hover:
            # 非悬停（或放得下）：右侧省略号；放得下时 elidedText 等价于原文
            text = (fm.elidedText(self._full, Qt.TextElideMode.ElideRight, avail)
                    if full_w > avail else self._full)
            painter.drawText(rect, self.alignment(), text)
            self._maybe_strike(painter, rect, fm, text)
            return
        # 悬停滑动：只有「左边界」左移，右边界保持不动，从而露出被省略的中后段。
        # ★ 关键：切勿把整个矩形一起左移（-off,0,-off,0）——drawText 会在平移后的
        #   右边界处再次裁切，offset 越大尾部越被截掉，导致「hover 也显示不全」（用户反馈）。
        off = int(self._offset)
        shifted = rect.adjusted(-off, 0, 0, 0)
        painter.drawText(shifted, self.alignment(), self._full)
        self._maybe_strike(painter, shifted, fm, self._full)

    def _maybe_strike(self, painter, rect, fm, text):
        if not self._done:
            return
        # 完成态：在可见文字视觉中心画删除线（对齐 DONE_LABEL_QSS 的 line-through）
        text_w = fm.horizontalAdvance(text)
        if self.alignment() & Qt.AlignmentFlag.AlignRight:
            x0 = rect.right() - text_w
        else:
            x0 = rect.left()
        y = rect.center().y()
        pen = painter.pen()
        pen.setStyle(Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.drawLine(int(x0), int(y), int(x0 + text_w), int(y))

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        fm = self.fontMetrics()
        full_w = fm.horizontalAdvance(self._full)
        avail = self._available()
        if full_w > avail and avail > 0:
            max_off = full_w - avail
            self._anim.stop()
            # 时长随超长幅度增长（缓一点便于阅读），封顶 6s
            self._anim.setDuration(max(1200, min(6000, int(max_off * 6))))
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(float(max_off))
            self._anim.setEasingCurve(QEasingCurve.Type.Linear)
            self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self._anim.stop()
        self._offset = 0.0
        self.update()
        super().leaveEvent(event)


CALENDAR_QSS = """
QCalendarWidget QWidget#qt_calendar_navigationbar {
    background: #fff7ee;
    border: 1px solid rgba(249,117,16,0.16);
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
QCalendarWidget QToolButton {
    background: transparent;
    border: none;
    color: #3d2b1f;
    font-size: 13px;
    font-weight: 700;
    padding: 3px 6px;
}
QCalendarWidget QToolButton:hover {
    background: rgba(249,117,16,0.10);
    border-radius: 6px;
    color: #f97510;
}
QCalendarWidget QToolButton#qt_calendar_monthbutton::menu-indicator {
    image: none;
    width: 0;
    height: 0;
}
QCalendarWidget QMenu {
    background: #fffaf5;
    border: 1px solid rgba(249,117,16,0.16);
    color: #3d2b1f;
}
QCalendarWidget QSpinBox {
    background: #fff8f0;
    border: 1px solid rgba(249,117,16,0.18);
    border-radius: 6px;
    color: #3d2b1f;
    padding: 2px 6px;
}
QCalendarWidget QAbstractItemView {
    background: #fffaf5;
    color: #3d2b1f;
    selection-background-color: rgba(249,117,16,0.16);
    selection-color: #f97510;
    outline: 0;
}
"""


def speak_later(text):
    QTimer.singleShot(80, lambda: say(text))


# 卜卜在添加/编辑页右下角以「底面 1/3 为半径的 1/4 圆」展示，大小随窗口缩放；
# 内容框透明（透出主题色与卜卜），不另起一列留空白占位——表单整宽铺满，卜卜透过
# 透明内容显示；卜卜整体沿 45° 左上平移使嘴巴/眼睛完整露出（见 common.PeekCard）。


class PanelFooter(QFrame):
    """添加/编辑页底部操作栏（对齐 index.html 的 .modal-foot）。

    本卡片右下角是卜卜 1/4 圆露出区，故底部栏整体透明（透出主题色与卜卜），
    只在左侧画一条顶部分隔线（在卜卜半径处收住），右下角完全留给卜卜。
    """

    RADIUS = 19

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panelFooter")

    def paintEvent(self, e):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 底部栏透明（透出主题色与卜卜），仅画一条左侧顶部分隔线，与上方内容区区分
        width = float(self.width())
        painter.setPen(QPen(QColor("#F1E4D3"), 1))
        painter.drawLine(0, 1, int(width), 1)           # 顶部细分隔线
        painter.end()


class ToggleSwitch(QAbstractButton):
    """滑动开关，复刻 index.html 的 .switch（宽 42 / 高 24，橙色激活）。

    用 QAbstractButton 继承以获得 isChecked()/setChecked()/toggled 全套接口，
    外观自绘 + QPropertyAnimation 做滑块位移与轨道配色过渡。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 24)
        self.setStyleSheet("background:transparent;border:none;")
        self._offset = 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate_to)

    # --- 动画属性：0.0=关 / 1.0=开 ---
    def _get_offset(self):
        return self._offset

    def _set_offset(self, value):
        self._offset = float(value)
        self.update()

    offset = pyqtProperty(float, _get_offset, _set_offset)

    def _animate_to(self, checked):
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked):  # noqa: N802
        """程序化设置时直接跳到目标位置，避免打开面板时看到多余滑动。"""
        super().setChecked(checked)
        self._anim.stop()
        self._offset = 1.0 if checked else 0.0
        self.update()

    def paintEvent(self, e):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        t = self._offset
        off, on = QColor("#F1E4D3"), QColor("#F97316")
        track = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), (h - 1) / 2, (h - 1) / 2)
        # 滑块
        d = h - 6
        x = 3 + (w - d - 6) * t
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(QRectF(x, 3, d, d))


class TodoCheckBox(QPushButton):
    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(22, 22)
        self.setStyleSheet("QPushButton{background:transparent;border:none;padding:0;margin:0;}")

    def paintEvent(self, e):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#ff7613")))
            painter.drawRoundedRect(rect, 6, 6)
        else:
            pen = QPen(QColor(160, 142, 122, 76), 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 6, 6)
            return
        pen = QPen(QColor("#ffffff"), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(6, 11, 9, 15)
        painter.drawLine(9, 15, 16, 6)


class CalendarDateTimeEdit(QDateTimeEdit):
    def paintEvent(self, e):  # noqa: N802
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        enabled = self.isEnabled()
        stroke = QColor(107, 87, 68, 210 if enabled else 90)
        accent = QColor(249, 117, 16, 210 if enabled else 70)
        grid = QColor(160, 142, 122, 120 if enabled else 55)

        icon_w = 15
        icon_h = 15
        x = self.width() - 25
        y = (self.height() - icon_h) // 2

        painter.setPen(QPen(stroke, 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(x, y + 1, icon_w, icon_h - 1, 2.5, 2.5)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(accent))
        painter.drawRoundedRect(x + 1, y + 2, icon_w - 2, 4, 1.4, 1.4)

        painter.setPen(QPen(stroke, 1.5))
        painter.drawLine(x + 4, y, x + 4, y + 3)
        painter.drawLine(x + icon_w - 4, y, x + icon_w - 4, y + 3)

        painter.setPen(QPen(grid, 1))
        painter.drawLine(x + 4, y + 8, x + icon_w - 4, y + 8)
        painter.drawLine(x + 4, y + 11, x + icon_w - 4, y + 11)
        painter.drawLine(x + 7, y + 7, x + 7, y + icon_h - 3)
        painter.drawLine(x + 10, y + 7, x + 10, y + icon_h - 3)


class ResizeGrip(QWidget):
    """无边框窗口的边缘/角落缩放握把。"""

    def __init__(self, window, edges, cursor):
        super().__init__(window)
        self.window = window
        self.edges = edges
        self.setCursor(cursor)
        self.setStyleSheet("background:transparent;")
        self._press = None

    def mousePressEvent(self, e):  # noqa: N802
        # 便签置顶（锁定）时禁止缩放：window 无 _locked 属性则视为未锁定（不影响待办窗口）。
        if getattr(self.window, "_locked", False):
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = (e.globalPosition().toPoint(), self.window.geometry())

    def mouseMoveEvent(self, e):  # noqa: N802
        if not self._press:
            return
        gp, geo = self._press
        d = e.globalPosition().toPoint() - gp
        x, y, w, h = geo.x(), geo.y(), geo.width(), geo.height()
        minw, minh = self.window.minimumWidth(), self.window.minimumHeight()
        if "right" in self.edges:
            w = max(minw, w + d.x())
        if "left" in self.edges:
            nw = w - d.x()
            if nw >= minw:
                x = x + d.x()
                w = nw
        if "bottom" in self.edges:
            h = max(minh, h + d.y())
        if "top" in self.edges:
            nh = h - d.y()
            if nh >= minh:
                y = y + d.y()
                h = nh
        self.window.setGeometry(x, y, w, h)

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._press = None


class TaskRow(QWidget):
    def __init__(self, task, on_toggle, on_edit, on_delete, on_interact=None):
        super().__init__()
        self.task = task
        self.on_toggle = on_toggle
        self.on_edit = on_edit
        self.on_delete = on_delete
        self.on_interact = on_interact
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(10)
        self.check = TodoCheckBox()
        self.check.setChecked(task["done"])
        self.check.toggled.connect(self._toggled)
        self.check.contextMenuEvent = self._show_context_menu
        # 列表页：标题文字点击不做任何行为（按需求临时改为无操作），保留右键菜单编辑/删除。
        self.text = ElideLabel(task.get("title") or task.get("content") or "")
        self.text.setStyleSheet(LABEL_QSS)
        self.text.setCursor(Qt.CursorShape.PointingHandCursor)
        self.text.contextMenuEvent = self._show_context_menu
        # 左键点击标题文字 → 打开便签式任务卡片窗口（右键仍走编辑/删除菜单）
        self.text.mousePressEvent = self._on_title_press
        # 右侧信息（对齐 index.html 的 .tc-meta）：提醒时间（有提醒才显示）+ 优先级（必有）
        remind = task.get("remind") if task.get("remind_enabled", True) else None
        due_text = self._format_remind(remind)
        prio = task.get("priority") or "中"
        self.meta = QWidget()
        meta_lay = QHBoxLayout(self.meta)
        meta_lay.setContentsMargins(0, 0, 0, 0)
        meta_lay.setSpacing(8)
        if due_text:
            meta_lay.addWidget(self._make_tag(due_text, TAG_BG, TAG_FG))
        meta_lay.addWidget(self._make_tag(prio, *priority_tag_colors(prio)))
        self.meta.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.meta.contextMenuEvent = self._show_context_menu
        lay.addWidget(self.check)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.meta)
        self._apply()

    def _make_tag(self, text, bg, fg, radius=8):
        """右侧圆角标签；不给它收缩空间，保证标签文字永远完整。"""
        tag = TagLabel(text, bg, fg, radius)
        tag.contextMenuEvent = self._show_context_menu
        return tag

    def _format_remind(self, value):
        """提醒时间：有则按「年-月-日 时:分」完整显示（无提醒返回空字符串 → 不显示该项）。"""
        if not value:
            return ""
        dt = QDateTime.fromString(value, "yyyy-MM-dd HH:mm")
        return dt.toString("yyyy-MM-dd HH:mm") if dt.isValid() else value

    def _toggled(self, checked):
        if self.on_interact:
            self.on_interact()
        self.task["done"] = checked
        todo.toggle(self.task["id"])
        self._apply()
        if checked:
            speak_later(config.character.system_func.get("todo", {}).get("complete", "嘻嘻，任务完成捏"))
        self.on_toggle()
        # 列表项勾选变化后，通知对应便签窗口刷新其标题划线/颜色与确认键（双向同步）
        tw = self.window()
        notify = getattr(tw, "notify_sticky", None)
        if notify is not None:
            notify(self.task["id"])

    def _on_title_press(self, event):
        # 仅左键无修饰键 → 打开便签；其余（右键等）交回默认处理（触发右键菜单）
        if event.button() == Qt.MouseButton.LeftButton and \
                event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self._open_sticky()
            event.accept()
        else:
            QLabel.mousePressEvent(self.text, event)

    def _open_sticky(self):
        tw = self.window()
        opener = getattr(tw, "open_sticky", None)
        if opener is not None:
            opener(self.task)

    def contextMenuEvent(self, event):  # noqa: N802
        self._show_context_menu(event)

    def _show_context_menu(self, event):
        task = dict(self.task)
        edit_callback = self.on_edit
        delete_callback = self.on_delete
        event.accept()
        self._context_menu = ActionPopupMenu(self.window(), [
            (tr("编辑"), lambda t=task, cb=edit_callback: cb(t)),
            (tr("删除"), lambda t=task, cb=delete_callback: cb(t)),
        ]).show_at(event.globalPos())

    def _apply(self):
        if self.task["done"]:
            self.text.setStyleSheet(DONE_LABEL_QSS)
            self.text.set_done(True)
        else:
            self.text.setStyleSheet(LABEL_QSS)
            self.text.set_done(False)


class TodoWindow(QDialog):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._drag_pos = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._list_size = (480, 430)
        self._add_size = (620, 720)
        # 最小尺寸按模式区分：保证「无论怎么缩放，页面元素都完整可见」
        # （列表页 460 宽 = 标题 + 四个按钮 + 边距，英文模式最宽，留足余量）
        self._list_min = (460, 380)
        self._add_min = (470, 560)
        # 卜卜在添加/编辑页以「底面 1/3 半径的 1/4 圆」展示，大小随窗口缩放
        # （由 PeekCard.set_quarter_radius 在 resize 时按宽度动态设置）；
        # 列表页 add_mode=False，完全保持原样（零 UI 改动）。
        self.editing_task = None
        self.priority = "中"
        # 便签窗口注册表：task_id -> StickyNoteWindow（用于列表↔便签双向同步与删除时关闭）
        self.sticky_windows = {}
        self.setMinimumSize(*self._list_min)
        self.resize(*self._list_size)
        self._build()
        self._build_grips()

    def _build(self):
        frame_root = QVBoxLayout(self)
        frame_root.setContentsMargins(0, 0, 0, 0)
        frame_root.setSpacing(0)

        self.container = PeekCard(self, scale=1.08)
        self.container.setObjectName("GlassWindow")
        self.container.setStyleSheet(WINDOW_QSS)
        shadow = QGraphicsDropShadowEffect(self.container)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(180, 120, 50, 32))
        self.container.setGraphicsEffect(shadow)
        frame_root.addWidget(self.container)

        outer = QVBoxLayout(self.container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = QWidget()
        self.header.setObjectName("window-bar")
        self.header.setFixedHeight(58)
        header_lay = QHBoxLayout(self.header)
        header_lay.setContentsMargins(18, 0, 18, 0)
        header_lay.setSpacing(6)
        self.title_label = QLabel("📋 " + tr("任务清单"))
        self.title_label.setObjectName("window-title")
        header_lay.addWidget(self.title_label)
        header_lay.addStretch(1)
        # 编辑态专属：关闭按钮（自绘 X 图标，不再使用字符 ✕）
        self.close_b = QPushButton()
        self.close_b.setObjectName("todoClose")
        self.close_b.setIcon(QIcon(svg_icon("close", 18, "#8A7358")))
        self.close_b.setIconSize(QSize(18, 18))
        self.close_b.setFixedSize(34, 34)
        self.close_b.setVisible(False)
        self.close_b.setToolTip(tr("返回"))
        self.close_b.clicked.connect(self._hide_editor)
        header_lay.addWidget(self.close_b)
        self.sel_all = QPushButton(tr("全选"))
        self.add_b = QPushButton(tr("添加"))
        self.del_b = QPushButton(tr("删除"))
        self.back_b = QPushButton(tr("返回"))
        self.sel_all.setObjectName("todoSecondary")
        self.add_b.setObjectName("todoPrimary")
        self.del_b.setObjectName("todoDanger")
        self.back_b.setObjectName("todoSecondary")
        for b in (self.sel_all, self.add_b, self.del_b, self.back_b):
            b.setFixedHeight(32)
        self._apply_header_button_widths()
        self.sel_all.clicked.connect(self._select_all)
        self.add_b.clicked.connect(self._toggle_add)
        self.del_b.clicked.connect(self._delete)
        self.back_b.clicked.connect(self.close)
        header_lay.addWidget(self.sel_all)
        header_lay.addWidget(self.add_b)
        header_lay.addWidget(self.del_b)
        header_lay.addWidget(self.back_b)
        outer.addWidget(self.header)

        self.body = QWidget()
        self.body.setObjectName("todo-body")
        self.body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(self.body, 1)
        root = QVBoxLayout(self.body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header.mousePressEvent = self._bar_press
        self.header.mouseMoveEvent = self._bar_move

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self.list_widget = QWidget()
        self.list_widget.setObjectName("task-list-widget")
        self.list_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.list_lay = QVBoxLayout(self.list_widget)
        self.list_lay.setContentsMargins(12, 8, 12, 12)
        self.list_lay.setSpacing(0)
        self.scroll.setWidget(self.list_widget)
        root.addWidget(self.scroll, 1)

        # ===== 添加/编辑面板（匹配 index.html 设计） =====
        self.add_panel = QWidget()
        self.add_panel.setObjectName("add-panel")
        self.add_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.add_panel.setVisible(False)
        ap_root = QVBoxLayout(self.add_panel)
        ap_root.setContentsMargins(0, 0, 0, 0)
        ap_root.setSpacing(0)

        # 页面主体不放滚动区：表单整体随窗口缩放自适应，
        # 只有「任务内容」编辑区自身可滚动（满足“主体无滚动条、仅内容可滚动”）。
        self.add_content = QWidget()
        self.add_content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        ac = QVBoxLayout(self.add_content)
        # 内容框透明、整宽铺满：卜卜透过透明内容显示，不另起空白列（详见 PeekCard 的
        # 1/4 圆 + 45° 左上平移，使嘴巴/眼睛完整露出）。
        ac.setContentsMargins(24, 18, 24, 6)
        ac.setSpacing(16)
        self._narrow = None  # 窄宽度内边距状态缓存

        # 任务标题
        title_label = QLabel()
        title_label.setObjectName("fieldLabel")
        title_label.setText(tr("任务标题") + ' <span style="color:#F97316;font-weight:700">*</span>')
        title_label.setTextFormat(Qt.TextFormat.RichText)
        self.title_in = QLineEdit()
        self.title_in.setObjectName("titleInput")
        self.title_in.setPlaceholderText(tr("给任务起个标题，比如：完成季度复盘"))
        self.title_in.setFixedHeight(44)
        self.title_in.setMaxLength(80)
        self.title_in.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        ac.addWidget(title_label)
        ac.addWidget(self.title_in)

        # 任务内容（富文本）
        content_label = QLabel(tr("任务内容"))
        content_label.setObjectName("fieldLabel")
        self.editor = RichEditor()
        self.editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.editor_frame = QFrame()
        self.editor_frame.setObjectName("editorFrame")
        self.editor_frame.setProperty("focused", False)
        self.editor_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        fl = QVBoxLayout(self.editor_frame)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)
        fl.addWidget(self.editor)
        # 编辑区聚焦时高亮外框（Qt QSS 不支持 :focus-within，改用动态属性）
        self.editor.focusIn.connect(lambda: self._set_editor_focus(True))
        self.editor.focusOut.connect(lambda: self._set_editor_focus(False))
        ac.addWidget(content_label)
        ac.addWidget(self.editor_frame, 1)

        # 提醒时间 + 优先级
        meta = QHBoxLayout()
        meta.setSpacing(16)
        self.meta_row = meta
        # 提醒
        remind_col = QVBoxLayout()
        remind_col.setSpacing(6)
        remind_head = QHBoxLayout()
        remind_head.setSpacing(6)
        rlab = QLabel(tr("提醒时间"))
        rlab.setObjectName("fieldLabel")
        # 与优先级列的表头等高，保证两列的「输入控件」起始 y 对齐
        rlab.setFixedHeight(24)
        # 滑动开关（对齐 index.html 的 .switch）
        self.remind_chk = ToggleSwitch()
        remind_head.addWidget(rlab)
        remind_head.addStretch(1)
        remind_head.addWidget(self.remind_chk)
        self.remind_in = CalendarDateTimeEdit(QDateTime.currentDateTime())
        self.remind_in.setDisplayFormat("yyyy/MM/dd HH:mm")
        self.remind_in.setCalendarPopup(True)
        calendar = QCalendarWidget(self.remind_in)
        calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        calendar.setStyleSheet(CALENDAR_QSS)
        self.remind_in.setCalendarWidget(calendar)
        # 日历弹窗是独立顶层窗口，需要提升到 TopMost 层最上方，
        # 否则会被置顶的卡片窗口压住（即「年月日框被页面遮挡」）。
        self._calendar = calendar
        calendar.installEventFilter(self)
        self.remind_in.setFixedHeight(40)
        self.remind_in.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.remind_in.setEnabled(False)
        self.remind_chk.toggled.connect(self._on_remind_toggled)
        remind_col.addLayout(remind_head)
        remind_col.addWidget(self.remind_in)
        meta.addLayout(remind_col, 1)
        # 优先级
        prio_col = QVBoxLayout()
        prio_col.setSpacing(6)
        plab = QLabel(tr("优先级"))
        plab.setObjectName("fieldLabel")
        plab.setFixedHeight(24)  # 与提醒列的表头等高（含开关），两列控件对齐
        prio_col.addWidget(plab)
        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)
        self.chips = []
        for p in ("低", "中", "高"):
            chip = QPushButton(tr(p))
            chip.setObjectName("todoChip")
            # 窄窗时也保证 chips 不被压扁（宽度不足时由提醒栏让位）
            chip.setMinimumWidth(58)
            chip.setFixedHeight(40)  # 与提醒时间输入框等高，两列底部对齐
            chip.setProperty("prio", "low" if p == "低" else ("high" if p == "高" else "mid"))
            chip.setProperty("active", p == "中")
            chip.clicked.connect(lambda _=False, pp=p: self._on_chip(pp))
            chips_row.addWidget(chip)
            self.chips.append(chip)
        prio_col.addLayout(chips_row)
        meta.addLayout(prio_col, 1)
        ac.addLayout(meta)

        ap_root.addWidget(self.add_content, 1)

        # 底部操作栏（对齐 index.html 的 .modal-foot；右下角为卜卜 1/4 圆让位）
        self.footer = PanelFooter()
        footer = QHBoxLayout(self.footer)
        # 右侧内边距额外加卜卜半径：按钮整体左移，不压在卜卜露出区上
        footer.setContentsMargins(24, 12, 24, 18)
        footer.setSpacing(12)
        self.footer_lay = footer
        footer.addStretch(1)
        self.cancel_b = QPushButton(tr("取消"))
        self.save_b = QPushButton(tr("保存任务"))
        self.cancel_b.setObjectName("panelCancel")
        self.save_b.setObjectName("panelSave")
        self.cancel_b.setFixedHeight(42)
        self.save_b.setFixedHeight(42)
        # 不设最小宽度：窄窗（470）时按钮要能和右侧卜卜让位区共存，不互相挤压
        self.cancel_b.setMinimumWidth(0)
        self.save_b.setMinimumWidth(0)
        self.cancel_b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_b.clicked.connect(self._hide_editor)
        self.save_b.clicked.connect(self._save)
        footer.addWidget(self.cancel_b)
        footer.addWidget(self.save_b)
        ap_root.addWidget(self.footer)

        root.addWidget(self.add_panel)

        self._apply_responsive_margins()
        self._render()

    def _build_grips(self):
        m = 7
        top = 58
        self.grip_left = ResizeGrip(self, ("left",), QCursor(Qt.CursorShape.SizeHorCursor))
        self.grip_right = ResizeGrip(self, ("right",), QCursor(Qt.CursorShape.SizeHorCursor))
        self.grip_bottom = ResizeGrip(self, ("bottom",), QCursor(Qt.CursorShape.SizeVerCursor))
        self.grip_bl = ResizeGrip(self, ("left", "bottom"), QCursor(Qt.CursorShape.SizeFDiagCursor))
        self.grip_br = ResizeGrip(self, ("right", "bottom"), QCursor(Qt.CursorShape.SizeBDiagCursor))
        self.grip_left.setGeometry(0, top, m, self.height() - top - m)
        self.grip_right.setGeometry(self.width() - m, top, m, self.height() - top - m)
        self.grip_bottom.setGeometry(m, self.height() - m, self.width() - 2 * m, m)
        self.grip_bl.setGeometry(0, self.height() - m, m, m)
        self.grip_br.setGeometry(self.width() - m, self.height() - m, m, m)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        m = 7
        top = 58
        if hasattr(self, "grip_left"):
            self.grip_left.setGeometry(0, top, m, self.height() - top - m)
            self.grip_right.setGeometry(self.width() - m, top, m, self.height() - top - m)
            self.grip_bottom.setGeometry(m, self.height() - m, self.width() - 2 * m, m)
            self.grip_bl.setGeometry(0, self.height() - m, m, m)
            self.grip_br.setGeometry(self.width() - m, self.height() - m, m, m)
        self._apply_responsive_margins()

    def _peek_r(self):
        """卜卜 1/4 圆区域半径 = 卡片（窗口）宽度的 1/3，卜卜大小随窗口缩放。"""
        return max(120.0, self.width() / 3.0)

    def _apply_responsive_margins(self):
        """随窗口宽度自适应：内边距收紧 + 卜卜半径留白 + 窄窗时提醒/优先级纵向堆叠，
        保证所有控件（标题/编辑框/底部按钮）恒定完整可见且可交互。"""
        if not hasattr(self, "add_content"):
            return
        narrow = self.width() < 540
        pad = 18 if narrow else 24
        # 表单与底部按钮整宽铺满（右侧不再留卜卜空白列）；卜卜透过透明内容显示，
        # 且已沿 45° 左上平移使嘴巴/眼睛完整露出，不与按钮争抢右下角。
        self.add_content.layout().setContentsMargins(pad, 16 if narrow else 18, pad, 6)
        self.footer_lay.setContentsMargins(pad, 12, pad, 16 if narrow else 18)
        # 窄窗：提醒时间 / 优先级 由横向并排改为纵向堆叠，避免 chips 被压扁、按钮点不到
        self.meta_row.setDirection(
            QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
        for chip in self.chips:
            chip.setMinimumWidth(48 if narrow else 58)
        # 同步卜卜半径（窗口缩放时卜卜大小跟着变）
        if self.container.add_mode:
            self.container.set_quarter_radius(self._peek_r())

    def _set_editor_focus(self, on):
        """编辑区聚焦时给外框加橙色描边。"""
        if not hasattr(self, "editor_frame"):
            return
        self.editor_frame.setProperty("focused", bool(on))
        self.editor_frame.style().unpolish(self.editor_frame)
        self.editor_frame.style().polish(self.editor_frame)

    def eventFilter(self, obj, event):  # noqa: N802
        """日历弹窗显示时把它顶到最上层，避免被置顶卡片压住。"""
        if obj is getattr(self, "_calendar", None) and event.type() in (
            QEvent.Type.Show, QEvent.Type.ShowToParent,
        ):
            QTimer.singleShot(0, promote_popup_topmost)
        return super().eventFilter(obj, event)

    def set_title(self, title: str):
        self.title_label.setText(title)

    def _apply_header_button_widths(self):
        # 顶部四个按钮宽度统一（与「返回」一致），避免前三颗比「返回」宽出一截
        is_en = config.settings.get("language") == "en"
        w = 68 if is_en else 62
        for b in (self.sel_all, self.add_b, self.del_b, self.back_b):
            b.setFixedWidth(w)

    def _bar_press(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.pos()

    def _bar_move(self, e):
        if self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            # 编辑态：返回列表；列表态：关闭窗口
            if self.add_panel.isVisible():
                self._hide_editor()
            else:
                self.close()
            return
        super().keyPressEvent(e)

    def _render(self):
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        tasks = todo.all_tasks()
        if not tasks:
            empty = QLabel(tr("暂无任务，点『添加』开始捏～"))
            empty.setStyleSheet("color:#a08e7a;font-size:16px;padding:20px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list_lay.addWidget(empty)
        for t in tasks:
            self.list_lay.addWidget(
                TaskRow(t, self._after_task_toggle, self._edit_task,
                        self._delete_task, self.ctx.stop_alarm)
            )
        self.list_lay.addStretch(1)
        self._prune_stickies()

    def refresh_external(self):
        """外部闹钟删除后刷新待办列表及当前提醒状态。"""
        if self.editing_task:
            current = next((t for t in todo.all_tasks()
                            if t.get("id") == self.editing_task.get("id")), None)
            if current:
                self.editing_task = current
                self._populate_editor(current)
        self._render()

    def _after_task_toggle(self):
        self._render()
        self.ctx.refresh_alarm()

    def _select_all(self):
        tasks = todo.all_tasks()
        if not tasks:
            return
        all_done = all(t["done"] for t in tasks)
        for t in tasks:
            if t["done"] == all_done:
                t["done"] = not all_done
                todo.toggle(t["id"])
        self._render()

    def _toggle_add(self):
        if self.add_panel.isVisible():
            self._hide_editor()
        else:
            self._show_editor()

    def _on_chip(self, prio):
        self.priority = prio
        for chip in self.chips:
            chip.setProperty("active", chip.text() == tr(prio))
            chip.style().polish(chip)

    def _show_editor(self, task=None):
        self.editing_task = task
        if task:
            self._populate_editor(task)
        else:
            self.title_in.clear()
            self.editor.clear()
            self.remind_chk.setChecked(False)
            self.remind_in.setDateTime(QDateTime.currentDateTime())
            self._on_chip("中")
        self.add_panel.setVisible(True)
        # 切换到添加/编辑页：卜卜进入「底面 1/3 半径 1/4 圆」模式（列表页零改动）
        self.container.set_add_mode(True)
        self.container.set_quarter_radius(self._peek_r())
        self._apply_responsive_margins()
        self.scroll.setVisible(False)
        self.sel_all.setVisible(False)
        self.add_b.setVisible(False)
        self.del_b.setVisible(False)
        self.back_b.setVisible(False)
        self.close_b.setVisible(True)
        self.set_title(tr("编辑任务") if task else tr("添加任务"))
        # 先放宽最小尺寸再定尺寸：确保表单所有字段（含底部按钮）恒定完整可见
        self.setMinimumSize(*self._add_min)
        self.resize(max(self._add_size[0], self.width()), max(self._add_size[1], self.height()))
        self.title_in.setFocus()

    def _populate_editor(self, task):
        self.title_in.setText(task.get("title", ""))
        self.editor.set_html(task.get("content", ""))
        prio = task.get("priority", "中")
        self._on_chip(prio)
        if task.get("remind"):
            self.remind_chk.setChecked(task.get("remind_enabled", True))
            dt = QDateTime.fromString(task["remind"], "yyyy-MM-dd HH:mm")
            if dt.isValid():
                self.remind_in.setDateTime(dt)
        else:
            self.remind_chk.setChecked(False)
            self.remind_in.setDateTime(QDateTime.currentDateTime())

    def _on_remind_toggled(self, checked):
        self.remind_in.setEnabled(checked)
        if checked and self.remind_in.dateTime() <= QDateTime.currentDateTime():
            self.remind_in.setDateTime(QDateTime.currentDateTime().addSecs(60))

    def _hide_editor(self):
        self.editing_task = None
        self.title_in.clear()
        self.editor.clear()
        self.remind_chk.setChecked(False)
        self.remind_in.setDateTime(QDateTime.currentDateTime())
        self._on_chip("中")
        self.add_panel.setVisible(False)
        # 切回列表页：卜卜退出添加模式，恢复原始小图 peek（保持列表页零 UI 改动）
        self.container.set_add_mode(False)
        self.scroll.setVisible(True)
        self.sel_all.setVisible(True)
        self.add_b.setVisible(True)
        self.del_b.setVisible(True)
        self.back_b.setVisible(True)
        self.close_b.setVisible(False)
        self.set_title("📋 " + tr("任务清单"))
        self.setMinimumSize(*self._list_min)
        self.resize(*self._list_size)

    def retranslate_ui(self):
        if self.add_panel.isVisible():
            self.set_title(tr("编辑任务") if self.editing_task else tr("添加任务"))
        else:
            self.set_title("📋 " + tr("任务清单"))
        self.sel_all.setText(tr("全选"))
        self.add_b.setText(tr("添加"))
        self.del_b.setText(tr("删除"))
        self.back_b.setText(tr("返回"))
        self._apply_header_button_widths()
        # 添加/编辑页文案
        self.title_in.setPlaceholderText(tr("给任务起个标题，比如：完成季度复盘"))
        self.cancel_b.setText(tr("取消"))
        self.save_b.setText(tr("保存任务"))
        for chip, p in zip(self.chips, ("低", "中", "高")):
            chip.setText(tr(p))
            chip.setProperty("active", self.priority == p)
            chip.style().polish(chip)
        self._render()

    def _edit_task(self, task):
        self._show_editor(task)

    def _delete_task(self, task):
        if todo.delete_task(task.get("id")):
            self._render()
            self.ctx.refresh_alarm()
            speak_later(config.character.system_func.get("todo", {}).get("delete", "这条任务已经删掉捏"))

    def _sync_alarm(self, content, remind, old_alarm_id=None, enabled=True):
        if not remind:
            return None
        if old_alarm_id and not enabled:
            updated = alarm_mod.update(
                old_alarm_id, custom_text=content, enabled=False
            )
            return old_alarm_id if updated else None
        dt = QDateTime.fromString(remind, "yyyy-MM-dd HH:mm")
        if not dt.isValid() or dt <= QDateTime.currentDateTime():
            return None
        if old_alarm_id:
            updated = alarm_mod.update(
                old_alarm_id,
                hour=dt.time().hour(),
                minute=dt.time().minute(),
                once_date=dt.date().toString("yyyy-MM-dd"),
                custom_text=content,
                enabled=enabled,
            )
            if updated:
                return old_alarm_id
        synced_alarm = alarm_mod.add(
            hour=dt.time().hour(),
            minute=dt.time().minute(),
            repeat="once",
            once_date=dt.date().toString("yyyy-MM-dd"),
            custom_text=content,
            source="todo",
            enabled=enabled,
        )
        return synced_alarm.get("id")

    def _save(self):
        title = self.title_in.text().strip()
        if not title:
            NoticeDialog(self, tr("请先填写任务标题"), tr("任务标题为必填项")).exec()
            self.title_in.setFocus()
            return
        content_html = self.editor.to_html()
        remind_enabled = self.remind_chk.isChecked()
        remind = None
        if remind_enabled:
            dt = self.remind_in.dateTime()
            min_dt = QDateTime.currentDateTime().addSecs(180)
            if dt < min_dt:
                NoticeDialog(self, tr("提醒时间过近"), tr("提醒时间至少要在系统时间3分钟后")).exec()
                return
            remind = dt.toString("yyyy-MM-dd HH:mm")
        elif self.editing_task and self.editing_task.get("alarm_id") and self.editing_task.get("remind"):
            # 关闭提醒时保留原闹钟和时间，只同步 enabled 状态。
            remind = self.editing_task["remind"]
        old_alarm_id = self.editing_task.get("alarm_id") if self.editing_task else None
        alarm_id = self._sync_alarm(
            title, remind, old_alarm_id, enabled=remind_enabled
        )
        if self.editing_task:
            todo.update_task(
                self.editing_task["id"], title, content_html, remind,
                alarm_id=alarm_id, remind_enabled=remind_enabled, priority=self.priority,
            )
        else:
            todo.add(title, content_html, remind, alarm_id=alarm_id, priority=self.priority)
        self._hide_editor()
        self._render()
        self.ctx.refresh_alarm()
        speak_later(config.character.system_func.get("todo", {}).get("addSuccess", "好嘟，任务保存好捏"))

    def _delete(self):
        removed = todo.delete_done()
        self._render()
        self.ctx.refresh_alarm()

    # ===== 便签式任务卡片（点击列表标题文字打开） =====

    # 「复制任务」新开便签时相对原窗口的错位步长（px）。
    # 完全重叠会让用户以为没复制成功，故每张新便签往右下错开一点。
    CASCADE_STEP = 28
    CASCADE_MAX = 8          # 错开步数上限（超出后回绕，避免越飘越远）

    def open_sticky(self, task, base=None):
        """打开（或聚焦已打开的）某任务的便签窗口。

        base：可选的「参照窗口」。传入时把新便签摆在它的右下方（级联错位），
        用于「复制任务」——否则新窗口与原窗口完全重叠，用户会以为没复制成功。
        不传则沿用 Qt 默认位置（从列表页点开便签的行为保持不变）。
        """
        existing = self.sticky_windows.get(task["id"])
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = StickyNoteWindow(task, self, self.ctx)
        self.sticky_windows[task["id"]] = win
        win.show()
        if base is not None:
            self._cascade_sticky(win, base)

    def _cascade_sticky(self, win, base):
        """把 win 错开摆到 base 的右下方，避免「复制任务」后两窗完全重叠。

        - 错开量按当前已开便签数递增（连点复制也不会层层重合），并在
          CASCADE_MAX 步后回绕，避免越飘越远。
        - 必须夹紧到屏幕可用区域：越界就翻到 base 的左上方，保证新窗口完整可见
          （否则错到屏幕外，用户反而找不到新便签）。
        """
        n = max(1, len(self.sticky_windows) - 1)          # 已开便签数（不含刚开的）
        step = self.CASCADE_STEP * (((n - 1) % self.CASCADE_MAX) + 1)
        x, y = base.x() + step, base.y() + step
        scr = QApplication.screenAt(base.pos()) or QApplication.primaryScreen()
        if scr is None:
            win.move(x, y)
            return
        avail = scr.availableGeometry()
        max_x = avail.right() - win.width() + 1
        max_y = avail.bottom() - win.height() + 1
        if x > max_x or y > max_y:                        # 右下放不下 → 改到左上
            x, y = base.x() - step, base.y() - step
        x = max(avail.left(), min(x, max(max_x, avail.left())))
        y = max(avail.top(), min(y, max(max_y, avail.top())))
        win.move(x, y)

    def unregister_sticky(self, tid):
        self.sticky_windows.pop(tid, None)

    def notify_sticky(self, tid):
        """列表项勾选状态变化时，通知对应便签窗口刷新其标题划线/颜色与确认键。"""
        win = self.sticky_windows.get(tid)
        if win is not None:
            win.sync_state()

    def _prune_stickies(self):
        """任务被删除后，关闭其对应的便签窗口。"""
        ids = {t["id"] for t in todo.all_tasks()}
        for tid, win in list(self.sticky_windows.items()):
            if tid not in ids:
                try:
                    win.close()
                except RuntimeError:
                    self.sticky_windows.pop(tid, None)


# 便签背景色：默认主题米色 #fffaf5，外加参考 HTML 的 5 色（主题色/黄/绿/蓝/粉）。
# 用户要求「白色改为软件主题色」——原「白」(#fefefe) 与「主题色」(#fffaf5) 重复，
# 故移除「白」、保留「主题色」作为切回入口（默认背景与软件主题一致）。
STICKY_COLORS = [
    ("主题色", "#fffaf5"),
    ("黄", "#fff9c4"),
    ("绿", "#e7f5e8"),
    ("蓝", "#e6f2ff"),
    ("粉", "#ffe8ec"),
]

# 便签右键菜单：只负责「便签自定义项」，编辑动作块与整体样式复用 app/ui/common.py 的
# EditContextMenu（两处右键菜单同源，避免再次出现样式/功能不一致）。


class StickyContextMenu(EditContextMenu):
    """便签右键菜单 = 原生编辑动作块 + 复制任务 / 清空内容 / 便签背景（色板）。

    - 编辑动作块（撤销/重做/剪切/复制/粘贴/删除/全选 + 快捷键）由 EditContextMenu 提供，
      文案走 i18n，与软件「语言」设置一致（不再出现 Qt 原生英文菜单）。
    - 自定义块严格对齐参考 HTML；按用户要求已移除「旋转便签」，「白色」改为软件主题色。
    - 「复制任务」= 克隆一个标题/内容相同的新任务，并联动任务清单同步新开对应便签。
    """

    def __init__(self, parent, sticky, target=None):
        # 注意：_build_extra 在基类 __init__ 内被调用，故 sticky 必须先于 super() 赋值。
        self.sticky = sticky
        super().__init__(parent, target)

    # ---------- 子类扩展项（编辑动作块之后追加） ----------
    def _build_extra(self, lay):
        lay.addWidget(self._separator())

        # 1) 便签自定义项（对齐参考 HTML；已移除「旋转便签」）
        # 注意：_row() 内部已经把回调包进了 self._trigger()（close + 延迟执行），
        # 这里**不能再多包一层** _trigger——否则点击时 _trigger 会走两遍，
        # 第二遍 close() 时菜单因 WA_DeleteOnClose 已销毁 → RuntimeError 崩溃。
        for text, cb in (("复制任务", self.sticky.copy_task),
                         ("清空内容", self.sticky.clear_content)):
            lay.addWidget(self._row(tr(text), "", cb))

        # 2) 便签背景：标签 + 一排圆形色块。
        #    英文「Sticky Background」比中文「便签背景」长得多；若标签与色块同排，
        #    标签只剩 ~54px 会被截断成「Sticky Bac」。故改为两行——第一行标签（独占整宽、
        #    完整显示），第二行色块，两者左对齐。菜单高度由 show_at() 的 adjustSize() 自动增长。
        bg_row = QWidget()
        bl = QVBoxLayout(bg_row)
        bl.setContentsMargins(14, 6, 10, 6)
        bl.setSpacing(6)
        lbl = QLabel(tr("便签背景"))
        # 与上方菜单项（复制任务/清空内容/撤销…）字体样式保持一致：同为 CTX_MENU_TEXT_QSS(13px)，
        # 不再单独压成 12px（否则「便签背景」比其它项明显小一号）。
        lbl.setStyleSheet(CTX_MENU_TEXT_QSS)
        bl.addWidget(lbl)
        sw_row = QWidget()
        sl = QHBoxLayout(sw_row)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        for _name, col in STICKY_COLORS:
            sw = QPushButton()
            sw.setFixedSize(18, 18)
            sw.setCursor(Qt.CursorShape.PointingHandCursor)
            sw.setToolTip(tr(_name))
            sw.setStyleSheet(
                f"background:{col};border:1px solid #ccc;border-radius:9px;")
            sw.clicked.connect(lambda _checked=False, c=col: self._set_bg(c))
            sl.addWidget(sw)
        sl.addStretch(1)
        bl.addWidget(sw_row)
        lay.addWidget(bg_row)

    def _set_bg(self, col):
        # 与菜单项走同一条关闭链路（_trigger 内含已销毁防护）
        self._trigger(lambda: self.sticky.set_bg(col))


class _StickyView(QGraphicsView):
    """便签专用视图：整张卡片固定铺满窗口，**禁用一切滚动位移**。

    背景：`_sync_geometry()` 为容纳卡片投影给 scene 留了 pad=36 的外扩区域，
    于是 scene 比视口大 → QGraphicsView 默认具备滚动能力。当任务内容为空时，
    内层 QTextEdit 没有可滚动内容，会把滚轮事件忽略掉 → 事件冒泡到视图 →
    视图把整张卡片上下滚动一下，表现为「顶部栏被顶出去 / 底部工具栏被裁掉」
    的错位（用户反馈：文本框无内容时滚轮一动就乱）。

    修法：直接覆盖 wheelEvent、完全不调用基类实现（基类才会滚动视口），
    滚轮在内容为空时不产生任何位移；内容超长时滚轮由内层 QTextEdit 自行消费，
    根本不会传到这里，因此长文本依旧可以正常滚动。
    """

    def wheelEvent(self, e):  # noqa: N802
        e.ignore()


class StickyNoteWindow(QWidget):
    """便签式任务卡片窗口（对齐参考 HTML 的 #taskCard）。

    - 无边框 + 半透明背景，卡片用 QGraphicsProxyWidget 承载；窗口可用原生
      startSystemMove 拖拽标题栏移动、可边缘/角落缩放。
    - 顶部三按钮：完成（确认键，双向同步列表项划线/颜色）/ 置顶（锁定不可移动与缩放）/
      关闭。
    - 可编辑标题（QLineEdit，下划线样式）+ 复用的紧凑富文本编辑器（11 按钮工具栏）。
    - 右键菜单：复制任务（克隆为新任务并联动列表与便签）/ 清空内容 / 便签背景（色板）。
    - 背景默认主题色 #fffaf5（与软件主题一致），可切 5 色。
    """

    def __init__(self, task, todo_window, ctx):
        super().__init__()
        self.task_id = task["id"]
        self.todo_window = todo_window
        self.ctx = ctx
        self._locked = False
        self._drag = None  # 手动拖拽状态：{"start_global": QPoint, "start_pos": QPoint}
        self._done = bool(task.get("done", False))
        self._rotate = 0
        self._bg = QColor("#fffaf5")  # 软件主题米色（默认背景）

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                           | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 最小/最大缩放尺寸：保证 420px 卡片 + 圆角 + 阴影始终显示正常、不溢出；
        # 最小宽 400 可容纳单行 11 按钮工具栏，最小高 380 可容纳 180px 编辑器 + 工具栏
        self.setMinimumSize(400, 380)
        self.setMaximumSize(980, 820)

        self._build_note()
        self._build_view()
        self._build_grips()
        self.resize(420, 380)
        self.set_bg("#fffaf5")
        # 打开便签时立即载入该任务的真实标题与富文本内容（修复：之前永远显示占位符）
        self.title.setText(task.get("title", "") or "")
        self.editor.set_html(task.get("content", ""))
        self.sync_state()

    # ---------- 构建 ----------
    def _build_note(self):
        self.note = QWidget()
        self.note.setObjectName("stickyNote")
        self.note.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        nl = QVBoxLayout(self.note)
        nl.setContentsMargins(20, 20, 20, 20)   # HTML p-5 = 20px
        nl.setSpacing(0)

        # 顶部操作栏（同时也是拖拽手柄）
        self.bar = QWidget()
        self.bar.setFixedHeight(24)
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(12)                        # HTML gap-3 = 12px
        self.btn_complete = QPushButton()
        self.btn_pin = QPushButton()
        self.btn_close = QPushButton()
        for b, role in ((self.btn_complete, "complete"),
                        (self.btn_pin, "pin"),
                        (self.btn_close, "close")):
            b.setObjectName("stickyBtn")
            b.setProperty("role", role)
            b.setFixedSize(24, 24)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIcon(QIcon(self._btn_icon(role, False)))
            b.setIconSize(QSize(20, 20))
            # 写入 :hover 以启用 WA_Hover，使事件过滤器能切换 hover 图标配色
            b.setStyleSheet(
                "QPushButton{background:transparent;border:none;padding:0;}"
                "QPushButton:hover{background:rgba(0,0,0,0.06);border-radius:8px;}")
            b.installEventFilter(self)
        bl.addStretch(1)
        bl.addWidget(self.btn_complete)
        bl.addWidget(self.btn_pin)
        bl.addWidget(self.btn_close)
        nl.addWidget(self.bar)
        nl.addSpacing(12)                         # HTML 顶部栏 mb-3 = 12px

        # 可编辑标题（text-xl 20px / font-medium / 下划线；完成时删除线 + 变灰）
        self.title = QLineEdit()
        self.title.setObjectName("stickyTitle")
        self.title.setPlaceholderText(tr("任务标题"))
        self.title.setFixedHeight(36)
        nl.addWidget(self.title)
        nl.addSpacing(16)                         # HTML 标题 mb-4 = 16px

        # 富文本任务内容（复用紧凑编辑器：单行 11 按钮工具栏）
        self.editor = RichEditor(compact=True)
        nl.addWidget(self.editor, 1)

        # 拖拽手柄（顶部栏）与便签体右键菜单：用事件过滤器实现，
        # 避免给「代理内的子控件」设置实例级事件虚函数覆盖（那种写法在代理控件
        # 析构时 PyQt 虚函数分派会访问已半销毁的父窗口绑定方法 → 段错误）。
        self.bar.installEventFilter(self)
        self.note.installEventFilter(self)
        # 也监听标题 / 富文本编辑器（含内层 QTextEdit）：否则在这两处右键会弹出
        # QLineEdit/QTextEdit 各自的原生菜单，与设计的右键菜单完全不同 →
        # 表现为「菜单还是没改」。统一拦截后整个卡片任意位置右键都是同一个自绘菜单。
        self.title.installEventFilter(self)
        self.editor.installEventFilter(self)
        # ★ 关键：QTextEdit 是 QAbstractScrollArea，右键的 ContextMenu 事件是投递给它的
        #   **viewport()** 而不是 QTextEdit 本身！只装在 QTextEdit 上永远收不到 →
        #   内容区右键会弹出 QTextEdit 自带的原生菜单（Undo/Redo/Cut/Copy/Paste…），
        #   这正是用户反馈「右键菜单还是没改」的真正原因。必须装在 viewport 上。
        self.editor.editor.viewport().installEventFilter(self)
        self.btn_complete.clicked.connect(self.toggle_done)
        self.btn_pin.clicked.connect(self.toggle_pin)
        self.btn_close.clicked.connect(self.close)
        self.title.editingFinished.connect(self._on_title_edited)

    def _build_view(self):
        # _StickyView：禁用滚轮滚动，避免内容为空时滚轮把整张卡片顶偏/裁切
        self._view = _StickyView(self)
        self._view.setFrameShape(QFrame.Shape.NoFrame)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setStyleSheet("background:transparent;border:none;")
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._scene = QGraphicsScene(self)
        self._view.setScene(self._scene)
        self._proxy = QGraphicsProxyWidget()
        self._proxy.setWidget(self.note)
        self._rot = QGraphicsRotation()
        self._rot.setAxis(Qt.Axis.ZAxis)
        self._proxy.setTransformations([self._rot])
        # 注意：这里刻意**不**给代理控件挂 QGraphicsDropShadowEffect。
        # 原因：卡片本就被 resize 成与窗口等大，投影落在窗口外、被视口裁掉（不可见）；
        # 而 QGraphicsProxyWidget 上的图形特效会在**每一次重绘**（每次键入/悬停）把整张
        # 卡片渲染成 pixmap 再做高斯模糊 → 窗口是半透明分层窗口，代价极高，
        # 表现为「有时卡顿、点不动」（用户反馈）。去掉后外观无变化、交互恢复流畅。
        self._scene.addItem(self._proxy)

    def _build_grips(self):
        m = 7
        self.grip_left = ResizeGrip(self, ("left",), QCursor(Qt.CursorShape.SizeHorCursor))
        self.grip_right = ResizeGrip(self, ("right",), QCursor(Qt.CursorShape.SizeHorCursor))
        self.grip_bottom = ResizeGrip(self, ("bottom",), QCursor(Qt.CursorShape.SizeVerCursor))
        self.grip_bl = ResizeGrip(self, ("left", "bottom"), QCursor(Qt.CursorShape.SizeFDiagCursor))
        self.grip_br = ResizeGrip(self, ("right", "bottom"), QCursor(Qt.CursorShape.SizeBDiagCursor))
        self.grip_left.setGeometry(0, 0, m, self.height())
        self.grip_right.setGeometry(self.width() - m, 0, m, self.height())
        self.grip_bottom.setGeometry(m, self.height() - m, self.width() - 2 * m, m)
        self.grip_bl.setGeometry(0, self.height() - m, m, m)
        self.grip_br.setGeometry(self.width() - m, self.height() - m, m, m)

    # ---------- 显示后重新同步几何（消除初始底部裁切） ----------
    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        # 初次显示时布局尚未稳定，self.note 的最小尺寸会偏高（~404）把卡片顶出窗口、
        # 裁掉底部工具栏；待布局稳定后重新同步几何，让卡片恰好铺满窗口、不被裁剪。
        QApplication.processEvents()
        self._sync_geometry()
        QTimer.singleShot(0, self._sync_geometry)

    def eventFilter(self, obj, event):  # noqa: N802
        et = event.type()
        # 三按钮 hover：切换图标配色（对齐 HTML hover:text-green/orange/red）
        if obj in (self.btn_complete, self.btn_pin, self.btn_close):
            role = obj.property("role")
            if et == QEvent.Type.HoverEnter:
                obj.setIcon(QIcon(self._btn_icon(role, True)))
                return False
            if et == QEvent.Type.HoverLeave:
                obj.setIcon(QIcon(self._btn_icon(role, False)))
                return False
        # 拖拽移动：顶部栏空白区 或 卡片背景（非按钮/输入框/正文）均可抓取。
        # 早期只有 24px 顶部细条能拖，用户抓卡片主体却拖不动 → 体验「吃力」。
        # 改用「按下即 grabMouse + 全局鼠标追踪」的手动拖拽，比 startSystemMove 在
        # Frameless+置顶+代理旋转控件下更可靠、且整张卡片任意空白都能抓。
        if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if not self._locked:
                draggable = False
                if obj is self.bar:
                    child = self.bar.childAt(event.position().toPoint())
                    draggable = (child is None or child is self.bar)
                elif obj is self.note:
                    # 仅当按在卡片背景（标题/正文/按钮都不是）→ 才能拖，避免抢走文本编辑
                    child = self.note.childAt(event.position().toPoint())
                    draggable = (child is None or child is self.note)
                if draggable:
                    gp = (event.globalPosition().toPoint()
                          if hasattr(event, "globalPosition") else event.globalPos())
                    self._drag = {"start_global": gp, "start_pos": self.pos()}
                    self.grabMouse()
            return False
        # 便签卡片任意位置右键：弹出统一的自绘菜单（含标题、内容、工具栏；
        # 拦截 QLineEdit/QTextEdit 的原生右键菜单，保证与设计完全一致）
        if et == QEvent.Type.ContextMenu and isinstance(obj, QWidget) \
                and (obj is self.note or self.note.isAncestorOf(obj)):
            # 右键落在标题 → 编辑动作作用于标题输入框；落在内容（含 QTextEdit 的
            # viewport）→ 作用于富文本编辑器；落在卡片空白 → 默认内容编辑器。
            target = self.title if obj is self.title else self.editor.editor
            self._show_sticky_menu(event, target)
            return True
        return super().eventFilter(obj, event)

    # ---------- 手动拖拽（按下即 grabMouse，全局追踪鼠标） ----------
    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag is not None and not self._locked:
            gp = (e.globalPosition().toPoint()
                  if hasattr(e, "globalPosition") else e.globalPos())
            delta = gp - self._drag["start_global"]
            self.move(self._drag["start_pos"] + delta)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self._drag is not None:
            self._drag = None
            self.releaseMouse()
            return
        super().mouseReleaseEvent(e)

    # ---------- 完成（确认键）：双向同步 ----------
    def toggle_done(self):
        cur = todo.get_task(self.task_id)
        if cur is None:
            return
        new = not cur["done"]
        todo.set_done(self.task_id, new)
        self.todo_window._render()   # 刷新列表项划线/颜色
        self.sync_state()            # 刷新本窗口标题与确认键
        if new:
            speak_later(config.character.system_func.get("todo", {}).get("complete", "嘻嘻，任务完成捏"))

    def sync_state(self):
        """根据任务最新 done 状态刷新：标题删除线+颜色、确认键图标。"""
        cur = todo.get_task(self.task_id)
        self._done = bool(cur["done"]) if cur else False
        f = self.title.font()
        f.setStrikeOut(self._done)
        self.title.setFont(f)
        self.title.setStyleSheet(self._title_qss(self._done))
        self.btn_complete.setIcon(QIcon(self._btn_icon("complete", False)))
        self.btn_complete.setIconSize(QSize(20, 20))

    def _title_qss(self, done):
        # HTML：text-xl(20px) font-medium(500) title-underline(2px #d8d8d8) pb-1(4px)
        # 完成时 line-through + opacity-70（用灰色近似）
        color = "#9ca3af" if done else "#1f2937"
        return (
            "QLineEdit#stickyTitle{background:transparent;border:none;"
            "border-bottom:2px solid #d8d8d8;font-size:20px;font-weight:500;"
            f"color:{color};padding:0 2px 4px 2px;}}"
            "QLineEdit#stickyTitle:focus{border-bottom-color:#F97316;}"
        )

    # ---------- 置顶 = 锁定不可移动/缩放 ----------
    def toggle_pin(self):
        self._locked = not self._locked
        self.btn_pin.setIcon(QIcon(self._btn_icon("pin", False)))
        self.btn_pin.setIconSize(QSize(20, 20))

    def _btn_icon(self, role, hovered):
        """三按钮图标（严格对齐 HTML 的 text-gray-600 / hover 配色 / 完成绿 / 置顶橙）。"""
        if role == "complete":
            if self._done:
                return svg_icon("check_fill", 20)            # 实心绿圆白勾
            return svg_icon("check", 20, "#16A34A" if hovered else "#4B5563")
        if role == "pin":
            return svg_icon("pin", 20, "#F9730F" if (hovered or self._locked) else "#4B5563")
        # close：默认灰色，hover 红色
        return svg_icon("close", 20, "#EF4444" if hovered else "#6B7280")

    # ---------- 背景色 ----------
    def set_bg(self, color):
        self._bg = QColor(color)
        # HTML rounded-lg = 8px
        self.note.setStyleSheet(
            f"QWidget#stickyNote{{background:{self._bg.name()};border-radius:8px;}}")

    # ---------- 右键菜单 ----------
    def _show_sticky_menu(self, event, target=None):
        event.accept()
        self._sticky_menu = StickyContextMenu(self, self, target).show_at(event.globalPos())

    # ---------- 复制 / 清空 / 改标题 ----------
    def copy_task(self):
        """复制任务：新建一个标题/内容完全相同的任务，并在任务清单同步出现后打开其便签。
        按用户要求「就新开一个这个界面……任务清单那边也同步新开与之对应好的」。
        返回新建任务的 id，便于调用方（如测试/联动）定位。"""
        title = self.title.text().strip() or tr("未命名")
        content_html = self.editor.to_html()
        new_task = todo.add(title, content_html, remind=None, alarm_id=None, priority="中")
        self.todo_window._render()              # 任务清单同步新增条目
        # base=self：新便签相对当前这张错开摆放，避免完全重叠让人以为没复制
        self.todo_window.open_sticky(new_task, base=self)
        return new_task["id"]

    def clear_content(self):
        self.title.clear()
        self.editor.clear()

    def _on_title_edited(self):
        todo.set_note(self.task_id, self.title.text().strip() or tr("未命名"),
                      self.editor.to_html())
        self.todo_window._render()

    # ---------- 几何 / 旋转同步 ----------
    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._view.setGeometry(0, 0, self.width(), self.height())
        m = 7
        self.grip_left.setGeometry(0, 0, m, self.height())
        self.grip_right.setGeometry(self.width() - m, 0, m, self.height())
        self.grip_bottom.setGeometry(m, self.height() - m, self.width() - 2 * m, m)
        self.grip_bl.setGeometry(0, self.height() - m, m, m)
        self.grip_br.setGeometry(self.width() - m, self.height() - m, m, m)
        self._sync_geometry()

    def _sync_geometry(self):
        w, h = self.width(), self.height()
        self.note.resize(w, h)
        self._rot.setOrigin(QVector3D(w / 2.0, h / 2.0, 0.0))
        # pad=0：卡片与窗口等大、且已无投影需要外扩；sceneRect 与视口一致后
        # 视图滚动区间为 0，配合 _StickyView 彻底杜绝「滚轮把卡片顶偏」。
        pad = 0
        rect = QRectF(-pad, -pad, w + 2 * pad, h + 2 * pad)
        self._scene.setSceneRect(rect)
        self._view.setSceneRect(rect)
        self._view.centerOn(w / 2.0, h / 2.0)

    # ---------- 关闭：回写内容并解除注册（注意：关闭便签≠删除任务） ----------
    def closeEvent(self, e):  # noqa: N802
        todo.set_note(self.task_id, self.title.text().strip() or tr("未命名"),
                      self.editor.to_html())
        self.todo_window.unregister_sticky(self.task_id)
        self.todo_window._render()
        super().closeEvent(e)
