"""常驻桌面挂件：左上角固定、不可移动、全透明背景的任务清单速录。

设计要点（对应需求）：
- 全透明背景（FramelessWindowHint + WA_TranslucentBackground，无玻璃卡片），
  只浮出任务列表文字与复选框，像桌面便签一样贴在左上角。
- 固定屏幕左上角；无标题栏、无拖拽手柄、无缩放握把 → 不可移动/缩放。
- 宽度固定 336px，与音乐播放器主窗口 PLAYER_W 保持一致。无「全选/添加/返回/删除」按钮。
- 无右键菜单（TaskRow 传 enable_context_menu=False）。
- 标题行「📋 任务清单」与列表首项的间距收紧到与列表项间距一致，并去除标题下横线。
- 勾选复选框可直接完成/取消任务；任务数据来自 app.core.todo，与主窗口/便签共享同一数据源。
- 软件启动时由 App 创建并 show()，退出时 hide()/close()；常驻显示（点击其它软件不会被隐藏，
  只是层级上可被其它窗口覆盖——沿用现有 keep_on_top / release_topmost 机制，本窗口不强制置顶）。

点击穿透（关键，macOS 原生实现）：
- 需求：空白处点击穿透到桌面/其它窗口；只让「复选框」「标题文字」和「滚动区（滚轮翻页）」可点；
  标题文字过长时的 hover tooltip 仍保留（TaskRow.text 是 ElideLabel，已自带该 tooltip）。
- Windows 不可用（本项目运行时是 macOS）。`WA_TransparentForMouseEvents` 设在顶层窗口会触发
  macOS 的 setIgnoresMouseEvents，使整窗（含子控件）都收不到事件，无法做「背景穿透 + 子控件可点」。
- 正确做法（macOS 原生）：覆盖 content NSView 的 hitTest: ——
  命中交互区（标题 / 滚动区 / 复选框 / 标题文字）返回 self（事件交给本窗口，Qt 再路由到具体子控件，
  滚轮也由此到达滚动区）；空白区返回 nil（穿透到下方窗口/桌面）。
- 兜底：若 Objective-C runtime 注入失败，退回 Qt 的 WA_TransparentForMouseEvents 粒度方案
  （容器层透明、交互子控件保持可点），至少保证可交互（空白仅被本窗口吞掉、不穿透桌面）。
"""

import sys

from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QScrollArea, QApplication,
)
from PyQt6.QtCore import Qt, QPoint, QRect

from app.core import todo
from app.core.i18n import tr
from app.ui.todo_window import TaskRow


# ---- Windows 点击穿透所需的常量（仅 win32 下使用，保留兼容）----
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    _GWL_EXSTYLE = -20
    _WS_EX_TRANSPARENT = 0x00000020
    _WM_NCHITTEST = 0x0084
    _HTTRANSPARENT = -1
    _HTCLIENT = 1
    _user32 = ctypes.windll.user32

# macOS 原生 hitTest 注入所需的模块级状态（跨平台代码不应在导入期加载 libobjc）
_DOCK_BY_VIEW = {}
_HT_IMP_HOLDER = []


# 标题行高度约 20px；行上下内边距各 10px → 项间距 20px。
# 标题行 ↔ 列表首项的间距也设为 10（布局 spacing）+ 首项上内边距 10 = 20px，与项间距一致。
_DOCK_WIDTH = 336            # 与音乐播放器主窗口 PLAYER_W 保持一致
_DOCK_MARGIN = 12
_DOCK_TITLE_GAP = 10


class TodoDock(QWidget):
    """左上角固定的全透明任务清单挂件（macOS 原生选择性点击穿透）。"""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        # 仅无边框；不设置 WindowStaysOnTopHint —— 不强制置顶，点击其它软件时本窗口
        # 不会被隐藏，只是层级上可被其它窗口覆盖（满足「必须显示 + 其它软件可更高」）。
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(_DOCK_WIDTH)
        self._build()
        self.refresh()

        # 点击穿透按平台接入：macOS 用原生 hitTest 覆盖；Windows 用 WM_NCHITTEST；
        # 其它（含注入失败）用 Qt 粒度 WA_TransparentForMouseEvents 兜底。
        if sys.platform == "darwin":
            if not _setup_macos_native_clickthrough(self):
                _apply_granular_wa(self)
        elif sys.platform == "win32":
            self._setup_win32_clickthrough()

    # ---------------- 构建 ----------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(_DOCK_MARGIN, 10, _DOCK_MARGIN, 10)
        root.setSpacing(_DOCK_TITLE_GAP)   # 标题 ↔ 列表首项间距

        self.title = QLabel("📋 " + tr("任务清单"))
        self.title.setObjectName("dockTitle")
        self.title.setStyleSheet(self._qss())
        root.addWidget(self.title)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self.list_widget = QWidget()
        self.list_widget.setObjectName("dock-list")
        self.list_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.list_lay = QVBoxLayout(self.list_widget)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(0)   # 项间距由每行内部上下内边距(10)决定 → 20px
        self.scroll.setWidget(self.list_widget)
        root.addWidget(self.scroll, 1)

        self._place_top_left()

    @staticmethod
    def _qss():
        return """
        QLabel#dockTitle {
            font-size: 14px;
            font-weight: 700;
            color: #3d2b1f;
            background: transparent;
        }
        QLabel#dockEmpty {
            font-size: 13px;
            font-weight: 500;
            color: #a08e7a;
            background: transparent;
            padding: 4px 0;
        }
        """

    def _place_top_left(self):
        """固定在屏幕左上角（避开任务栏），小留白。"""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        self.move(avail.left() + 8, avail.top() + 8)

    # ---------------- 渲染 ----------------
    def refresh(self):
        self._render()

    def _render(self):
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        tasks = todo.all_tasks()
        if not tasks:
            empty = QLabel(tr("暂无任务"))
            empty.setObjectName("dockEmpty")
            empty.setStyleSheet(self._qss())
            self.list_lay.addWidget(empty)
        else:
            for t in tasks:
                # 挂件：禁用右键菜单、禁用点击标题开便签；勾选回调刷新自身并同步主窗口。
                self.list_lay.addWidget(
                    TaskRow(t, self._after_toggle, None, None, self.ctx.stop_alarm,
                            enable_context_menu=False, open_sticky_on_click=False)
                )
        self._fit_height()

    def _after_toggle(self):
        """复选框切换：同步主待办窗口（若已打开，其 _render 会再刷新本挂件）；
        主窗口未打开时自行刷新，避免重复构建。"""
        self.ctx.refresh_todo()
        if self.ctx.windows.get("todo") is None:
            self._render()

    def _fit_height(self):
        """按内容高度自适应窗口高度（整宽固定）；过高则限制并启用内部滚动。"""
        screen = QApplication.primaryScreen()
        avail_h = screen.availableGeometry().height() if screen is not None else 800
        max_h = max(120, avail_h - 40)
        hint = self.sizeHint().height()
        self.setFixedHeight(min(hint, max_h))

    # ---------------- 交互区判定（跨平台共用）----------------
    def _widget_rect_in_window(self, w):
        """取子控件在挂件窗口本地坐标系下的矩形。"""
        top_left = w.mapTo(self, QPoint(0, 0))
        return QRect(top_left, w.size())

    def _interactive_rects(self):
        """所有「可点」区域：挂件标题 + 滚动区（滚轮翻页）+ 每行的复选框 + 标题文字。"""
        rects = []
        if self.title.isVisible():
            rects.append(self._widget_rect_in_window(self.title))
        if self.scroll.isVisible():
            rects.append(self._widget_rect_in_window(self.scroll))
        for row in self.list_widget.findChildren(TaskRow):
            cb = getattr(row, "check", None)
            if cb is not None and cb.isVisible():
                rects.append(self._widget_rect_in_window(cb))
            txt = getattr(row, "text", None)
            if txt is not None and txt.isVisible():
                rects.append(self._widget_rect_in_window(txt))
        return rects

    def _is_interactive(self, local):
        for r in self._interactive_rects():
            if r.contains(local):
                return True
        return False

    # ---------------- Windows：WM_NCHITTEST（保留兼容）----------------
    def _setup_win32_clickthrough(self):
        try:
            self.winId()
            hwnd = int(self.winId())
            ex = _user32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
            _user32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, ex | _WS_EX_TRANSPARENT)
        except Exception:  # noqa: BLE001
            pass

    def nativeEvent(self, eventType, message):  # noqa: N802
        if sys.platform == "win32" and eventType == "windows_generic_MSG":
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == _WM_NCHITTEST:
                x = ctypes.c_short(msg.lParam & 0xFFFF).value
                y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                local = self.mapFromGlobal(QPoint(x, y))
                if self._is_interactive(local):
                    return True, _HTCLIENT
                return True, _HTTRANSPARENT
        return super().nativeEvent(eventType, message)

    # ---------------- 生命周期 / 国际化 ----------------
    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self._place_top_left()
        self._fit_height()

    def retranslate_ui(self):
        self.title.setText("📋 " + tr("任务清单"))
        self._render()


# ----------------------------------------------------------------------------
# macOS 原生选择性点击穿透：覆盖 content NSView 的 hitTest:
# ----------------------------------------------------------------------------
def _setup_macos_native_clickthrough(dock):
    """给挂件 content NSView 覆盖 hitTest:，交互区返回 self、空白区返回 nil（穿透）。
    返回 True 表示注入成功；False 表示失败（调用方应回退到 WA 粒度方案）。"""
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.CDLL(ctypes.util.find_library("objc"))

        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.objc_allocateClassPair.restype = ctypes.c_void_p
        objc.objc_allocateClassPair.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        objc.objc_registerClassPair.restype = None
        objc.objc_registerClassPair.argtypes = [ctypes.c_void_p]
        objc.class_addMethod.restype = ctypes.c_bool
        objc.class_addMethod.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
        objc.object_setClass.restype = ctypes.c_void_p
        objc.object_setClass.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        class NSPoint(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

        registry = _DOCK_BY_VIEW

        def _hit_test_impl(self_ptr, sel_ptr, a_point):
            # a_point 为 content NSView 本地坐标系下的点（== 挂件窗口本地坐标）。
            d = registry.get(self_ptr)
            if d is None:
                return self_ptr  # 找不到归属 → 保守当作可点，避免穿透到桌面却吞事件
            try:
                if d._is_interactive(QPoint(int(a_point.x), int(a_point.y))):
                    return self_ptr  # 命中交互区：事件交给本窗口，Qt 再路由到子控件
            except Exception:  # noqa: BLE001
                return self_ptr
            return 0  # nil → 穿透到下方窗口/桌面

        HitTestIMP = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, NSPoint)
        imp = HitTestIMP(_hit_test_impl)
        _HT_IMP_HOLDER.append(imp)  # 保活，防止被 GC 导致崩溃

        NSView = objc.objc_getClass(b"NSView")
        new_cls = objc.objc_allocateClassPair(NSView, b"ATDockHitTestView", 0)
        if not new_cls:
            raise RuntimeError("objc_allocateClassPair failed")
        sel = objc.sel_registerName(b"hitTest:")
        # 签名：返回 id '@'、self '@'、_cmd ':'、aPoint '{CGPoint=dd}'
        if not objc.class_addMethod(new_cls, sel, imp, b"@@:{CGPoint=dd}"):
            raise RuntimeError("class_addMethod hitTest: failed")
        objc.objc_registerClassPair(new_cls)

        # content NSView（PyQt6 在 macOS 上 winId() 即 NSView*）
        view = int(dock.winId())
        objc.object_setClass(view, new_cls)
        registry[view] = dock
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[TodoDock] macOS 原生穿透初始化失败，回退 WA 方案: {exc}")
        return False


def _apply_granular_wa(dock):
    """兜底：Qt 粒度 WA_TransparentForMouseEvents。
    容器层（list_widget / 每行 / meta）透明不捕获；交互子控件（标题 / 复选框 / 文字）
    与滚动区保持可点。空白仅被本窗口吞掉（不穿透桌面），但交互与滚轮正常。"""
    from PyQt6.QtCore import Qt as _Qt
    wa = _Qt.WidgetAttribute.WA_TransparentForMouseEvents
    dock.scroll.setAttribute(wa, False)           # 滚动区可点 → 滚轮翻页
    dock.list_widget.setAttribute(wa, True)        # 容器透明
    for row in dock.list_widget.findChildren(TaskRow):
        row.setAttribute(wa, True)
        meta = getattr(row, "meta", None)
        if meta is not None:
            meta.setAttribute(wa, True)
    dock.title.setAttribute(wa, False)            # 标题可点
