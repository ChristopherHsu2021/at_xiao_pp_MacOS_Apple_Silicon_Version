"""富文本编辑器组件：工具栏 + QTextEdit，复刻 index.html 的设计与功能。

仅依赖 PyQt6（含 QtSvg）。工具栏按钮在点击时保持编辑器选区（NoFocus + 操作后回焦），
外观（橙色主题、激活态）通过 QSS 还原 index.html 的 .tb-btn / .editor 样式。
"""

import sys

from PyQt6.QtCore import (
    Qt, QByteArray, QSize, QPoint, QRect, QRectF, QEvent, pyqtSignal, QTimer,
)
from PyQt6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QFont, QFontMetrics, QTextCursor,
    QTextCharFormat, QTextBlockFormat, QTextListFormat, QTextFormat,
    QLinearGradient, QBrush, QPen, QFontDatabase,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QPushButton, QLabel, QComboBox,
    QColorDialog, QTextEdit, QFrame, QSizePolicy, QLayout, QApplication,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle, QGraphicsDropShadowEffect,
)

from app.ui.common import promote_popup_topmost, EditContextMenu, guard_ui
from app.core.i18n import tr
from app.ui.screen_fit import scale_qss, s

# 工具栏图标（与 index.html 同源 SVG path，统一描边风格）
_ICONS = {
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "bold": '<path d="M7 5h6a3.5 3.5 0 0 1 0 7H7zM7 12h7a3.5 3.5 0 0 1 0 7H7z"/>',
    "italic": '<path d="M10 5h9M6 19h9M14 5l-4 14"/>',
    "underline": '<path d="M7 5v6a5 5 0 0 0 10 0V5"/><path d="M5 21h14"/>',
    "strike": '<path d="M8 5h8M12 5v6M6 12h12M12 12v7M9 19h6"/>',
    "ul": '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1.2" fill="currentColor" stroke="none"/><circle cx="4.5" cy="12" r="1.2" fill="currentColor" stroke="none"/><circle cx="4.5" cy="18" r="1.2" fill="currentColor" stroke="none"/>',
    "ol": '<path d="M10 6h11M10 12h11M10 18h11"/><path d="M4 5v3M3 5h2M4 8l-1.5 2M4 8l1.5 2M4 19h-1a1 1 0 0 1 0-2h1v-2"/>',
    "quote": '<path d="M5 12h4l-1 4H5zM12 12h4l-1 4h-3z" stroke-width="1.6"/><path d="M7 7l-2 5M14 7l-2 5" stroke-width="1.4"/>',
    "left": '<path d="M4 6h16M4 10h10M4 14h16M4 18h10"/>',
    "center": '<path d="M4 6h16M7 10h10M4 14h16M7 18h10"/>',
    "right": '<path d="M4 6h16M10 10h10M4 14h16M10 18h10"/>',
    "link": '<path d="M10 14a4 4 0 0 0 6.2.5l3-3a4 4 0 0 0-5.7-5.7l-1.5 1.5"/><path d="M14 10a4 4 0 0 0-6.2-.5l-3 3a4 4 0 0 0 5.7 5.7l1.5-1.5"/>',
    # 清除格式：橡皮擦（对齐参考 HTML 的 fa-eraser）
    "clear": '<path d="M13.5 5.5l5 5-8 8H7l-3.5-3.5z"/><path d="M5 20h14"/>',
    "hili": '<path d="M9 11l6-6 4 4-6 6M8 12l-3 3 4 4 3-3"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5 5-5"/>',
    # 已完成：实心圆 + 白勾（对齐 fa-check-circle，绿色 #16A34A）
    "check_fill": ('<circle cx="12" cy="12" r="9.5" fill="#16A34A" stroke="none"/>'
                   '<path d="M8 12.5l2.6 2.6 5-5.2" fill="none" stroke="#fff" stroke-width="2.1"/>'),
    "pin": '<path d="M12 17v4"/><path d="M7.5 3h9l-1 6 3 3H5.5l3-3-1-6z"/>',
    # 文字颜色：字母 F（对齐参考 HTML 的 fa-font）
    "font": '<path d="M7 4h10M7 4v16M7 11h7"/>',
}


# 图标缓存：同一 (key,size,color) 只渲染一次。
# 原实现每次调用都要 QSvgRenderer 解析 + QPainter 重绘；工具栏 hover/激活态切换频繁，
# 在便签（半透明置顶窗）里会造成可感知的卡顿。
_ICON_CACHE: dict = {}


def svg_icon(key: str, size: int = 17, color: str = "#6b5744") -> QIcon:
    """把 _ICONS 里的 SVG path 渲染成 QIcon（橙色主题描边）。结果按参数缓存。"""
    _ck = (key, size, color)
    _hit = _ICON_CACHE.get(_ck)
    if _hit is not None:
        return _hit
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.9" '
        f'stroke-linecap="round" stroke-linejoin="round">{_ICONS[key]}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    px = max(16, size)
    pix = QPixmap(px, px)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    _icon = QIcon(pix)
    _ICON_CACHE[_ck] = _icon
    return _icon


def swatch_pixmap(size: int = 18, color: QColor | None = None) -> QPixmap:
    """文字颜色按钮用的色块（对齐 index.html 的 .color-swatch）。"""
    base = QColor(color) if color is not None and QColor(color).isValid() else QColor("#F97316")
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, base)
    grad.setColorAt(1.0, base.lighter(155))
    painter.setPen(QPen(QColor("#EBD9C2"), 1))
    painter.setBrush(QBrush(grad))
    painter.drawRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), 5, 5)
    painter.end()
    return pix


# ---------- 字体 / 字号 下拉数据 ----------

FONT_PLACEHOLDER = "字体"
SIZE_PLACEHOLDER = "字号"

# 语义预设（对齐 index.html 的 6 个 option）：名称 → 候选字体族。
# Qt 的 setFontFamilies 会取候选里第一个系统真实存在的字体。
def _prefer_platform_font(fams: list) -> list:
    """按平台重排字体候选：macOS 优先 PingFang SC / Songti SC / STKaiti / Menlo，
    Windows 优先 Microsoft YaHei，Linux 优先 Noto Sans CJK SC；其余保持原序。

    setFontFamilies 会取候选里第一个系统真实存在的字体，故把平台原生中文字体
    前置即可在对应系统上优先命中，避免回退到缺失的 Microsoft YaHei 触发告警。
    """
    if sys.platform == "darwin":
        prefer = ("PingFang SC", "Songti SC", "STKaiti", "Menlo")
    elif sys.platform == "win32":
        prefer = ("Microsoft YaHei",)
    else:
        prefer = ("Noto Sans CJK SC",)
    head = [f for f in fams if f in prefer]
    tail = [f for f in fams if f not in prefer]
    return head + tail


FONT_PRESETS = [
    ("无衬线", _prefer_platform_font(["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
                "Noto Sans SC", "Segoe UI", "Arial"])),
    ("衬线", _prefer_platform_font(["SimSun", "Songti SC", "Times New Roman", "Georgia"])),
    ("苹方 / 雅黑", _prefer_platform_font(["PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei"])),
    ("楷体", _prefer_platform_font(["KaiTi", "STKaiti", "楷体"])),
    ("宋体", _prefer_platform_font(["SimSun", "Songti SC", "宋体"])),
    ("等宽", _prefer_platform_font(["Consolas", "Cascadia Mono", "Menlo", "Courier New"])),
]

# 中文字号（号数 → 磅值），取值与 Word 一致
CN_FONT_SIZES = [
    ("初号", 42), ("小初", 36), ("一号", 26), ("小一", 24), ("二号", 22),
    ("小二", 18), ("三号", 16), ("小三", 15), ("四号", 14), ("小四", 12),
    ("五号", 10.5), ("小五", 9),
]

# 常用数字磅值
PT_FONT_SIZES = [8, 9, 10, 10.5, 11, 12, 14, 16, 18, 20, 22, 24,
                 26, 28, 32, 36, 42, 48, 56, 64, 72]


def _has_cjk(name: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in name)


def _font_sort_key(name: str):
    """中文字体排前面（按拼音），西文字体排后面（按字母序）。

    pypinyin 未安装时退化为按原字符串排序（不抛异常，保证下拉永远能打开）。
    """
    if _has_cjk(name):
        try:
            from pypinyin import lazy_pinyin
            return (0, "".join(lazy_pinyin(name)), name)
        except Exception:  # noqa: BLE001
            return (0, name, name)
    return (1, name.lower(), name.lower())


def system_font_families():
    """系统里除预设之外的全部字体族（中文优先 + 拼音排序）。"""
    preset_first = {fams[0] for _, fams in FONT_PRESETS}
    try:
        families = [f for f in QFontDatabase.families() if f]
    except Exception:  # noqa: BLE001
        families = []
    return sorted({f for f in families if f not in preset_first}, key=_font_sort_key)


def size_choices():
    """字号下拉项：[(显示名, 磅值)]，中文号数 + 数字磅值（不附带 pt / 像素单位，与 HTML 一致）。"""
    items = [(name, pt) for name, pt in CN_FONT_SIZES]
    items.extend(("%g" % pt, pt) for pt in PT_FONT_SIZES)
    return items


class ElideItemDelegate(QStyledItemDelegate):
    """下拉项委托：文字放不下时显示「…」；鼠标悬停该项时自动横向滑动，把整条文字看全。

    Qt 默认的下拉项只做硬裁切（连省略号都没有），长字体名（如 Microsoft YaHei UI）
    在窄下拉里完全看不出后半段。这里自绘文本 + 定时器位移，实现「悬停滑动展示全文」。
    """

    INTERVAL = 28   # ms
    STEP = 2        # px / 帧
    PAD_X = 8       # 与 QSS `::item{padding:0 8px}` 对齐

    def __init__(self, parent=None):
        super().__init__(parent)
        self._row = -1
        self._offset = 0
        self._max = 0
        self._dir = 1
        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL)
        self._timer.timeout.connect(self._tick)

    # ---- 悬停状态 ----
    def hover_row(self):
        return self._row

    def set_hover(self, row, overflow):
        """row = 悬停项行号（-1 表示无）；overflow = 文字超出可用宽度的像素数。"""
        row = int(row)
        if row != self._row:
            self._row = row
            self._offset = 0
            self._dir = 1
        self._max = max(0, int(overflow))
        if self._max > 0:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self._repaint()

    def stop(self):
        self._timer.stop()
        self._row = -1
        self._offset = 0
        self._max = 0
        self._dir = 1

    def _tick(self):
        if self._max <= 0:
            self._timer.stop()
            return
        self._offset += self.STEP * self._dir
        if self._offset >= self._max:
            self._offset = self._max
            self._dir = -1
        elif self._offset <= 0:
            self._offset = 0
            self._dir = 1
        self._repaint()

    def _repaint(self):
        view = self.parent()
        if view is not None and hasattr(view, "viewport"):
            view.viewport().update()

    # ---- 绘制 ----
    def sizeHint(self, option, index):  # noqa: N802
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(26, size.height()))

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        # 先问样式「文本该落在哪」（自动包含 QSS ::item 的内边距），再清空文本只画背景/选中态
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
        if not rect.isValid() or rect.width() <= 0:
            rect = opt.rect.adjusted(self.PAD_X, 0, -self.PAD_X, 0)
        opt.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        if rect.width() <= 0:
            return
        fm = QFontMetrics(opt.font)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setClipRect(opt.rect)
        painter.setFont(opt.font)
        painter.setPen(QColor("#EA6A1F") if selected else QColor("#3d2b1f"))
        if index.row() == self._row and self._max > 0:
            # 悬停中：整条文字横向滑动，首尾往复
            width = fm.horizontalAdvance(text) + 2
            painter.drawText(
                QRect(rect.x() - self._offset, rect.y(), width, rect.height()),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        else:
            painter.drawText(
                rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                fm.elidedText(text, Qt.TextElideMode.ElideRight, rect.width()))
        painter.restore()


class TopComboBox(QComboBox):
    """下拉选择框（字体 / 字号）。

    1) 弹出后把列表顶到 TopMost 最上层（卡片常驻置顶，否则列表会被压住）；
    2) 关闭态文字放不下时显示「…」，鼠标悬停时自动横向滑动展示全文；
    3) 列表项同理：放不下显示「…」，悬停该项时滑动展示全文。
    """

    INTERVAL = 28
    STEP = 2
    PAD_LEFT = 8    # 与 QSS `padding:0 22px 0 8px` 对齐
    PAD_RIGHT = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self._offset = 0
        self._overflow = 0
        self._dir = 1
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(self.INTERVAL)
        self._hover_timer.timeout.connect(self._tick_hover)
        self.setMouseTracking(True)
        # 列表项：自绘委托 + 悬停跟踪
        view = self.view()
        self._delegate = ElideItemDelegate(view)
        view.setItemDelegate(self._delegate)
        view.setMouseTracking(True)
        view.viewport().setMouseTracking(True)
        view.viewport().installEventFilter(self)

    # ---------- 列表：悬停滑动 ----------
    def eventFilter(self, obj, event):  # noqa: N802
        view = self.view()
        if obj is view.viewport():
            et = event.type()
            if et == QEvent.Type.MouseMove:
                idx = view.indexAt(event.position().toPoint())
                if idx.row() != self._delegate.hover_row():
                    text = str(idx.data(Qt.ItemDataRole.DisplayRole) or "") if idx.isValid() else ""
                    fm = QFontMetrics(view.font())
                    avail = max(0, obj.width() - 2 * ElideItemDelegate.PAD_X)
                    self._delegate.set_hover(idx.row() if idx.isValid() else -1,
                                             fm.horizontalAdvance(text) - avail)
            elif et in (QEvent.Type.Leave, QEvent.Type.Hide):
                self._delegate.set_hover(-1, 0)
        return super().eventFilter(obj, event)

    # ---------- 关闭态：悬停滑动 ----------
    def _button_text(self) -> str:
        idx = self.currentIndex()
        return self.itemText(idx) if idx >= 0 else ""

    def _text_rect(self):
        return self.rect().adjusted(self.PAD_LEFT, 0, -self.PAD_RIGHT, 0)

    def _text_overflow(self):
        fm = QFontMetrics(self.font())
        return max(0, fm.horizontalAdvance(self._button_text()) - self._text_rect().width())

    def enterEvent(self, e):  # noqa: N802
        super().enterEvent(e)
        self._overflow = self._text_overflow()
        if self._overflow > 0 and not self._hover_timer.isActive():
            self._hover_timer.start()

    def leaveEvent(self, e):  # noqa: N802
        super().leaveEvent(e)
        self._hover_timer.stop()
        self._offset = 0
        self.update()

    def _tick_hover(self):
        if self._overflow <= 0:
            self._hover_timer.stop()
            return
        self._offset += self.STEP * self._dir
        if self._offset >= self._overflow:
            self._offset = self._overflow
            self._dir = -1
        elif self._offset <= 0:
            self._offset = 0
            self._dir = 1
        self.update()

    # ---------- 绘制：省略号 / 滑动 ----------
    def paintEvent(self, e):  # noqa: N802
        super().paintEvent(e)
        text = self._button_text()
        rect = self._text_rect()
        if not text or rect.width() <= 0:
            return
        fm = QFontMetrics(self.font())
        overflow = max(0, fm.horizontalAdvance(text) - rect.width())
        offset = min(self._offset, overflow) if self._overflow == overflow else 0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 擦掉 Qt 默认绘制的（被硬裁切的）文字，再自绘省略号 / 滑动文本
        painter.fillRect(rect.adjusted(-2, 1, 2, -1), QColor("#FFFFFF"))
        painter.setPen(QColor("#6b5744"))
        painter.setFont(self.font())
        painter.setClipRect(rect)
        if offset <= 0:
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                             fm.elidedText(text, Qt.TextElideMode.ElideRight, rect.width()))
        else:
            painter.drawText(QRect(rect.x() - offset, rect.y(),
                                   fm.horizontalAdvance(text) + 2, rect.height()),
                             int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        painter.end()

    def showPopup(self):  # noqa: N802
        super().showPopup()
        QTimer.singleShot(0, promote_popup_topmost)


class FlowLayout(QLayout):
    """自动换行的流式布局，复刻 index.html `.toolbar{flex-wrap:wrap}` 的行为。

    Qt 没有内置流式布局：窗口一窄，固定单行的 QHBoxLayout 会把右侧按钮直接裁掉，
    这正是「窄宽度下工具栏/布局显示不全」的根因。此处按行排布并返回真实高度，
    配合 `_FlowToolbar` 同步自身高度，保证任何宽度下所有按钮都可见。
    """

    def __init__(self, parent=None, margin=0, h_spacing=4, v_spacing=4):
        super().__init__(parent)
        self._items = []
        self._h = h_spacing
        self._v = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._do_layout(QRect(0, 0, max(1, width), 0), test_only=True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(self._hint(item))
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    @staticmethod
    def _hint(item):
        """控件尺寸提示：按 maximumWidth/minimumWidth 夹紧。

        字体/字号下拉框自身 sizeHint 由最长项（如 Microsoft YaHei UI）撑到 ~190px，
        不夹紧就会无视 maxWidth 把框撑宽、并让换行判断偏早。此处夹紧即可。
        """
        hint = item.sizeHint()
        mn = item.minimumSize()
        mx = item.maximumSize()
        return QSize(max(mn.width(), min(hint.width(), mx.width())),
                     max(mn.height(), min(hint.height(), mx.height())))

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        rows, row, x = [], [], eff.x()
        for item in self._items:
            hint = self._hint(item)
            if row and x + hint.width() > eff.right() + 1:
                rows.append(row)
                row = []
                x = eff.x()
            row.append((item, x, hint.width(), hint.height()))
            x += hint.width() + self._h
        if row:
            rows.append(row)
        y = eff.y()
        for row in rows:
            line_h = max(h for _, _, _, h in row)
            for item, ix, w, h in row:
                if not test_only:
                    item.setGeometry(QRect(QPoint(ix, y + (line_h - h) // 2), QSize(w, h)))
            y += line_h + self._v
        if not rows:
            return m.top() + m.bottom()
        return y - self._v - rect.y() + m.bottom()


class FlowToolbar(QFrame):
    """工具栏容器：按宽度换行，并把自身高度同步为流式布局的实际高度。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("reToolbar")
        self.flow = FlowLayout(self)
        self.flow.setContentsMargins(s(10), s(8), s(10), s(8))
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        policy.setVerticalPolicy(QSizePolicy.Policy.Minimum)
        self.setSizePolicy(policy)
        # ★ 渐进显示上限（2026-09-21 便签新需求）：None = 不限制（完整模式编辑器
        #   照旧，工具栏始终全高）；设为整数后工具栏实际高度不得超过该值 —— 超出
        #   的按钮部分被裁掉，由便签窗口随「下拉增高」逐步放宽上限，实现
        #   「默认尺寸下不显示工具栏、拉大窗口才慢慢长出来」的效果。
        self._reveal_cap = None

    def set_reveal_cap(self, cap):
        """设置/解除渐进显示上限（None=解除，恢复完整高度）。

        内部做了去重：cap 未变化时不重复 setFixedHeight，避免拖拽缩放窗口时
        每个像素都触发一次布局抖动。
        """
        if cap is not None:
            cap = max(0, int(cap))
        if cap == self._reveal_cap:
            return
        self._reveal_cap = cap
        self._sync_height()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._sync_height()

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self._sync_height()

    def _sync_height(self):
        needed = self.flow.heightForWidth(self.width())
        # ★ 渐进显示：先按上限裁剪，再做固定高度同步（0 = 整条工具栏隐藏）。
        if self._reveal_cap is not None:
            needed = min(needed, self._reveal_cap)
        if needed > 0:
            if self.height() != needed:
                self.setFixedHeight(needed)
        else:
            self.setFixedHeight(0)


class RichEditor(QWidget):
    """编辑器聚焦/失焦通知（供外层给边框加高亮，替代不支持的 :focus-within）。

    compact=True 时只保留便签卡片所需的 11 个按钮（加粗/斜体/下划线/删除线/
    项目符号/编号/左对齐/居中/文字颜色/高亮/清除格式），隐藏撤销重做、字体、字号、
    引用、右对齐、插入链接及其分隔线，且不加分隔线 —— 与参考 HTML 的工具栏完全一致。
    """

    focusIn = pyqtSignal()
    focusOut = pyqtSignal()

    def __init__(self, parent=None, compact=False):
        super().__init__(parent)
        self._compact = compact
        # ★ 防御：紧凑模式下 add_cmd/build_color_buttons 会先把本对象作为事件过滤器
        #   装到工具栏按钮上（见 _build_ui 第 551/580/585 行），而 self.editor（QTextEdit）
        #   要在更后面（第 675 行）才赋值。若此时有事件同步投递到这些按钮，eventFilter
        #   会因访问尚不存在的 self.editor 而抛 AttributeError（点击任务清单标题新建便签时
        #   必现崩溃）。先置 None，让属性始终存在、比较安全。
        self.editor = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(s(0), s(0), s(0), s(0))
        root.setSpacing(s(0))

        # ---- 工具栏（窄宽度自动换行，保证按钮全部可见） ----
        self.toolbar = FlowToolbar()
        tb = self.toolbar.flow

        self._cmd_buttons = {}
        # 紧凑模式（便签卡片）对齐参考 HTML：28px 按钮 / 4px 圆角 / 灰色图标 / hover 灰底
        btn_size = 28 if self._compact else 32
        icon_sz = 16 if self._compact else 17
        icon_color = "#374151" if self._compact else "#6b5744"
        # 供 _apply_btn_icon 复用（紧凑模式 hover/激活态要按 全选按钮 的橙色重绘图标）
        self._icon_sz = icon_sz
        self._icon_color = icon_color
        self._btn_size = btn_size

        # 记录「按钮 cmd → 未翻译的简体中文提示语」：语言切换时 retranslate() 需要它
        # 逐个重新翻译（否则切语言后旧语言的工具提示会残留）。
        self._cmd_tip_keys = {}

        def add_cmd(key, tooltip, compact_hide=False):
            if self._compact and compact_hide:
                return None
            btn = QPushButton()
            btn.setObjectName("reBtn")
            btn.setToolTip(tr(tooltip))
            self._cmd_tip_keys[key] = tooltip
            btn.setIcon(svg_icon(key, icon_sz, icon_color))
            btn.setIconSize(QSize(icon_sz, icon_sz))
            btn.setFixedSize(btn_size, btn_size)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setProperty("cmd", key)
            btn.clicked.connect(lambda _=False, k=key: self._on_cmd(k))
            if self._compact:
                # 紧凑模式：hover / 激活态图标要跟着变橙（QSS 只能改底色，图标需自行重绘）
                btn.installEventFilter(self)
            tb.addWidget(btn)
            self._cmd_buttons[key] = btn
            return btn

        def add_sep():
            if not self._compact:
                self._sep(tb)

        def build_color_buttons():
            """文字颜色 / 高亮：紧凑模式用 fa-font / fa-highlighter 图标（灰）；
            完整模式用渐变色块（swatch）以贴合添加/编辑页设计。"""
            self._fore_color = QColor("#F97316")
            self.fore_btn = QPushButton()
            self.fore_btn.setToolTip(tr("文字颜色"))
            self.fore_btn.setFixedSize(btn_size, btn_size)
            self.fore_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.fore_btn.clicked.connect(self._on_fore_color)
            self._hili_color = QColor("#FFE066")
            self.hili_btn = QPushButton()
            self.hili_btn.setToolTip(tr("高亮/标记"))
            self.hili_btn.setFixedSize(btn_size, btn_size)
            self.hili_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.hili_btn.clicked.connect(self._on_hili_color)
            if self._compact:
                self.fore_btn.setObjectName("reBtn")
                self.fore_btn.setProperty("cmd", "font")
                self.fore_btn.setIcon(svg_icon("font", icon_sz, icon_color))
                self.fore_btn.setIconSize(QSize(icon_sz, icon_sz))
                self.fore_btn.installEventFilter(self)
                self.hili_btn.setObjectName("reBtn")
                self.hili_btn.setProperty("cmd", "hili")
                self.hili_btn.setIcon(svg_icon("hili", icon_sz, icon_color))
                self.hili_btn.setIconSize(QSize(icon_sz, icon_sz))
                self.hili_btn.installEventFilter(self)
            else:
                self.fore_btn.setObjectName("reColor")
                self.fore_btn.setIcon(QIcon(swatch_pixmap(18, self._fore_color)))
                self.fore_btn.setIconSize(QSize(s(18), s(18)))
                self.hili_btn.setObjectName("reHili")
                self.hili_btn.setIcon(svg_icon("hili", 17, "#8A7358"))
                self.hili_btn.setIconSize(QSize(s(17), s(17)))
            tb.addWidget(self.fore_btn)
            tb.addWidget(self.hili_btn)

        if self._compact:
            # 参考 HTML 工具栏顺序：B I U S · 项目符号 编号 · 左 中 · 字色 高亮 · 清除
            tb.setContentsMargins(s(0), s(12), s(0), s(0))   # 对齐 HTML 的 border-t pt-3
            add_cmd("bold", "加粗")
            add_cmd("italic", "斜体")
            add_cmd("underline", "下划线")
            add_cmd("strike", "删除线")
            add_cmd("ul", "项目符号列表")
            add_cmd("ol", "编号列表")
            add_cmd("left", "左对齐")
            add_cmd("center", "居中")
            build_color_buttons()
            add_cmd("clear", "清除格式")
        else:
            add_cmd("undo", "撤销")
            add_cmd("redo", "重做")
            add_sep()
            add_cmd("bold", "加粗")
            add_cmd("italic", "斜体")
            add_cmd("underline", "下划线")
            add_cmd("strike", "删除线")
            add_sep()
            # 字体：读取系统所有字体（预设 6 项 + 分隔线 + 系统字体族）
            self.sel_font = TopComboBox()
            self.sel_font.setObjectName("reSelect")
            self.sel_font.setToolTip(tr("字体"))
            self.sel_font.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.sel_font.setFixedHeight(s(32))
            # 收窄：字体名放不下时显示「…」，悬停自动滑动展示全文
            self.sel_font.setMinimumWidth(s(72))
            self.sel_font.setMaximumWidth(s(100))
            self.sel_font.setMaxVisibleItems(14)
            # 占位项也要跟随语言（原先写死简体中文 → 英文模式下显示「字体/字号」，
            # 这正是「编辑任务页中英混杂」的一个根因）。
            self.sel_font.addItem(tr(FONT_PLACEHOLDER))
            for label, fams in FONT_PRESETS:
                # 分类名（无衬线/衬线/等宽）跟随语言；字体专名（楷体/宋体…）不在表内 → 原样
                self.sel_font.addItem(tr(label), list(fams))
            system_fonts = system_font_families()
            if system_fonts:
                self.sel_font.insertSeparator(self.sel_font.count())
                for fam in system_fonts:
                    self.sel_font.addItem(fam, [fam])
            # 用 activated（仅用户操作触发）而非 currentTextChanged，
            # 避免处理函数里回填占位文案时再次触发自己。
            self.sel_font.activated.connect(self._on_font)
            tb.addWidget(self.sel_font)
            # 字号：中文号数（一号/小一…小五）+ 数字磅值
            self.sel_size = TopComboBox()
            self.sel_size.setObjectName("reSelect")
            self.sel_size.setToolTip(tr("字号"))
            self.sel_size.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.sel_size.setFixedHeight(s(32))
            # 与字体框同步收窄（字号文案短，够用即可）
            self.sel_size.setMinimumWidth(s(64))
            self.sel_size.setMaximumWidth(s(84))
            self.sel_size.setMaxVisibleItems(14)
            self.sel_size.addItem(tr(SIZE_PLACEHOLDER))
            for label, pt in size_choices():
                self.sel_size.addItem(label, pt)
            self.sel_size.activated.connect(self._on_size)
            tb.addWidget(self.sel_size)
            add_sep()
            build_color_buttons()
            add_sep()
            add_cmd("ul", "项目符号列表")
            add_cmd("ol", "编号列表")
            add_cmd("quote", "引用")
            add_sep()
            add_cmd("left", "左对齐")
            add_cmd("center", "居中")
            add_cmd("right", "右对齐")
            add_sep()
            add_cmd("link", "插入链接")
            add_cmd("clear", "清除格式")

        # 完整模式：工具栏在内容上方；紧凑模式（便签）严格对齐参考 HTML：
        # 内容在上、工具栏在下（bottom border-t + pt-3），故此处不添加。
        if not self._compact:
            root.addWidget(self.toolbar)

        # ---- 编辑区（自身可滚动，窗口主体不出滚动条） ----
        self.editor = QTextEdit()
        self.editor.setObjectName("reEditor")
        self.editor.setAcceptRichText(True)
        self.editor.setPlaceholderText(
            tr("在这里编辑任务详情") if self._compact
            else tr("在这里填写任务详情，可用上方工具栏排版…（可选）"))
        # ★ 2026-09-21 修「便签默认尺寸下看不到富文本工具栏」（用户意见附图实证）：
        #   紧凑模式（便签卡片）原来给正文一个 180px 的**硬最小高**，而便签的默认尺寸
        #   与最小尺寸是同一个值 320×280（screen_fit.WINDOW_DEFAULTS["sticky"]）。
        #   卡片内的竖向需求 = 上边距 16 + 顶部栏 19 + 间距 10 + 标题 29 + 间距 13
        #                    + 正文(≥180) + 间距 16 + 工具栏(窄宽度换行成 2 行 ≈72) + 下边距 16
        #                    = 371px > 280px → QVBoxLayout 无法压缩正文（已到最小高），
        #   整体溢出窗口，底部被裁掉——正好裁在工具栏上：用户看到第一行按钮，换行后的
        #   第二行（高亮/清除格式）只剩半个，且必须把窗口往下拉大才慢慢露出来。
        #   把紧凑模式正文最小高改成 56 设计像素（≈45px）后总需求降到 236px < 280px。
        #   ★ 2026-09-21 需求反转：便签默认尺寸下工具栏**不显示**，由便签窗口
        #   （StickyNoteWindow._update_toolbar_reveal）按下拉高度渐进露出 —— 见
        #   FlowToolbar.set_reveal_cap；正文最小高 s(56) 保证 280 高度下正文仍有
        #   可用的编辑空间，保持不变。完整模式（添加/编辑任务页）窗口高 606，
        #   180 不成问题，保持原值。
        self.editor.setMinimumHeight(s(56) if self._compact else 96)
        self.editor.currentCharFormatChanged.connect(self._sync_active)
        self.editor.cursorPositionChanged.connect(self._sync_active)
        self.editor.installEventFilter(self)
        # ★ 关键：QTextEdit 是 QAbstractScrollArea，右键的 ContextMenu 事件投递给它的
        #   viewport() 而不是 QTextEdit 本身 —— 过滤器只装在 QTextEdit 上永远收不到，
        #   Qt 于是弹出原生的英文菜单（Undo/Redo/Cut/…），与软件语言设置不一致。
        self.editor.viewport().installEventFilter(self)
        root.addWidget(self.editor, 1)

        # 紧凑模式：内容下方依次是 16px 间距（HTML 内容 mb-4）+ 工具栏（border-t pt-3）
        if self._compact:
            root.addSpacing(s(16))
            root.addWidget(self.toolbar)

        self.setStyleSheet(EDITOR_QSS_COMPACT if self._compact else EDITOR_QSS)

    def eventFilter(self, obj, event):  # noqa: N802
        """统一事件过滤器：焦点高亮 / Windows 排版快捷键 / 内容区右键菜单 / 紧凑按钮 hover。

        注意：早期版本在本类里定义了**两个** eventFilter，后定义者会覆盖前者（前者沦为死代码），
        导致焦点信号与快捷键拦截实际失效；此处合并为唯一实现，避免再次被覆盖。
        """
        et = event.type()

        # 1) 编辑区焦点变化 → 转成信号（供外层给边框加高亮）；
        #    并拦截 Windows 常用排版快捷键，显式调用既有处理（避免与 QTextEdit 原生重复触发）。
        if self.editor is not None and obj is self.editor:
            if et == QEvent.Type.FocusIn:
                self.focusIn.emit()
            elif et == QEvent.Type.FocusOut:
                self.focusOut.emit()
            elif et == QEvent.Type.KeyPress:
                if self._handle_shortcut(event):
                    return True
            return super().eventFilter(obj, event)

        # 2) 内容区右键：QTextEdit 是 QAbstractScrollArea，ContextMenu 事件投递给它的
        #    viewport() 而非 QTextEdit 本身，必须拦在 viewport 上，否则会弹出 Qt 原生
        #    英文菜单（Undo/Redo/...）。紧凑模式（便签卡片）的右键菜单由 StickyNoteWindow
        #    统一提供（含 复制任务/清空内容/便签背景），这里只在完整模式（添加/编辑页）接管。
        if (self.editor is not None and not self._compact
                and et == QEvent.Type.ContextMenu
                and isinstance(obj, QWidget) and obj is self.editor.viewport()):
            event.accept()
            # guard_ui：在事件过滤器里构造弹窗；一旦抛异常 PyQt6 会 qFatal 整个 App
            # （用户实测过右键内容框闪退）。套一层后最坏只是不弹菜单。
            self._edit_menu = guard_ui(
                "任务内容框右键菜单",
                lambda: EditContextMenu(self, self.editor).show_at(event.globalPos()))
            return True

        # 3) 紧凑模式工具栏按钮 hover：图标由灰转橙（与「全选」按钮 hover 配色一致）
        if self._compact and isinstance(obj, QPushButton) and obj.property("cmd"):
            if et == QEvent.Type.HoverEnter:
                self._apply_btn_icon(obj, hovered=True)
                return False
            if et == QEvent.Type.HoverLeave:
                self._apply_btn_icon(obj, hovered=False)
                return False

        return super().eventFilter(obj, event)

    def _handle_shortcut(self, event):
        """macOS 常用文字排版快捷键（选中文段后生效；⌘ 即 Cmd 键）：

        - ⌘B / ⌘I / ⌘U        → 加粗 / 斜体 / 下划线
        - ⌘⇧S（Shift+⌘S）     → 删除线
        - ⌘L / ⌘E / ⌘R        → 左对齐 / 居中 / 右对齐

        在事件过滤器里拦截并显式调用既有 _toggle_char / _on_cmd，
        同时返回 True 吞掉按键，避免 QTextEdit 原生快捷键再触发一次（否则会抵消）。
        """
        mods = event.modifiers()
        cmd = bool(mods & Qt.KeyboardModifier.MetaModifier)  # macOS：⌘(Cmd)；跨平台下 Meta=Cmd
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        key = event.key()
        if not cmd:
            return False
        if not shift and key == Qt.Key.Key_B:
            self._toggle_char("bold")
            return True
        if not shift and key == Qt.Key.Key_I:
            self._toggle_char("italic")
            return True
        if not shift and key == Qt.Key.Key_U:
            self._toggle_char("underline")
            return True
        if shift and key == Qt.Key.Key_S:
            self._toggle_char("strike")
            return True
        if not shift and key == Qt.Key.Key_L:
            self._on_cmd("left")
            return True
        if not shift and key == Qt.Key.Key_E:
            self._on_cmd("center")
            return True
        if not shift and key == Qt.Key.Key_R:
            self._on_cmd("right")
            return True
        return False

    @staticmethod
    def _sep(layout):
        line = QFrame()
        line.setObjectName("reSep")
        line.setFixedSize(s(1), s(20))
        layout.addWidget(line)

    # ---------- 命令处理 ----------
    def _on_cmd(self, key):
        ed = self.editor
        cur = ed.textCursor()
        if key == "undo":
            ed.undo()
        elif key == "redo":
            ed.redo()
        elif key in ("bold", "italic", "underline", "strike"):
            self._toggle_char(key)
        elif key == "ul":
            cur.createList(QTextListFormat.Style.ListDisc)
        elif key == "ol":
            cur.createList(QTextListFormat.Style.ListDecimal)
        elif key == "quote":
            self._toggle_quote()
        elif key in ("left", "center", "right"):
            flag = {
                "left": Qt.AlignmentFlag.AlignLeft,
                "center": Qt.AlignmentFlag.AlignHCenter,
                "right": Qt.AlignmentFlag.AlignRight,
            }[key]
            ed.setAlignment(flag)
            # 立即刷新按钮激活态：只点亮刚选中的那个对齐方式
            self._sync_active()
        elif key == "link":
            self._insert_link()
        elif key == "clear":
            self._clear_format()
        ed.setFocus()

    def _merge_char(self, fmt: QTextCharFormat):
        cur = self.editor.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.SelectionType.WordUnderCursor)
        cur.mergeCharFormat(fmt)
        self.editor.setTextCursor(cur)

    def _toggle_char(self, key):
        cur = self.editor.textCursor()
        f = cur.charFormat()
        fmt = QTextCharFormat()
        if key == "bold":
            w = f.fontWeight()
            fmt.setFontWeight(QFont.Weight.Normal if w >= QFont.Weight.Bold else QFont.Weight.Bold)
        elif key == "italic":
            fmt.setFontItalic(not f.fontItalic())
        elif key == "underline":
            fmt.setFontUnderline(not f.fontUnderline())
        elif key == "strike":
            fmt.setFontStrikeOut(not f.fontStrikeOut())
        self._merge_char(fmt)
        self._sync_active()

    def _toggle_quote(self):
        cur = self.editor.textCursor()
        bf = cur.blockFormat()
        new = QTextBlockFormat()
        if bf.leftMargin() > 4:
            new.setLeftMargin(0)
            new.setTopMargin(0)
            new.setBottomMargin(0)
        else:
            new.setLeftMargin(16)
            new.setTopMargin(4)
            new.setBottomMargin(4)
        cur.mergeBlockFormat(new)
        self.editor.setTextCursor(cur)

    def _insert_link(self):
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, tr("插入链接"), tr("请输入链接地址（https://…）"))
        if not (ok and text.strip()):
            return
        url = text.strip()
        cur = self.editor.textCursor()
        sel = cur.selectedText()
        cur.insertHtml(f'<a href="{url}">{sel if sel else url}</a>')
        self.editor.setTextCursor(cur)

    def _clear_format(self):
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Normal)
        fmt.setFontItalic(False)
        fmt.setFontUnderline(False)
        fmt.setFontStrikeOut(False)
        fmt.setForeground(QColor("#3d2b1f"))
        fmt.clearBackground()
        self._merge_char(fmt)

    def _on_font(self, index):
        """应用字体：下拉框保持显示所选项（如「楷体」），与 index.html 的 字体-->选中值 一致。"""
        if index <= 0:
            return
        families = self.sel_font.itemData(index)
        if families:
            fmt = QTextCharFormat()
            fmt.setFontFamilies(list(families))
            self._merge_char(fmt)
        # 不再回退占位文案：组合框显示当前选中的字体名（楷体等），选择即生效、即时渲染
        self.sel_font.setToolTip(tr("字体：%s") % self.sel_font.currentText())
        self.editor.viewport().update()
        self.editor.setFocus()

    def _on_size(self, index):
        """应用字号（中文号数 / 数字磅值）：下拉框保持显示所选项，与字体逻辑一致。"""
        if index <= 0:
            return
        pt = self.sel_size.itemData(index)
        if pt:
            fmt = QTextCharFormat()
            fmt.setFontPointSize(float(pt))
            self._merge_char(fmt)
        # 不再回退占位文案：组合框显示当前选中的字号，选择即生效、即时渲染
        self.sel_size.setToolTip(tr("字号：%s") % self.sel_size.currentText())
        self.editor.viewport().update()
        self.editor.setFocus()

    def _on_fore_color(self):
        # 用自绘紧凑取色弹窗替代原生 QColorDialog（Windows 原生对话框巨大且风格不符）
        self._popup_color(self.fore_btn, self._fore_color, self._apply_fore_color)

    def _on_hili_color(self):
        self._popup_color(self.hili_btn, self._hili_color, self._apply_hili_color)

    def _apply_fore_color(self, color):
        color = QColor(color)
        self._fore_color = color
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        self._merge_char(fmt)
        if not self._compact:   # 完整模式按钮是渐变色块，需刷新色块
            self.fore_btn.setIcon(QIcon(swatch_pixmap(18, self._fore_color)))
        self.editor.setFocus()

    def _apply_hili_color(self, color):
        color = QColor(color)
        self._hili_color = color
        fmt = QTextCharFormat()
        fmt.setBackground(color)
        self._merge_char(fmt)
        if not self._compact:
            self.hili_btn.setIcon(QIcon(swatch_pixmap(16, self._hili_color)))
        self.editor.setFocus()

    def _popup_color(self, anchor, initial, apply_cb):
        """在按钮下方弹出自绘紧凑调色板；点「自定义…」再开非原生 QColorDialog。"""
        pop = ColorPopup(QColor(initial))
        pop.picked.connect(apply_cb)
        pop.adjustSize()
        gp = anchor.mapToGlobal(anchor.rect().bottomLeft())
        pop.move(gp.x(), gp.y() + 4)
        pop.show()

    def _sync_active(self):
        ed = self.editor
        cf = ed.currentCharFormat()
        self._set_active("bold", cf.fontWeight() >= QFont.Weight.Bold)
        self._set_active("italic", cf.fontItalic())
        self._set_active("underline", cf.fontUnderline())
        self._set_active("strike", cf.fontStrikeOut())
        # 对齐：只有「用户显式设置过对齐」才点亮按钮，且只点亮被选中的那个。
        # 段落默认对齐的 Qt 值为 AlignLeft(1)，但它并未写入 BlockAlignment 属性
        # （实测 hasProperty(BlockAlignment)=False），据此区分「默认」与「显式左对齐」，
        # 消除「左对齐一直常亮」的问题（选的谁就谁常亮）。
        bf = ed.textCursor().blockFormat()
        if bf.hasProperty(QTextFormat.Property.BlockAlignment):
            al = bf.alignment()
            is_center = bool(al & Qt.AlignmentFlag.AlignHCenter)
            is_right = bool(al & Qt.AlignmentFlag.AlignRight)
            is_left = not is_center and not is_right
        else:
            is_left = is_center = is_right = False
        self._set_active("left", is_left)
        self._set_active("center", is_center)
        self._set_active("right", is_right)

    def _set_active(self, key, on):
        btn = self._cmd_buttons.get(key)
        if not btn:
            return
        on = bool(on)
        # _sync_active 会在每次光标移动/键入时跑（7 个按钮）；状态没变就早退，
        # 避免每次都 style().polish() + 重绘图标 → 便签窗口卡顿的诱因之一。
        if bool(btn.property("active")) == on:
            return
        btn.setProperty("active", on)
        btn.style().polish(btn)
        # 图标配色随状态重绘：紧凑模式橙/灰（对齐「全选」按钮 hover），完整模式白/棕
        self._apply_btn_icon(btn, hovered=btn.underMouse())

    def _apply_btn_icon(self, btn, hovered=False):
        """(重)绘制工具栏按钮图标。
        紧凑模式：hover 或激活 → 橙 #F97510，否则灰（与任务清单页「全选」按钮 hover 一致）；
        完整模式：激活 → 白，否则棕（沿用 index.html 主题）。"""
        key = btn.property("cmd")
        if not key:
            return
        on = bool(btn.property("active"))
        if self._compact:
            color = "#F97510" if (hovered or on) else self._icon_color
            btn.setIcon(svg_icon(key, self._icon_sz, color))
            btn.setIconSize(QSize(self._icon_sz, self._icon_sz))
        else:
            btn.setIcon(svg_icon(key, self._icon_sz, "#ffffff" if on else self._icon_color))
            btn.setIconSize(QSize(self._icon_sz, self._icon_sz))

    # ---------- 对外接口 ----------
    def to_html(self) -> str:
        return self.editor.toHtml()

    def _reset_selectors(self):
        if hasattr(self, "sel_font"):
            self.sel_font.setCurrentIndex(0)
            self.sel_font.setToolTip(tr("字体"))
        if hasattr(self, "sel_size"):
            self.sel_size.setCurrentIndex(0)
            self.sel_size.setToolTip(tr("字号"))
        self._sync_active()

    def retranslate(self):
        """语言切换后刷新编辑器内的全部界面文案。

        覆盖：字体/字号下拉的「占位项」与预设分类名、工具栏各按钮提示、色板按钮提示、
        编辑区占位文案。此前这些只在 __init__ 时取一次 tr()，切语言后旧语言文案会残留
        —— 表现为「编辑任务页中英混杂」（截图里 字体 / 字号 两处没翻译）。
        """
        if hasattr(self, "sel_font"):
            self.sel_font.setItemText(0, tr(FONT_PLACEHOLDER))
            for i, (label, _fams) in enumerate(FONT_PRESETS, start=1):
                if i < self.sel_font.count():
                    self.sel_font.setItemText(i, tr(label))
            self.sel_font.setToolTip(tr("字体"))
        if hasattr(self, "sel_size"):
            self.sel_size.setItemText(0, tr(SIZE_PLACEHOLDER))
            self.sel_size.setToolTip(tr("字号"))
        for key, btn in getattr(self, "_cmd_buttons", {}).items():
            zh = getattr(self, "_cmd_tip_keys", {}).get(key)
            if zh:
                btn.setToolTip(tr(zh))
        fore = getattr(self, "fore_btn", None)
        if fore is not None:
            fore.setToolTip(tr("文字颜色"))
        hili = getattr(self, "hili_btn", None)
        if hili is not None:
            hili.setToolTip(tr("高亮/标记"))
        self.editor.setPlaceholderText(
            tr("在这里编辑任务详情") if self._compact
            else tr("在这里填写任务详情，可用上方工具栏排版…（可选）"))

    def set_html(self, html: str):
        self.editor.setHtml(html or "")
        self._reset_selectors()

    def clear(self):
        self.editor.clear()
        self._reset_selectors()
        self._fore_color = QColor("#F97316")
        self._hili_color = QColor("#FFE066")
        self.fore_btn.setIcon(QIcon(swatch_pixmap(18, self._fore_color)))
        self.hili_btn.setIcon(svg_icon("hili", 17, "#8A7358"))

    def set_placeholder(self, text: str):
        self.editor.setPlaceholderText(text)


# 紧凑模式（便签卡片）样式：中性灰白视图；hover / 激活态改用与任务清单页
# 「全选」按钮 hover 一致的淡橙底（rgba(249,117,16,0.08) + #f97510），图标由代码重绘。
EDITOR_QSS_COMPACT = scale_qss("""
QFrame#reToolbar {
    background: transparent; border: none; border-top: 1px solid #e5e7eb;
}
QPushButton#reBtn {
    border: none; background: transparent; border-radius: 4px; padding: 0;
}
/* hover / 激活(锁定)配色对齐任务清单页「全选」按钮的 hover：淡橙底 + 橙图标 */
QPushButton#reBtn:hover { background: rgba(249,117,16,0.08); }
QPushButton#reBtn[active="true"] { background: rgba(249,117,16,0.08); }
QPushButton#reBtn[active="true"]:hover { background: rgba(249,117,16,0.12); }
QTextEdit#reEditor {
    border: none; background: transparent; color: #374151;
    font-size: 16px; line-height: 1.6; padding: 0;
    selection-background-color: #bfdbfe; selection-color: #111827;
}
QTextEdit#reEditor:focus { border: none; }
QTextEdit#reEditor QScrollBar:vertical {
    width: 6px; background: transparent; margin: 2px 0 2px 0;
}
QTextEdit#reEditor QScrollBar::handle:vertical {
    background: rgba(120,120,120,0.30); border-radius: 3px; min-height: 28px;
}
QTextEdit#reEditor QScrollBar::handle:vertical:hover { background: rgba(120,120,120,0.5); }
QTextEdit#reEditor QScrollBar::add-line:vertical,
QTextEdit#reEditor QScrollBar::sub-line:vertical { height: 0; }
QTextEdit#reEditor QScrollBar::add-page:vertical,
QTextEdit#reEditor QScrollBar::sub-page:vertical { background: transparent; }
""")


EDITOR_QSS = scale_qss("""
QFrame#reToolbar {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #FFFDF8,stop:1 #FFF9F0);
    border-bottom: 1px solid #F1E4D3;
    border-top-left-radius: 13px; border-top-right-radius: 13px;
}
QFrame#reSep { background: #F1E4D3; }
QPushButton#reBtn {
    border:none;background:transparent;border-radius:8px;color:#6b5744;
    padding:0;
}
QPushButton#reBtn:hover { background:#FFE9D8; color:#EA6A1F; }
QPushButton#reBtn[active="true"] { background:#F97316; color:#fff; }
QPushButton#reBtn[active="true"]:hover { background:#EA6A1F; }
QComboBox#reSelect {
    border:1px solid #F1E4D3;border-radius:8px;background:#fff;color:#6b5744;
    font-size:12.5px;padding:0 22px 0 8px;
}
QComboBox#reSelect:focus { border-color:#F97316; }
QComboBox#reSelect::drop-down {
    subcontrol-origin: padding; subcontrol-position: right center;
    width: 18px; border: none;
}
QComboBox#reSelect::down-arrow {
    image: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20width='12'%20height='12'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='%236b5744'%20stroke-width='2'%20stroke-linecap='round'%20stroke-linejoin='round'%3E%3Cpath%20d='M6%209l6%206%206-6'/%3E%3C/svg%3E");
    width: 12px; height: 12px;
}
QComboBox#reSelect QAbstractItemView {
    background:#fff;border:1px solid #F1E4D3;color:#3d2b1f;selection-background-color:#FFE9D8;
    selection-color:#EA6A1F;outline:0;padding:4px;
}
QComboBox#reSelect QAbstractItemView::item {
    min-height:24px;padding:0 8px;border-radius:6px;
}
QPushButton#reColor {
    border:none;background:transparent;border-radius:8px;
}
QPushButton#reColor:hover { background:#FFE9D8; }
QPushButton#reHili {
    border:none;background:#FFE9B0;border-radius:8px;
}
QPushButton#reHili:hover { background:#FFD27A; }
QTextEdit#reEditor {
    border:none;background:transparent;color:#3d2b1f;font-size:15px;line-height:1.75;
    padding:14px 16px;
    border-bottom-left-radius: 13px; border-bottom-right-radius: 13px;
    selection-background-color:#FFE0C4;selection-color:#3B2A1A;
}
QTextEdit#reEditor:focus { border:none; }
QTextEdit#reEditor QScrollBar:vertical {
    width:6px;background:transparent;margin:4px 2px 4px 0;
}
QTextEdit#reEditor QScrollBar::handle:vertical {
    background:rgba(160,142,122,0.32);border-radius:3px;min-height:28px;
}
QTextEdit#reEditor QScrollBar::handle:vertical:hover { background:rgba(249,117,16,0.45); }
QTextEdit#reEditor QScrollBar::add-line:vertical,
QTextEdit#reEditor QScrollBar::sub-line:vertical { height:0; }
QTextEdit#reEditor QScrollBar::add-page:vertical,
QTextEdit#reEditor QScrollBar::sub-page:vertical { background:transparent; }
""")


# ============ 紧凑取色弹窗（替代 Windows 原生 QColorDialog） ============
# 原生 QColorDialog 在 Windows 上会弹出巨大的系统对话框，与便签卡片风格完全不符；
# 这里用自绘的 8×4 预设色板 + 「自定义…」，尺寸紧凑、风格与整体一致，且点击外部即关闭。
COLOR_PALETTE = [
    "#000000", "#434343", "#666666", "#999999", "#b7b7b7", "#cccccc", "#efefef", "#ffffff",
    "#980000", "#ff0000", "#ff9900", "#ffff00", "#00ff00", "#00ffff", "#4a86e8", "#0000ff",
    "#e6b8af", "#f4cccc", "#fce5cd", "#fff2cc", "#d9ead3", "#d0e0e3", "#c9daf8", "#cfe2f3",
    "#a64d79", "#8e7cc3", "#674ea7", "#cc4125", "#e06666", "#f6b26b", "#ffd966", "#93c47d",
]

COLOR_POPUP_QSS = scale_qss("""
QWidget#colorPopupCard { background:#ffffff; border:1px solid #e5e7eb; border-radius:8px; }
QPushButton#colorPopupCustom {
    background:transparent; border:1px solid #e5e7eb; border-radius:6px;
    color:#3d2b1f; font-size:12px; padding:0 10px;
}
QPushButton#colorPopupCustom:hover {
    background:rgba(249,117,16,0.08); color:#f97510; border-color:rgba(249,117,16,0.30);
}
""")


class ColorPopup(QWidget):
    """自绘紧凑取色弹窗：预设色板 + 「自定义…」（后者开非原生 QColorDialog）。

    - 以 Qt.Popup 呈现 → 点击外部自动关闭，无需额外事件过滤器。
    - 选中任一色块或自定义颜色后发出 `picked(QColor)` 并自动关闭。
    """

    picked = pyqtSignal(QColor)

    def __init__(self, initial=None, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._initial = QColor(initial) if initial is not None else QColor("#F97316")

        root = QVBoxLayout(self)
        root.setContentsMargins(s(0), s(0), s(0), s(0))
        card = QWidget()
        card.setObjectName("colorPopupCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(COLOR_POPUP_QSS)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(s(16))
        shadow.setOffset(s(0), s(4))
        shadow.setColor(QColor(0, 0, 0, 46))
        card.setGraphicsEffect(shadow)
        root.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(s(10), s(10), s(10), s(10))
        lay.setSpacing(s(8))
        grid = QGridLayout()
        grid.setSpacing(s(4))
        cols = 8
        for i, hexv in enumerate(COLOR_PALETTE):
            sw = QPushButton()
            sw.setFixedSize(s(18), s(18))
            sw.setCursor(Qt.CursorShape.PointingHandCursor)
            sw.setStyleSheet(scale_qss(
                f"QPushButton{{background:{hexv};border:1px solid rgba(0,0,0,0.15);border-radius:4px;}}"
                f"QPushButton:hover{{border:2px solid #F97510;}}"))
            sw.clicked.connect(lambda _=False, c=hexv: self._pick(QColor(c)))
            grid.addWidget(sw, i // cols, i % cols)
        lay.addLayout(grid)

        cust = QPushButton(tr("自定义…"))
        cust.setObjectName("colorPopupCustom")
        cust.setFixedHeight(s(28))
        cust.setCursor(Qt.CursorShape.PointingHandCursor)
        cust.clicked.connect(self._custom)
        lay.addWidget(cust)

    def _pick(self, color):
        self.picked.emit(color)
        self.close()

    def _custom(self):
        dlg = QColorDialog(self._initial, self)
        dlg.setWindowTitle(tr("自定义颜色"))
        dlg.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        dlg.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
        if dlg.exec() and dlg.currentColor().isValid():
            self.picked.emit(dlg.currentColor())
        self.close()
