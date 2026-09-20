"""常驻桌面挂件：左上角固定、不可移动、全透明背景的任务清单速录。

设计要点（对应需求）：
- 全透明背景（FramelessWindowHint + WA_TranslucentBackground，无玻璃卡片），
  只浮出任务列表文字与复选框，像桌面便签一样贴在左上角。
- 固定屏幕左上角；无标题栏、无拖拽手柄、无缩放握把 → 不可移动/缩放。
- 宽度固定 336px，与音乐播放器主窗口 PLAYER_W 保持一致。无「全选/添加/返回/删除」按钮。
- 无右键菜单（TaskRow 传 enable_context_menu=False）。
- 标题行「📋 任务清单」与列表首项的间距收紧到与列表项间距一致，并去除标题下横线。
- 勾选复选框可直接完成/取消任务；任务数据来自 app.core.todo，与主窗口/便签共享同一数据源。
- 软件启动时由 App 创建并 show()，退出时 hide()/close()；常驻显示（点击其它软件不会被隐藏）。
  Windows：不强制置顶（沿用现有 keep_on_top / release_topmost 机制，可被其它窗口覆盖）。
  macOS：见下节「macOS 显示逻辑」——登记为桌面挂件，层级固定为浮层（台前调度豁免的代价）。

macOS 显示逻辑（与 Windows 分叉，见 app/ui/mac_window.py）：
- 症状：mac 端左上角看不到挂件。根因是 Qt 的窗口标志不足以表达原生语义 —— 只用
  ``FramelessWindowHint`` 的窗口在 macOS 是**普通 NSWindow**，会被「台前调度
  (Stage Manager)」当成 App 的普通主窗口：前台窗口（如桌宠）一出现，其它普通窗口
  就被移出舞台、缩进屏幕左侧的「最近使用的 App」条（表现即挂件「消失」）。
- 修法：本窗口在 macOS 用 ``Qt.Tool``（映射为 NSPanel 浮层面板），并对底层 NSWindow
  施加 AppKit 语义：collectionBehavior = CanJoinAllApplications | Stationary |
  CanJoinAllSpaces | FullScreenAuxiliary | IgnoresCycle、level = NSFloatingWindowLevel、
  hidesOnDeactivate = NO。这样它常驻所有空间/所有 App 舞台，不受台前调度、Mission
  Control、空间切换影响，切到其它软件也不隐藏。
- 该逻辑只在 darwin 下生效，Windows 端的窗口标志与 WM_NCHITTEST 路径保持原样。

点击穿透（关键，macOS 原生实现）：
- 需求：空白处点击穿透到桌面/其它窗口；只让「复选框」「标题文字」和「滚动区（滚轮翻页）」可点；
  标题文字过长时的 hover tooltip 仍保留（TaskRow.text 是 ElideLabel，已自带该 tooltip）。
- ``WA_TransparentForMouseEvents`` 设在顶层窗口会触发 macOS 的 setIgnoresMouseEvents，
  使整窗（含子控件）都收不到事件，无法做「背景穿透 + 子控件可点」。
- 正确做法（macOS 原生）：覆盖 content NSView 的 hitTest: ——
  命中交互区（标题 / 滚动区 / 复选框 / 标题文字）返回 self（事件交给本窗口，Qt 再路由到具体子控件，
  滚轮也由此到达滚动区）；空白区返回 nil（穿透到下方窗口/桌面）。
  注意：新类必须以该 NSView 的**真实类**（QNSView）为父类，且传入的点需按窗口高度翻转 y；
  这两点踩错会让窗口既不显示也点不动（详见 mac_window.install_hit_test_router）。
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
from app.ui.todo_window import TaskRow, LIST_WINDOW_SIZE
from app.ui.mac_window import (
    IS_MAC, apply_desktop_widget_style, install_hit_test_router, mac_log,
)


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


# 标题行高度约 20px；行上下内边距各 10px → 项间距 20px。
# 标题行 ↔ 列表首项的间距也设为 10（布局 spacing）+ 首项上内边距 10 = 20px，与项间距一致。
_DOCK_WIDTH = 269            # 与音乐播放器主窗口 PLAYER_W 保持一致（1440×900 基准的 80%）
# 宽版：只要存在「带提醒时间」的任务，挂件宽度就对齐任务清单页（480）。
# 提醒时间是「年-月-日 时:分」的长串，336px 下会把标题挤得只剩省略号。
_DOCK_WIDTH_WITH_REMIND = LIST_WINDOW_SIZE[0]
_DOCK_MARGIN = 12
_DOCK_TITLE_GAP = 10
_DOCK_VISIBLE_ROWS = 5   # 可视区固定显示 5 条任务，多出来的靠滚动查看


def _any_remind(tasks):
    """是否存在「带提醒时间」的任务（判定与 TaskRow 一致：remind_enabled 关掉不算）。"""
    for t in tasks or ():
        if t.get("remind") and t.get("remind_enabled", True):
            return True
    return False


class TodoDock(QWidget):
    """左上角固定的全透明任务清单挂件（macOS 原生选择性点击穿透）。"""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._wa_fallback = False   # 是否退化为 Qt 粒度穿透方案（_render 需补挂属性）
        # 仅无边框；不设置 WindowStaysOnTopHint —— 不强制置顶，点击其它软件时本窗口
        # 不会被隐藏，只是层级上可被其它窗口覆盖（满足「必须显示 + 其它软件可更高」）。
        # macOS 额外加 Qt.Tool（→ NSPanel 浮层面板）：普通 NSWindow 会被台前调度
        # 当成 App 主窗口移出舞台（挂件「消失」的根因），面板型窗口不会被收走。
        # NoDropShadowWindowHint：全透明无边框窗口的系统阴影按内容形状缓存，会在
        # 画面后方残留灰黑重影（同类坑见 pet_window 第十六类坑），一并去掉。
        flags = Qt.WindowType.FramelessWindowHint
        if IS_MAC:
            flags |= Qt.WindowType.Tool | Qt.WindowType.NoDropShadowWindowHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(_DOCK_WIDTH)
        self._build()
        self.refresh()

        # 点击穿透按平台接入：macOS 用原生 hitTest 覆盖；Windows 用 WM_NCHITTEST；
        # 其它（含注入失败）用 Qt 粒度 WA_TransparentForMouseEvents 兜底。
        self._install_click_through()
        if IS_MAC:
            # macOS 显示逻辑：登记为「桌面挂件」，不受台前调度 / 空间切换影响。
            self._apply_mac_outer_style()
            app = QApplication.instance()
            if app is not None:
                # 切 App / 台前调度重新分舞台后重申一次挂件语义（幂等，开销极小）。
                # 用绑定方法而非 lambda：挂件销毁时 PyQt 会自动断开，避免退出期回调野指针。
                app.applicationStateChanged.connect(self._on_app_state_changed)

    # ---------------- 平台接入：点击穿透 / macOS 显示逻辑 ----------------
    def _install_click_through(self):
        """装「空白穿透 + 交互区可点」；macOS 走原生 hitTest 路由，失败退 WA 粒度。"""
        if IS_MAC:
            ok = install_hit_test_router(
                self,
                lambda x, y: self._is_interactive(QPoint(int(x), int(y))),
                tag="TodoDock",
            )
            self._wa_fallback = not ok
            if not ok:
                _apply_granular_wa(self)
                mac_log("点击穿透：原生 hitTest 注入失败 → 回退 Qt 粒度兜底方案",
                        tag="TodoDock")
            else:
                mac_log("点击穿透：原生 hitTest 路由生效（空白穿透 + 交互区可点）",
                        tag="TodoDock")
            return ok
        if sys.platform == "win32":
            self._setup_win32_clickthrough()
        return True

    def _apply_mac_outer_style(self, verbose=True):
        """macOS 专属显示逻辑：不受台前调度影响（见 app/ui/mac_window.py 顶部说明）。"""
        if not IS_MAC:
            return False
        return apply_desktop_widget_style(
            self, floating=True, tag="TodoDock", verbose=verbose
        )

    def _on_app_state_changed(self, _state):
        """应用激活状态变化（切 App / 台前调度重新分舞台）→ 重申挂件语义。"""
        self._apply_mac_outer_style(verbose=False)

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
        # 宽度自适应：有任务带提醒 → 对齐任务清单页宽度；取消提醒后没有一个任务
        # 带提醒 → 恢复 336。宽度变化后必须立即重排，否则 _fit_height 会按旧宽度算高度。
        target = _DOCK_WIDTH_WITH_REMIND if _any_remind(tasks) else _DOCK_WIDTH
        if self.width() != target:
            self.setFixedWidth(target)
            lay = self.layout()
            if lay is not None:
                lay.activate()
        if not tasks:
            empty = QLabel(tr("暂无任务"))
            empty.setObjectName("dockEmpty")
            empty.setStyleSheet(self._qss())
            self.list_lay.addWidget(empty)
        else:
            for t in tasks:
                # 挂件：禁用右键菜单、禁用点击标题开便签；勾选回调刷新自身并同步主窗口。
                # open_sticky_on_click=True：点标题文字打开该任务的便签卡片
                # （TaskRow 走 self.window().open_sticky(task) → 见本类 open_sticky）
                self.list_lay.addWidget(
                    TaskRow(t, self._after_toggle, None, None, self.ctx.stop_alarm,
                            enable_context_menu=False, open_sticky_on_click=True,
                            glass_tag=True)
                )
        self._fit_height()
        # 兜底穿透方案的属性挂在「行控件」上，_render 重建行后必须重新补挂，
        # 否则刷新出来的行会吞掉鼠标事件（原生 hitTest 方案无此问题）。
        if self._wa_fallback:
            _apply_granular_wa(self)

    def open_sticky(self, task):
        """点击挂件里的任务标题 → 打开（或聚焦）该任务的便签卡片。

        TaskRow._open_sticky 调的是 ``self.window().open_sticky(task)``，挂件自己就是
        顶层窗口，所以这里做桥接：便签注册表 ``sticky_windows`` 挂在待办窗口上，
        先**静默**确保待办窗口实例存在（不显示它，避免点标题时顺带弹出任务清单页），
        再交给它打开便签。
        """
        todo_win = self.ctx.windows.get("todo")
        if todo_win is None:
            ensure = getattr(self.ctx, "ensure_todo_window", None)
            todo_win = ensure() if ensure is not None else None
        if todo_win is None:
            return
        # 便签窗口自带 WindowStaysOnTopHint（见 StickyNoteWindow），无需再补置顶
        todo_win.open_sticky(task)

    def _after_toggle(self):
        """复选框切换：同步主待办窗口（若已打开，其 _render 会再刷新本挂件）；
        主窗口未打开时自行刷新，避免重复构建。"""
        self.ctx.refresh_todo()
        if self.ctx.windows.get("todo") is None:
            self._render()

    def _fit_height(self):
        """可视高度 = 标题 + **最多 5 条任务**；超过 5 条则高度固定，其余靠滚动查看。

        不足 5 条时按实际内容收窄（挂件是透明窗口，多出来的空高度只会白白吃掉
        空白处的点击穿透区域）；超过 5 条时按「前 5 行的实际高度和」定高，
        QScrollArea 自动出现纵向滚动条，滚轮/拖滚动条都能翻。
        屏幕太矮时再夹一道 max_h，避免把整屏占满。
        """
        screen = QApplication.primaryScreen()
        avail_h = screen.availableGeometry().height() if screen is not None else 800
        max_h = max(120, avail_h - 40)

        self.list_lay.activate()                       # 先让行布局生效，sizeHint 才准
        rows = self.list_widget.findChildren(TaskRow)
        inner = self.list_widget.sizeHint().height()   # 全部行（或「暂无任务」）的高度
        if rows:
            heights = [r.sizeHint().height() for r in rows]
            visible = sum(heights[:_DOCK_VISIBLE_ROWS])
        else:
            visible = inner                             # 空状态：一个「暂无任务」的高度
        # 窗口非列表部分（上下内边距 + 标题 + 标题与列表间距 + 滚动区边框）
        chrome = max(0, self.sizeHint().height() - inner)
        self.setFixedHeight(min(chrome + visible, max_h))

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
        # Qt 可能重建原生窗口（窗口标志变化等），每次都重申挂件语义与穿透路由
        # （两者都幂等：桌面挂件语义是回写属性，hitTest 路由同一 view 直接返回）
        if IS_MAC:
            self._apply_mac_outer_style()
        self._install_click_through()

    def retranslate_ui(self):
        self.title.setText("📋 " + tr("任务清单"))
        self._render()


# ----------------------------------------------------------------------------
# 兜底方案（macOS 原生 hitTest 注入失败时使用）
# ----------------------------------------------------------------------------
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
