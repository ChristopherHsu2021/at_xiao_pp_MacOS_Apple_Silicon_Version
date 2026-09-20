"""常驻桌面挂件：左上角固定、不可移动、全透明背景的任务清单速录。

设计要点（对应需求）：
- 全透明背景（FramelessWindowHint + WA_TranslucentBackground，无玻璃卡片），
  只浮出任务列表文字与复选框，像桌面便签一样贴在左上角。
- 固定屏幕左上角；无标题栏、无拖拽手柄、无缩放握把 → 不可移动/缩放。
- 宽度固定 269px（= 音乐播放器主窗口 PLAYER_W，1440×900 基准的 80%）。无「全选/添加/返回/删除」按钮。
- 无右键菜单（TaskRow 传 enable_context_menu=False）。
- 标题行「📋 任务清单」与列表首项的间距收紧到与列表项间距一致，并去除标题下横线。
- 复选框与任务清单页共用 TodoCheckBox（尺寸/样式天然一致）。
- **不常显「提醒时间」**：该标签是「年-月-日 时:分」长串，会明显撑宽挂件；改为在任务标题
  上挂 hover 提示卡，卡片内容**只有提醒时间**（TaskRow(show_remind_tag=False)）。
  没有提醒时间的任务不弹任何提示卡；被省略的长标题靠行内「跑马灯」看全，不再进提示卡
  （2026-09-21 需求：hover 白框只用于显示提醒时间，不显示内容和标题）。
- 勾选复选框可直接完成/取消任务；任务数据来自 app.core.todo，与主窗口/便签共享同一数据源。
- 软件启动时由 App 创建并 show()，退出时 hide()/close()；常驻显示（点击其它软件不会被隐藏）。
  Windows：不强制置顶（沿用现有 keep_on_top / release_topmost 机制，可被其它窗口覆盖）。
  macOS：见下节「macOS 显示逻辑」——登记为桌面挂件，层级下沉到桌面层（不遮挡其它 App）。

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

hover 与「任意 App 都要能点/能 hover」（2026-09-21 需求，本节是唯一权威说明）
-----------------------------------------------------------------------------
现象：用户反馈「不管鼠标焦点在哪个应用，TodoDock 都应该能触发点击或 hover」——
在别的 App 前台时，挂件既不会高亮、也点不动。

根因有两条，必须一起解决：
1. **Qt 在 macOS 上不给非激活 App 派发 hover**。Qt 官方行为（QTBUG-100932）：
   ``NSTrackingArea`` 只在 ``NSApplication`` 为激活态时才把 mouseEntered/mouseExited
   转成 Qt 的 enterEvent/leaveEvent。挂件的常态就是「别的 App 在前台」，于是
   ElideLabel 的原生 hover（标题跑马灯 + tooltip）永远不触发。
   → 解法：挂件**自己轮询光标**（``QTimer`` + ``QCursor.pos()``），算出落在哪一行，
     主动调 ``ElideLabel.set_hovered()``。为避免与原生 hover 打架，行内标签一律
     ``set_external_hover_owner(True)``（关掉原生 mouseTracking 与原生 tooltip，
     提示改由挂件自绘卡片给出）。详见 TodoDock._poll_hover。
2. **macOS 不向被覆盖的窗口投递鼠标事件**（与 Windows 的 WM_NCHITTEST 模型不同）。
   挂件若长期待在普通层（NSNormalWindowLevel），别的 App 窗口一盖上来就同时失去
   hover 与 click；但长期待在浮层（NSFloatingWindowLevel）又会一直盖住别人的界面
   ——上一轮用户明确反对（「不遮挡住其他应用或界面的显示」）。
   → 解法：**动态层级**。轮询里发现光标进入挂件矩形 → 抬到浮层（此时才盖住别人、
     也才收得到鼠标）；光标离开 → 落回普通层（不再遮挡任何界面）。空白区穿透仍由
     hitTest 路由保证，所以抬层期间挂件矩形内的「空白」依然把点击让给下层窗口。
     实现见 ``mac_window.set_window_level``（只改 level，不动 collectionBehavior）。
3. **同层之内还有先后顺序**（2026-09-21 第三轮：用户截图「tododock 遮盖其他应用和页面」）。
   动态层级只解决「层」，层内顺序仍按 orderFront/orderBack 排，且**全局跨 App** 生效：
   抬到浮层必然把它顶到最前，落回普通层时若只改 level，它会**停在普通层最前** →
   继续压着其它 App 更早打开的窗口（截图里挂件文字叠在一个原生窗口上）。挂件启动时
   的 show() 也有同样问题。→ 解法：落层/重申语义时一律补一次 ``orderBack:``
   （``mac_window.order_window_back``），把挂件压到普通层最后；需要交互时轮询再抬回浮层。

三条合起来即为「光标到哪儿，挂件就在哪儿可点可 hover；光标一走，挂件就沉到最底下不挡人」。
"""

import sys

from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QScrollArea, QApplication,
)
from PyQt6.QtCore import Qt, QPoint, QRect, QRectF, QTimer
from PyQt6.QtGui import QCursor, QColor, QFont, QFontMetrics, QPainter, QPen

from app.core import todo
from app.core.todo_signals import bus
from app.core.i18n import tr
from app.ui.todo_window import TaskRow, LIST_WINDOW_SIZE   # noqa: F401  (LIST_WINDOW_SIZE 保留供参考/将来对齐)
from app.ui.screen_fit import scale_qss, s
from app.ui.style import TITLE_BAR_QSS
from app.ui.mac_window import (
    IS_MAC, apply_desktop_widget_style, install_hit_test_router, mac_log,
    order_window_back, set_window_level,
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
_DOCK_MARGIN = s(12)         # 左右留白（随全局 80% 缩放）
_DOCK_VPAD = s(10)           # 挂件容器上下留白
# 头部「📋 任务清单」与列表首项的间距：与任务清单页「项与项」的间距一致 ——
# 行自身上下各有 s(10) 内边距，故两行之间的视觉间距 = 2×行内边距；首项还会自带一个
# 上内边距，所以这里只需要补「一个行内边距」的布局 spacing 即可对齐（2026-09-21 意见：
# 原间距过长，标题与首条任务之间空了一大块）。
_DOCK_TITLE_GAP = s(10)
_DOCK_VISIBLE_ROWS = 5   # 可视区固定显示 5 条任务，多出来的靠滚动查看

# ---- hover 轮询参数（见模块头部「hover」小节）----
_HOVER_POLL_MS = 40      # 25Hz：足够跟手，又不至于明显吃 CPU（每次轮询只读一次光标坐标）
_TIP_MAX_W = s(260)      # 自绘 hover 提示卡的最大宽度（超出自动换行）


class _DockHoverTip(QWidget):
    """桌面挂件自绘的 hover 提示卡（替代 Qt 原生 tooltip）。

    为什么不用 ``setToolTip``：原生 tooltip 由 Qt 自己管理显隐时机，而它的显隐同样依赖
    「原生 hover」——正是 macOS 在 App 非激活时不派发的那种事件。挂件改为光标轮询后，
    提示必须由轮询**显式驱动**，所以自带一个窗口：ToolTip 类型 + 不抢焦点 + 鼠标穿透
    （``WindowTransparentForInput`` → macOS setIgnoresMouseEvents），永远不干扰点击。

    样式与 App 右键菜单同源：暖米白卡片 + 8px 圆角 + 细白描边，正文 #3d2b1f。
    """

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._text = ""
        font = QFont(self.font())
        font.setPixelSize(max(10, int(round(s(12)))))
        self.setFont(font)

    def text(self):
        return self._text

    def set_text(self, text):
        """按文本量出卡片尺寸（自动换行，宽度上限 _TIP_MAX_W）。"""
        self._text = text or ""
        pad = int(round(s(10)))
        fm = QFontMetrics(self.font())
        flags = int(Qt.TextFlag.TextWordWrap)
        rect = fm.boundingRect(0, 0, int(_TIP_MAX_W), 10000, flags, self._text)
        self.resize(rect.width() + pad * 2, rect.height() + pad * 2)

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 235), 1))
        p.setBrush(QColor(255, 250, 245, 248))
        p.drawRoundedRect(r, s(8), s(8))
        pad = int(round(s(10)))
        p.setPen(QColor("#3d2b1f"))
        p.drawText(self.rect().adjusted(pad, pad, -pad, -pad),
                   int(Qt.TextFlag.TextWordWrap), self._text)


class TodoDock(QWidget):
    """左上角固定的全透明任务清单挂件（macOS 原生选择性点击穿透）。"""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._wa_fallback = False   # 是否退化为 Qt 粒度穿透方案（_render 需补挂属性）
        self._rows = []             # 缓存的 TaskRow 列表（hover 轮询每 40ms 用，不能每次 findChildren）
        self._hover_row = None      # 当前光标命中的行（用于自绘 hover 高亮）
        self._tip = None            # 自绘 hover 提示卡（首次需要时才建）
        self._floating = None       # 当前是否处于浮层（None = 尚未设置，见 _ensure_level）
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
        # 订阅全局 done_changed：列表页 / 便签任一入口勾选本挂件的某条任务时，该行
        # 标题渲染（删除线 + 置灰）即刻就地同步，无需等整表重建。UniqueConnection 防重复连。
        bus().done_changed.connect(self._on_done_changed,
                                    Qt.ConnectionType.UniqueConnection)

        # 点击穿透按平台接入：macOS 用原生 hitTest 覆盖；Windows 用 WM_NCHITTEST；
        # 其它（含注入失败）用 Qt 粒度 WA_TransparentForMouseEvents 兜底。
        self._install_click_through()
        if IS_MAC:
            # macOS 显示逻辑：登记为「桌面挂件」，不受台前调度 / 空间切换影响。
            self._apply_mac_outer_style()
            # hover + 动态层级：见模块头部「hover」小节（App 非激活时 Qt 不派发 hover，
            # 且被覆盖的窗口收不到鼠标 → 只能自己轮询光标，并按需抬层/落层）。
            self._poll_timer = QTimer(self)
            self._poll_timer.setInterval(_HOVER_POLL_MS)
            self._poll_timer.timeout.connect(self._poll_hover)
            self._poll_timer.start()
            app = QApplication.instance()
            if app is not None:
                # 切 App / 台前调度重新分舞台后重申一次挂件语义（幂等，开销极小）。
                # 用绑定方法而非 lambda：挂件销毁时 PyQt 会自动断开，避免退出期回调野指针。
                app.applicationStateChanged.connect(self._on_app_state_changed)
        else:
            self._poll_timer = None

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
        """macOS 专属显示逻辑：不受台前调度影响（见 app/ui/mac_window.py 顶部说明）。

        层级策略（2026-09-21 更新，是「动态层级」，不要退回任何静态方案）：
        - NSFloatingWindowLevel 常驻（floating=True）：永不遮挡需求被否 —— 文字会长期
          盖在其它软件界面上（用户意见「不遮挡住其他应用或界面的显示」）。
        - 桌面层（level="desktop" / kCGDesktopIconWindowLevel）：实测**不可用** ——
          内容被系统合成成半透明发虚，且被 Finder 桌面窗口吃掉全部鼠标事件
          → 挂件完全无法点击。
        - 因此这里只把**基准层级**设为 NSNormalWindowLevel，并补一次 ``orderBack:``
          （压到「普通层最后方」—— 否则启动时的 show()/曾经抬过层都会让它停在最前，继续
          压着其它 App 的窗口）。真正的层级由 ``_ensure_level`` 在 40ms 轮询里动态切换：
            光标在挂件上 → LEVEL_FLOATING（否则 macOS 不给被覆盖窗口投递鼠标，
                             hover/点击全失效 —— 用户「任意应用都要能点/能 hover」）
            光标离开     → LEVEL_NORMAL + orderBack（不遮挡任何界面）
          本方法会在切 App 时被调用，故顺手把 _floating 复位为 False（与 NORMAL 一致），
          让轮询下一拍自行纠正（幂等、无竞态：两者都只是写同一个 level）。
        """
        if not IS_MAC:
            return False
        ok = apply_desktop_widget_style(
            self, floating=False, tag="TodoDock", verbose=verbose
        )
        if ok:
            self._floating = False
            # ★ 只落 level 不够：窗口仍停在「普通层最前」，照样压着其它 App 的窗口
            #   （用户截图：「tododock 遮盖其他应用和页面」）。必须同时 orderBack 压到最后。
            #   光标此刻正在挂件上时不要压（下一拍轮询就会把它抬回浮层，压了只是白抖一下）。
            if not self._cursor_inside():
                order_window_back(self, tag="TodoDock")
        return ok

    def _cursor_inside(self):
        """光标是否落在挂件窗口矩形内（异常一律按「不在」处理，绝不影响主流程）。"""
        try:
            return self.rect().contains(self.mapFromGlobal(QCursor.pos()))
        except Exception:  # noqa: BLE001
            return False

    def _on_app_state_changed(self, _state):
        """应用激活状态变化（切 App / 台前调度重新分舞台）→ 重申挂件语义。"""
        self._apply_mac_outer_style(verbose=False)

    # ---------------- hover + 动态层级（模块头部「hover」小节）----------------
    def _poll_hover(self):
        """每 40ms 一次：把「Qt 在 App 非激活时不派发 hover」与「被覆盖窗口收不到鼠标」
        两个 macOS 限制一起绕过去。

        顺序很重要：**先按光标位置调整层级，再判定命中行** —— 抬层本身不影响本函数的
        判定（命中用的是全局光标坐标 + 挂件几何，与窗口层级无关），但抬层必须尽早发生，
        用户真正点击时窗口才已经在上层。
        """
        if not self.isVisible():
            return
        try:
            pos = QCursor.pos()
            local = self.mapFromGlobal(pos)
            inside = self.rect().contains(local)
            self._ensure_level(inside)
            row = self._row_at(local) if inside else None
            if row is not self._hover_row:
                self._set_hover_row(row)
            label = getattr(row, "text", None) if row is not None else None
            # 提示卡内容 = 仅「提醒时间」（TaskRow 在无提醒时间时不会 set_extra_tip
            # → hover_tip_text() 为空串 → 不弹白框）。标题/内容全文一律不再进提示卡
            # —— 2026-09-21 需求（长标题在卡片里折行会把桌面糊住）。
            tip_text = label.hover_tip_text() if label is not None else ""
            if tip_text:
                self._show_tip(tip_text, pos)
            else:
                self._hide_tip()
        except Exception:  # noqa: BLE001
            # 轮询跑在 Qt 定时器里；任何异常都不能冒泡（虚函数/定时器里逃逸的异常会
            # 触发 PyQt6 的 qFatal → 整个 App abort，同类坑见 common.guard_ui）。
            self._hide_tip()

    def _ensure_level(self, inside):
        """光标在挂件上 → 浮层（可收鼠标）；离开 → 普通层（不遮挡其它应用）。

        仅 darwin 生效，且只在状态真正变化时才发 objc 消息（``set_window_level`` 幂等）。
        """
        if not IS_MAC:
            return
        want = bool(inside)
        if self._floating is want:
            return
        if set_window_level(self, want, tag="TodoDock"):
            self._floating = want

    def _row_at(self, local):
        """命中测试：光标（挂件本地坐标）落在哪一行。用整行矩形，比只判文字更宽容。"""
        for row in self._rows:
            try:
                if row is None or not row.isVisible():
                    continue
                top_left = row.mapTo(self, QPoint(0, 0))
                if QRect(top_left, row.size()).contains(local):
                    return row
            except Exception:  # noqa: BLE001
                continue
        return None

    def _set_hover_row(self, row):
        """切换命中行：旧行复位、新行进入 hover（唯一入口，避免两套 hover 状态打架）。"""
        prev = self._hover_row
        self._hover_row = row
        if prev is not None:
            try:
                prev.text.set_hovered(False)
            except Exception:  # noqa: BLE001
                pass
        if row is not None:
            try:
                row.text.set_hovered(True)
            except Exception:  # noqa: BLE001
                pass
        self.update()            # 重绘行 hover 高亮（见 paintEvent）

    def _show_tip(self, text, global_pos):
        """在挂件右侧弹出自绘提示卡；内容只有「提醒时间：年-月-日 时:分」。"""
        tip = self._tip
        if tip is None:
            tip = _DockHoverTip()
            self._tip = tip
        if tip.text() != text:
            tip.set_text(text)
        geo = self.geometry()
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else geo
        gx = geo.right() + int(round(s(8)))
        gy = global_pos.y() - tip.height() // 2
        if gx + tip.width() > avail.right():
            # 右侧放不下 → 退到光标左侧
            gx = max(avail.left(), global_pos.x() - tip.width() - int(round(s(12))))
        gy = max(avail.top(), min(gy, avail.bottom() - tip.height()))
        tip.move(int(gx), int(gy))
        if not tip.isVisible():
            tip.show()
        tip.raise_()
        # 提示卡是瞬时窗口，不参与台前调度豁免 → 需手动抬到浮层，否则会被别的 App 盖住
        if IS_MAC and self._floating:
            set_window_level(tip, True, tag="TodoDockTip")

    def _hide_tip(self):
        tip = self._tip
        if tip is None or not tip.isVisible():
            return
        tip.hide()
        if IS_MAC:
            set_window_level(tip, False, tag="TodoDockTip")

    # ---------------- 自绘 hover 高亮 ----------------
    def paintEvent(self, _e):  # noqa: N802
        """给命中行铺一层淡暖橙底（在子控件之下渲染，不影响任何既有样式）。

        没有这一层时，「标题放得下 + 无提醒时间」的行 hover 起来毫无视觉反馈，
        用户会再次认为「hover 没效果」。
        """
        row = self._hover_row
        if row is None:
            return
        try:
            top_left = row.mapTo(self, QPoint(0, 0))
            r = QRectF(QRect(top_left, row.size())).adjusted(
                -s(2), s(1), s(2), -s(1)
            )
        except Exception:  # noqa: BLE001
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(249, 117, 16, 30))
        p.drawRoundedRect(r, s(8), s(8))

    # ---------------- 构建 ----------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(_DOCK_MARGIN, _DOCK_VPAD, _DOCK_MARGIN, _DOCK_VPAD)
        root.setSpacing(_DOCK_TITLE_GAP)   # 标题 ↔ 列表首项间距（= 列表项间距，见常量注释）

        self.title = QLabel("📋 " + tr("任务清单"))
        self.title.setObjectName("dockTitle")
        # 顶栏标题与「任务清单页面」顶栏共用 style.TITLE_BAR_QSS（同一套字号/字重/颜色）
        # —— 三处任务标题渲染同步的需求之一（原来这里 14px、清单页 15px）。
        self.title.setStyleSheet(TITLE_BAR_QSS)
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
        # 随全局 80% 等比缩放（挂件也是「页面」，内饰要与其它页面同尺度）
        # 注意：顶栏标题不再在这里定义 —— 它改用 app/ui/style.TITLE_BAR_QSS，
        # 与任务清单页顶栏同源（三处标题渲染同步）。这里只剩空状态文案。
        return scale_qss("""
        QLabel#dockEmpty {
            font-size: 13px;
            font-weight: 500;
            color: #a08e7a;
            background: transparent;
            padding: 4px 0;
        }
        """)

    def _place_top_left(self):
        """固定在屏幕左上角（避开任务栏），小留白。"""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        pad = s(8)
        self.move(avail.left() + pad, avail.top() + pad)

    # ---------------- 渲染 ----------------
    def refresh(self):
        self._render()

    def _render(self):
        # 行即将被销毁：先把 hover 状态清干净（_hover_row 会变成悬垂引用）
        self._hover_row = None
        self._hide_tip()
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        tasks = todo.all_tasks()
        # 宽度恒定：不再因为「存在带提醒时间的任务」而加宽挂件（2026-09-21 意见）。
        # 提醒时间已改为标题 hover 提示，宽度与提示时间无关。
        if self.width() != _DOCK_WIDTH:
            self.setFixedWidth(_DOCK_WIDTH)
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
                # show_remind_tag=False：不常显提醒时间标签（会撑宽挂件），改挂标题 hover 提示
                self.list_lay.addWidget(
                    TaskRow(t, self._after_toggle, None, None, self.ctx.stop_alarm,
                            enable_context_menu=False, open_sticky_on_click=True,
                            glass_tag=True, show_remind_tag=False)
                )
        # 末尾留伸缩项：让行保持自身高度，多余空间落在列表底部而不是被塞进行内
        # （否则行被拉高、内容垂直居中 → 头部与首条任务之间凭空多出一段空白）
        self.list_lay.addStretch(1)
        self._fit_height()
        # 缓存行列表：hover 轮询每 40ms 跑一次，绝不能每次都 findChildren 遍历控件树
        self._rows = list(self.list_widget.findChildren(TaskRow))
        # 行内标签一律交给挂件轮询驱动 hover：关掉原生 mouseTracking 与原生 tooltip
        # （macOS 在 App 非激活时根本不派发原生 hover，留着只会与轮询打架）。
        for row in self._rows:
            try:
                row.text.set_external_hover_owner(True)
            except Exception:  # noqa: BLE001
                pass
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

    def _on_done_changed(self, tid, done):
        """全局完成态变化（来自列表/Dock/便签任意入口）：就地刷新本挂件对应行的标题渲染。

        挂件行由 ``TaskRow`` 承载，复用与列表页同一套 ``set_done_state``（删除线 + 置灰）。
        信号源自己那一行收到广播时幂等早退，不重复做事。
        """
        for row in self._rows:
            if getattr(row, "task", None) and row.task.get("id") == tid:
                row.set_done_state(done)
                break

    def _fit_height(self):
        """可视高度 = 标题行 + **最多 5 条任务**；超过 5 条则高度固定，其余靠滚动查看。

        2026-09-21 修正：原实现用 ``self.sizeHint().height() - inner`` 反推「非列表部分」
        的高度，而 ``inner``（list_widget.sizeHint）与 sizeHint 的生效时机不一致时会算偏大，
        于是滚动视口比「可见行高之和」更高；多出来的空间又被 QVBoxLayout 分给唯一一行
        （行被拉高、内容垂直居中），最终表现为意见里那条「头部『任务清单』与任务列表的
        间距太长」。现改为逐项显式计算 chrome，并配合 _render 末尾的伸缩项，行高恒定。
        不足 5 条时按实际内容收窄；屏幕太矮时再夹一道 max_h，避免把整屏占满。
        """
        screen = QApplication.primaryScreen()
        avail_h = screen.availableGeometry().height() if screen is not None else 800
        max_h = max(120, avail_h - 40)

        self.list_lay.activate()                       # 先让行布局生效，sizeHint 才准
        rows = self.list_widget.findChildren(TaskRow)
        if rows:
            heights = [r.sizeHint().height() for r in rows]
            visible = sum(heights[:_DOCK_VISIBLE_ROWS])
        else:
            visible = self.list_widget.sizeHint().height()   # 空状态：一个「暂无任务」的高度
        # 窗口非列表部分：上下留白 + 标题 + 标题与列表的间距
        chrome = (_DOCK_VPAD * 2 + self.title.sizeHint().height() + _DOCK_TITLE_GAP)
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
        # 首次显示时样式表字体可能还没落到控件上（sizeHint 偏大/偏小 → 挂件高度不准），
        # 等一轮事件循环后再按真实度量收一次高度。
        QTimer.singleShot(0, self._fit_height)
        # Qt 可能重建原生窗口（窗口标志变化等），每次都重申挂件语义与穿透路由
        # （两者都幂等：桌面挂件语义是回写属性，hitTest 路由同一 view 直接返回）
        if IS_MAC:
            self._apply_mac_outer_style()
        self._install_click_through()
        # 恢复 hover 轮询（隐藏期间已停，见 hideEvent）
        if self._poll_timer is not None and not self._poll_timer.isActive():
            self._poll_timer.start()

    def hideEvent(self, e):  # noqa: N802
        # 挂件看不见时没有任何可交互区域：停掉 40ms 轮询（避免空转吃 CPU），
        # 并收起提示卡、复位 hover（否则下次显示时残留旧高亮）。
        super().hideEvent(e)
        if self._poll_timer is not None:
            self._poll_timer.stop()
        self._hide_tip()
        if self._hover_row is not None:
            self._set_hover_row(None)

    def closeEvent(self, e):  # noqa: N802
        if self._poll_timer is not None:
            self._poll_timer.stop()
        tip = self._tip
        if tip is not None:
            tip.hide()
            tip.deleteLater()
            self._tip = None
        super().closeEvent(e)

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
