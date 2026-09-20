"""macOS 原生窗口行为适配层（台前调度 / Mission Control / 空间 / 选择性点击穿透）。

为什么需要它
------------
Qt 的跨平台窗口标志在 macOS 上只覆盖了一部分原生语义。桌面挂件类窗口若只用
``Qt.FramelessWindowHint``（= 普通 NSWindow），系统会把它当成 App 的普通主窗口
交给「台前调度(Stage Manager)」管理：当前台窗口（如桌宠）出现时，其它普通窗口
会被移出舞台、缩进屏幕左侧的「最近使用的 App」条里 —— 表现就是**左上角的
TodoDock 挂件凭空消失**（截图里只剩桌宠在舞台上，挂件成了侧边条里的缩略图）。

本模块不绕 Qt 的近似实现，直接对底层 NSWindow 施加 AppKit 语义：

1. ``collectionBehavior`` —— 桌面挂件必须同时具备
   ``CanJoinAllApplications | Stationary | CanJoinAllSpaces |
   FullScreenAuxiliary | IgnoresCycle``：
   可加入所有 App 的舞台、常驻所有空间、不被 Mission Control 挪动、
   不参与窗口循环。WWDC22《What's new in AppKit》明确 Stage Manager 会读取该字段
   （含 ``auxiliary`` / ``stationary`` / ``transient`` 的窗口不会被移出中间舞台）。
2. ``level = NSFloatingWindowLevel`` —— 与 NSPanel（Qt.Tool）一起被台前调度
   视为「浮层面板」，不会被收进侧边条。
3. ``hidesOnDeactivate = NO`` —— Qt.Tool/NSPanel 默认在应用失活时隐藏，
   桌面挂件必须常驻：点开其它软件也不能消失。

4. ``hitTest:`` 路由 —— 给窗口的 content NSView 动态挂一个只覆盖 ``hitTest:``
   的子类：交互区返回自身（事件照常进 Qt 并路由到具体子控件），空白区返回 nil
   （点击穿透到桌面/下层窗口）。**新类必须以该 NSView 的真实类为父类**
   （见 ``install_hit_test_router`` 的注释：换成 NSView 子类会让窗口既不显示
   也收不到事件）。

实现方式：全部走 ctypes + libobjc，不依赖 PyObjC 是否被打进冻结包
（PyObjC 写法在 AppKit 桥接包缺失时会静默失效）。所有函数失败都只返回 False /
写日志，绝不影响主流程。
"""

import ctypes
import ctypes.util
import os
import sys
import time

IS_MAC = sys.platform == "darwin"

# ---------------- NSWindowLevel ----------------
LEVEL_NORMAL = 0
LEVEL_FLOATING = 3
# 桌面层（kCGDesktopIconWindowLevel = kCGDesktopWindowLevel + 1，即 INT32_MIN + 26）。
# ⚠️ 实测不可用（2026-09-21，TodoDock 上验证过，勿再启用）：
#   窗口一旦降到这一层，内容会被系统合成成「半透明发虚」的样子，并且被 Finder 的
#   桌面窗口吃掉全部鼠标事件（hitTest/acceptsFirstMouse 都收不到）→ 挂件完全无法点击。
#   常量保留仅为记录结论、供将来排查；要「不遮挡其它应用」请用 LEVEL_NORMAL。
LEVEL_DESKTOP = -2147483622

# ---------------- NSWindowCollectionBehavior ----------------
BEHAVIOR_CAN_JOIN_ALL_SPACES = 1 << 0
BEHAVIOR_MOVE_TO_ACTIVE_SPACE = 1 << 1
BEHAVIOR_MANAGED = 1 << 2
BEHAVIOR_TRANSIENT = 1 << 3
BEHAVIOR_STATIONARY = 1 << 4
BEHAVIOR_PARTICIPATES_IN_CYCLE = 1 << 5
BEHAVIOR_IGNORES_CYCLE = 1 << 6
BEHAVIOR_FULL_SCREEN_PRIMARY = 1 << 7
BEHAVIOR_FULL_SCREEN_AUXILIARY = 1 << 8
BEHAVIOR_FULL_SCREEN_NONE = 1 << 9
BEHAVIOR_PRIMARY = 1 << 16
BEHAVIOR_AUXILIARY = 1 << 17
BEHAVIOR_CAN_JOIN_ALL_APPLICATIONS = 1 << 18

# 桌面挂件标准组合：不参与台前调度分舞台、常驻所有空间、伴随全屏、不进窗口循环
DESKTOP_WIDGET_BEHAVIOR = (
    BEHAVIOR_CAN_JOIN_ALL_APPLICATIONS
    | BEHAVIOR_STATIONARY
    | BEHAVIOR_CAN_JOIN_ALL_SPACES
    | BEHAVIOR_FULL_SCREEN_AUXILIARY
    | BEHAVIOR_IGNORES_CYCLE
)

# hitTest: 需要的 NSPoint（与 CGPoint 同构）
_NSPoint = None
_HIT_TEST_IMP = []          # 保活 IMP，防止被 GC 后崩溃
_ACCEPTS_FIRST_MOUSE_IMP = []
_ROUTE_BY_VIEW = {}         # NSView 指针 -> (widget, should_capture 回调)
_FIRST_MOUSE_VIEWS = set()  # 已注入过 acceptsFirstMouse: 的 NSView 指针
_CLASS_SEQ = [0]
_LIB = None


# ---------------------------------------------------------------------------
# libobjc 最小封装
# ---------------------------------------------------------------------------
def _objc():
    """惰性加载 libobjc，并声明本模块用到的全部符号原型。"""
    global _LIB, _NSPoint
    if _LIB is not None:
        return _LIB

    path = ctypes.util.find_library("objc") or "/usr/lib/libobjc.A.dylib"
    lib = ctypes.CDLL(path)

    lib.sel_registerName.restype = ctypes.c_void_p
    lib.sel_registerName.argtypes = [ctypes.c_char_p]
    lib.objc_getClass.restype = ctypes.c_void_p
    lib.objc_getClass.argtypes = [ctypes.c_char_p]

    lib.object_getClass.restype = ctypes.c_void_p
    lib.object_getClass.argtypes = [ctypes.c_void_p]
    lib.object_getClassName.restype = ctypes.c_char_p
    lib.object_getClassName.argtypes = [ctypes.c_void_p]
    lib.object_setClass.restype = ctypes.c_void_p
    lib.object_setClass.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    lib.objc_allocateClassPair.restype = ctypes.c_void_p
    lib.objc_allocateClassPair.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
    lib.objc_registerClassPair.restype = None
    lib.objc_registerClassPair.argtypes = [ctypes.c_void_p]
    lib.class_addMethod.restype = ctypes.c_bool
    lib.class_addMethod.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p
    ]

    class NSPoint(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    _NSPoint = NSPoint
    _LIB = lib
    return lib


def _sel(name: str):
    return _objc().sel_registerName(name.encode("utf-8"))


def _send_ptr(obj_ptr, sel_name):
    """id 返回值的消息（如 view.window()）。"""
    lib = _objc()
    fn = lib.objc_msgSend
    fn.restype = ctypes.c_void_p
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    return fn(ctypes.c_void_p(obj_ptr), ctypes.c_void_p(_sel(sel_name)))


def _send_uint(obj_ptr, sel_name):
    """NSUInteger 返回值的消息（如 window.collectionBehavior）。"""
    lib = _objc()
    fn = lib.objc_msgSend
    fn.restype = ctypes.c_ulong
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    return int(fn(ctypes.c_void_p(obj_ptr), ctypes.c_void_p(_sel(sel_name))))


def _send_long(obj_ptr, sel_name):
    """NSInteger 返回值的消息（如 window.level）。"""
    lib = _objc()
    fn = lib.objc_msgSend
    fn.restype = ctypes.c_long
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    return int(fn(ctypes.c_void_p(obj_ptr), ctypes.c_void_p(_sel(sel_name))))


def _send_cstr(obj_ptr, sel_name):
    """const char* 返回值的消息（如 object_getClassName 之外的对象方法名）。"""
    lib = _objc()
    fn = lib.objc_msgSend
    fn.restype = ctypes.c_char_p
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    return fn(ctypes.c_void_p(obj_ptr), ctypes.c_void_p(_sel(sel_name)))


def _send_void_uint(obj_ptr, sel_name, value):
    lib = _objc()
    fn = lib.objc_msgSend
    fn.restype = None
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    fn(ctypes.c_void_p(obj_ptr), ctypes.c_void_p(_sel(sel_name)), ctypes.c_ulong(int(value)))


def _send_void_long(obj_ptr, sel_name, value):
    lib = _objc()
    fn = lib.objc_msgSend
    fn.restype = None
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
    fn(ctypes.c_void_p(obj_ptr), ctypes.c_void_p(_sel(sel_name)), ctypes.c_long(int(value)))


def _send_void_bool(obj_ptr, sel_name, value):
    lib = _objc()
    fn = lib.objc_msgSend
    fn.restype = None
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
    fn(ctypes.c_void_p(obj_ptr), ctypes.c_void_p(_sel(sel_name)), ctypes.c_bool(bool(value)))


# ---------------------------------------------------------------------------
# 诊断日志：打包后的 .app 没有可见 stdout，静默失败会让排查从零开始
# ---------------------------------------------------------------------------
def mac_log(message: str, tag: str = "mac") -> None:
    """把关键结论追加到 <用户数据目录>/atpp_mac_debug.log（超过 128KB 自动重开）。"""
    if not IS_MAC:
        return
    try:
        from app.core.pathutil import get_data_dir

        path = os.path.join(get_data_dir(), "atpp_mac_debug.log")
        if os.path.exists(path) and os.path.getsize(path) > 128 * 1024:
            os.remove(path)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {tag}: {message}\n")
    except Exception:  # noqa: BLE001
        pass


def mac_debug_log_path() -> str:
    """日志文件路径（供界面/文档引用）。"""
    try:
        from app.core.pathutil import get_data_dir

        return os.path.join(get_data_dir(), "atpp_mac_debug.log")
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# 1) 桌面挂件语义：台前调度不会把它移出舞台
# ---------------------------------------------------------------------------
def ns_window_pointer(widget):
    """取 widget 的底层 NSWindow*（Qt 顶层窗口的 winId() 就是 content NSView*）。"""
    if not IS_MAC:
        return None
    try:
        view = int(widget.winId())
        if not view:
            return None
        win = _send_ptr(view, "window")
        return int(win) if win else None
    except Exception:  # noqa: BLE001
        return None


_LOGGED_FAIL = set()   # 同一 tag 的失败只记一次，避免定时重申刷爆日志


def apply_stage_exempt(widget, floating=None, tag="app-window", verbose=False, level=None):
    """macOS：让窗口不被「台前调度 / Mission Control / 空间切换」收走或重排。

    这是**整个软件**层面的豁免，卡片窗口（待办/闹钟/计时/设置/播放器/场景）与
    桌面挂件（桌宠 / TodoDock / 歌词浮窗）都要有，否则切到别的 App 时本程序窗口
    会被整体移出舞台，缩到屏幕左侧的「最近使用的 App」条里。

    - ``hidesOnDeactivate = NO``：面板（Qt.Tool）默认在应用失活时隐藏，桌面常驻
      窗口必须关掉。
    - ``collectionBehavior = DESKTOP_WIDGET_BEHAVIOR``：加入所有 App 的舞台
      (CanJoinAllApplications) + 常驻所有空间 (CanJoinAllSpaces) + 不被 Mission
      Control 挪动 (Stationary) + 伴随全屏 (FullScreenAuxiliary) + 不进窗口循环
      (IgnoresCycle)。
    - ``floating``：None = **不动层级**（保留现有置顶/让路逻辑，卡片窗口用这个）；
      True/False = 同时锁定浮层/普通层级（桌面挂件用 True）。
    - ``level``：显式层级覆盖，支持 ``"desktop"``（→ LEVEL_DESKTOP，桌面层）。
      桌面挂件（TodoDock）用它把自己压到所有 App 窗口之下，做到「不遮挡其它应用」。
      与 ``floating`` 同时给出时以 ``level`` 为准。

    幂等，可随定时/状态变化反复重申。返回 True 表示已生效（回读校验）。
    """
    if not IS_MAC:
        return False
    try:
        view = int(widget.winId())
        if not view:
            return False
        win = _send_ptr(view, "window")
        if not win:
            _fail_log(tag, f"取不到 NSWindow（view={view}）")
            return False
        win = int(win)

        want_desktop = (level == "desktop")
        _send_void_bool(win, "setHidesOnDeactivate:", False)
        if want_desktop:
            _send_void_long(win, "setLevel:", LEVEL_DESKTOP)
        elif floating is not None:
            _send_void_long(win, "setLevel:", LEVEL_FLOATING if floating else LEVEL_NORMAL)
        _send_void_uint(win, "setCollectionBehavior:", DESKTOP_WIDGET_BEHAVIOR)

        cur_level = _send_long(win, "level")
        behavior = _send_uint(win, "collectionBehavior")
        if want_desktop:
            level_ok = (cur_level == LEVEL_DESKTOP)
        elif floating is True:
            level_ok = cur_level >= LEVEL_FLOATING
        else:
            level_ok = True
        if (behavior & DESKTOP_WIDGET_BEHAVIOR) == DESKTOP_WIDGET_BEHAVIOR and level_ok:
            if verbose:
                mac_log(
                    f"{tag}: NSWindow={win} view={view} level={cur_level} "
                    f"behavior=0x{behavior:x} ✅（台前调度豁免已生效）",
                    tag="mac",
                )
            return True
        _fail_log(tag, f"原生设置未完全生效 level={cur_level} behavior=0x{behavior:x}")
        return False
    except Exception as exc:  # noqa: BLE001
        _fail_log(tag, f"原生窗口设置异常 {exc!r}")
        return False


def _fail_log(tag, message):
    """失败日志按 tag 去重（定时器会反复重申，不能每次都写文件）。"""
    if tag in _LOGGED_FAIL:
        return
    _LOGGED_FAIL.add(tag)
    mac_log(f"{tag}: {message}", tag="mac-error")


def apply_desktop_widget_style(widget, floating=True, tag="desktop-widget", verbose=False,
                               level=None):
    """把窗口登记为「桌面挂件」：台前调度/调度中心/空间切换都动不了它。

    = apply_stage_exempt(...) + 锁定层级（floating=True → 浮层；level="desktop" → 桌面层）。
    """
    return apply_stage_exempt(widget, floating=floating, tag=tag, verbose=verbose, level=level)


def set_window_level(widget, floating, tag="level"):
    """轻量层级切换：浮层(NSFloatingWindowLevel) / 普通层(NSNormalWindowLevel)。

    与 ``apply_stage_exempt`` 分工：本函数**只改 level**，不碰 collectionBehavior、
    不改 hidesOnDeactivate —— 供极高频调用（如 TodoDock 每 30ms 的光标轮询里
    「悬停抬层 / 离开落层」）使用，开销仅 1~2 次 objc 消息。

    为什么需要它（2026-09-21 实测）：
    macOS **不会**把鼠标事件投递给被其它窗口覆盖的窗口（与 Windows 的 WM_NCHITTEST
    穿透模型不同）。桌面挂件若长期待在 NSNormalWindowLevel，其它 App 的窗口一盖上来，
    挂件就同时失去 hover 与 click —— 用户反馈「不管焦点在哪儿都应该能点/能 hover」
    与「不能遮挡其它应用」是同一对矛盾需求，唯一解就是**动态层级**：
    光标进入挂件范围 → 抬到浮层（此时才盖住别人、也才收得到鼠标）；
    光标离开 → 落回普通层（不再遮挡任何界面）。空白区穿透仍由 hitTest 路由保证，
    所以抬层期间挂件矩形内的「空白」依然把点击让给下层窗口。

    幂等；返回 True 表示已处于目标层级。非 darwin 直接返回 False。
    """
    if not IS_MAC:
        return False
    try:
        view = int(widget.winId())
        if not view:
            return False
        win = _send_ptr(view, "window")
        if not win:
            return False
        win = int(win)
        target = LEVEL_FLOATING if floating else LEVEL_NORMAL
        if _send_long(win, "level") == target:
            return True
        _send_void_long(win, "setLevel:", target)
        if _send_long(win, "level") == target:
            return True
        _fail_log(tag, f"setLevel 未生效（target={target}）")
        return False
    except Exception as exc:  # noqa: BLE001
        mac_log(f"{tag}: set_window_level 异常 {exc!r}", tag="mac-error")
        return False


def iter_exempt_candidates():
    """枚举「本程序所有应当免除台前调度管理」的顶层窗口。

    用 ``QApplication.topLevelWidgets()`` 全量枚举，而不是维护一份写死的窗口清单 ——
    用户要求「整个软件系统完全、一点也不能受台前调度影响」，将来新增的任何窗口
    （便签、消息框、安装器、预览卡…）都自动被覆盖，不会再漏。

    排除瞬时窗口：Popup（右键菜单 / 自绘下拉面板）/ ToolTip / SplashScreen ——
    它们本就该跟随父窗口瞬时出现，给它们挂 CanJoinAllApplications 反而会让菜单
    出现在所有 App 的舞台上（错位弹窗）。
    """
    if not IS_MAC:
        return []
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt as _Qt
    except Exception:  # noqa: BLE001
        return []
    transient = (
        _Qt.WindowType.Popup
        | _Qt.WindowType.ToolTip
        | _Qt.WindowType.SplashScreen
    )
    out = []
    for w in QApplication.topLevelWidgets():
        try:
            if w is None or not w.isWindow() or not w.isVisible():
                continue
            if w.windowType() & transient:
                continue
            out.append(w)
        except Exception:  # noqa: BLE001
            continue
    return out


# ---------------------------------------------------------------------------
# 3) 无边框窗口的「用户可缩放」：给 NSWindow 追加 NSResizableWindowMask
# ---------------------------------------------------------------------------
# Qt 的 FramelessWindowHint 在 macOS 下会把 NSWindow 的 styleMask 设为
# NSWindowStyleMaskBorderless(0) —— 没有标题栏/边框，也就没有原生缩放握把，
# 用户无法从边缘拖拽改变窗口大小。绝大多数「玻璃卡片」工具窗口都因此只能固定大小。
# 解决：给 styleMask 追加 NSResizableWindowMask（1<<3），macOS 就会在边缘提供
# 缩放光标与拖拽缩放（即使视觉上无边框）。Qt 自己在 setMinimumSize/setMaximumSize
# 时已对窗口几何做最小/最大钳制，原生缩放会被它自动夹紧，无需再同步 content size。
# 该调用幂等、仅 darwin 生效；失败只记日志不影响主流程。
NS_WINDOW_STYLE_MASK_RESIZABLE = 1 << 3


def make_resizable(widget, tag="resizable"):
    """macOS：让无边框（FramelessWindowHint）窗口可由用户从边缘自由缩放。

    适用对象：所有「玻璃卡片」工具窗口（待办/便签/设置/播放器/闹钟/计时/场景/
    状态面板等）。**不适用**：桌宠与桌面 TodoDock（用户明确要求固定不可缩放）。
    其它平台（Qt 已有 ResizeGrip 自绘握把的窗口）原样返回，不影响现有逻辑。

    仅追加 styleMask 的 resizable 位；不改动层级、不改动 collectionBehavior、
    不改动最小/最大尺寸（由调用方的 setMinimumSize 决定）。
    """
    if not IS_MAC:
        return False
    try:
        view = int(widget.winId())
        if not view:
            return False
        win = _send_ptr(view, "window")
        if not win:
            _fail_log(tag, f"取不到 NSWindow（view={view}）")
            return False
        win = int(win)
        cur = _send_uint(win, "styleMask")
        if cur & NS_WINDOW_STYLE_MASK_RESIZABLE:
            return True
        _send_void_uint(win, "setStyleMask:", cur | NS_WINDOW_STYLE_MASK_RESIZABLE)
        after = _send_uint(win, "styleMask")
        if after & NS_WINDOW_STYLE_MASK_RESIZABLE:
            mac_log(f"{tag}: NSWindow={win} styleMask=0x{after:x} 已追加 resizable（可边缘缩放）",
                    tag="mac")
            return True
        _fail_log(tag, f"styleMask 追加 resizable 未生效（before=0x{cur:x} after=0x{after:x}）")
        return False
    except Exception as exc:  # noqa: BLE001
        mac_log(f"{tag}: make_resizable 异常 {exc!r}", tag="mac-error")
        return False


# ---------------------------------------------------------------------------
# 2) 选择性点击穿透：覆盖 content NSView 的 hitTest:
# ---------------------------------------------------------------------------
def _hit_test_imp():
    """构造并缓存 hitTest: 的 C 函数指针。"""
    if _HIT_TEST_IMP:
        return _HIT_TEST_IMP[0]

    point_type = _NSPoint

    def _impl(self_ptr, _sel_ptr, a_point):
        entry = _ROUTE_BY_VIEW.get(self_ptr)
        if entry is None:
            # 不是本模块接管的视图 → 原样返回自身，绝不干扰其它 Qt 窗口
            return self_ptr
        widget, should_capture = entry
        try:
            # 坑：hitTest: 传入的点是**窗口基准坐标系（左下原点）**，
            # 而 Qt 的坐标是左上原点，必须按窗口高度翻转 y，否则命中区上下颠倒。
            local_y = float(widget.height()) - a_point.y
            if should_capture(a_point.x, local_y):
                return self_ptr        # 交互区：交给本窗口，Qt 再路由到具体子控件
        except Exception:  # noqa: BLE001
            return self_ptr
        return 0                        # nil → 穿透到桌面/下层窗口

    sig = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, point_type)
    imp = sig(_impl)
    _HIT_TEST_IMP.append(imp)           # 保活
    return imp


def _accepts_first_mouse_imp():
    """构造并缓存 ``acceptsFirstMouse:`` 的 C 函数指针（固定返回 YES）。"""
    if _ACCEPTS_FIRST_MOUSE_IMP:
        return _ACCEPTS_FIRST_MOUSE_IMP[0]

    def _impl(self_ptr, _sel_ptr, _event_ptr):
        return 1                        # YES

    sig = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    imp = sig(_impl)
    _ACCEPTS_FIRST_MOUSE_IMP.append(imp)   # 保活
    return imp


def install_hit_test_router(widget, should_capture, tag="hit-test"):
    """给顶层窗口挂上「空白穿透、交互区可点」的 hitTest: 路由。

    ``should_capture(local_x, local_y) -> bool``：判断窗口本地坐标（**左上原点**）
    是否落在交互区（复选框/文字/标题/滚动区）。

    关键坑（务必不要回退成旧写法）：**新类必须以该 NSView 的真实类为父类**
    （``object_getClass``），不能以 NSView 为父类。Qt 的 content NSView 是 QNSView
    （继承自 NSView），窗口绘制与事件分发全部由它自己的方法完成；若把类换成
    「NSView 的子类」，QNSView 的实现整批丢失 —— 窗口既不显示、也收不到任何事件。
    只覆盖 hitTest: 时，QNSView 其余行为原样保留。

    同时覆盖 ``acceptsFirstMouse:`` 返回 YES（2026-09-21 补）：
    AppKit 默认对「非 key 窗口」不投递首次点击（第一次点击只用来激活本 App），
    桌面挂件要「单击即生效」就必须放开。空白区在 hitTest: 已返回 nil、
    根本走不到这里，所以无条件 YES 不会让挂件抢走桌面的点击。

    返回 True 表示注入成功（同一 view 重复注入是幂等的）。
    """
    if not IS_MAC:
        return False
    try:
        lib = _objc()
        view = int(widget.winId())
        if not view:
            return False
        if view in _ROUTE_BY_VIEW:              # 同一原生视图重复注入 → 幂等
            _ROUTE_BY_VIEW[view] = (widget, should_capture)
            return True

        base_cls = lib.object_getClass(ctypes.c_void_p(view))
        if not base_cls:
            raise RuntimeError("object_getClass 返回空")

        _CLASS_SEQ[0] += 1
        new_cls = lib.objc_allocateClassPair(
            ctypes.c_void_p(base_cls), f"ATWidgetHitTestView{_CLASS_SEQ[0]}".encode(), 0
        )
        if not new_cls:
            raise RuntimeError("objc_allocateClassPair 失败")
        imp = _hit_test_imp()
        if not lib.class_addMethod(
            ctypes.c_void_p(new_cls), ctypes.c_void_p(_sel("hitTest:")),
            ctypes.cast(imp, ctypes.c_void_p), b"@@:{CGPoint=dd}"
        ):
            raise RuntimeError("class_addMethod hitTest: 失败")
        # 非 key 窗口也要「单击即响应」（BOOL 在 x86_64 上是 char → 编码用 c）
        imp_first = _accepts_first_mouse_imp()
        if not lib.class_addMethod(
            ctypes.c_void_p(new_cls), ctypes.c_void_p(_sel("acceptsFirstMouse:")),
            ctypes.cast(imp_first, ctypes.c_void_p), b"c@:@"
        ):
            mac_log(f"{tag}: class_addMethod acceptsFirstMouse: 失败（不影响穿透）",
                    tag="mac-error")
        lib.objc_registerClassPair(ctypes.c_void_p(new_cls))
        lib.object_setClass(ctypes.c_void_p(view), ctypes.c_void_p(new_cls))

        _ROUTE_BY_VIEW[view] = (widget, should_capture)
        base_name = lib.object_getClassName(ctypes.c_void_p(base_cls)) or b"?"
        mac_log(
            f"{tag}: hitTest 路由已挂上 view={view} 父类={base_name.decode()} "
            f"→ ATWidgetHitTestView{_CLASS_SEQ[0]}",
            tag="mac",
        )
        return True
    except Exception as exc:  # noqa: BLE001
        mac_log(f"{tag}: hitTest 注入失败 {exc!r}", tag="mac-error")
        return False


def enable_first_mouse(widget, tag="first-mouse"):
    """macOS：让窗口在「App 未激活」时也能「首次点击即生效」。

    2026-09-21 需求背景（用户反馈「用户设置的闹钟点击人物无法暂停播报」）：
    AppKit 默认对非 key 窗口**不投递首次鼠标事件** —— 第一次点击只用来激活本 App，
    mousedown/mouseup 被吞掉。桌宠是置顶浮窗，用户几乎总是在「别的 App 在前台」的
    状态下点它（闹钟响的时候更是如此），于是 PetWindow.mouseReleaseEvent 不触发
    → _on_click 不执行 → ctx.stop_alarm() 不调用 → 播报停不下来。
    覆盖 ``acceptsFirstMouse:`` 返回 YES 后，这一次点击会同时完成「激活 + 投递」。

    与 ``install_hit_test_router`` 的分工：本函数**只加 acceptsFirstMouse:**，
    完全不碰 hitTest:（桌宠需要整窗可点，没有「空白穿透」需求）。两者可叠加使用，
    但要各自幂等，所以重复注入按 view 指针去重。

    实现要点（坑与 hitTest 路由一致）：新类必须以该 NSView 的**真实类**为父类
    （``object_getClass``），不能以 NSView 为父类，否则 QNSView 的绘制/事件分发
    实现整批丢失 → 窗口既显示不出来也收不到事件。

    返回 True 表示已注入（同一 view 重复调用幂等）。
    """
    if not IS_MAC:
        return False
    try:
        lib = _objc()
        view = int(widget.winId())
        if not view:
            return False
        if view in _FIRST_MOUSE_VIEWS:
            return True
        if view in _ROUTE_BY_VIEW:
            # 已被 hitTest 路由接管过（那条路已顺带加了 acceptsFirstMouse:）
            _FIRST_MOUSE_VIEWS.add(view)
            return True

        base_cls = lib.object_getClass(ctypes.c_void_p(view))
        if not base_cls:
            raise RuntimeError("object_getClass 返回空")

        _CLASS_SEQ[0] += 1
        new_cls = lib.objc_allocateClassPair(
            ctypes.c_void_p(base_cls), f"ATFirstMouseView{_CLASS_SEQ[0]}".encode(), 0
        )
        if not new_cls:
            raise RuntimeError("objc_allocateClassPair 失败")
        imp = _accepts_first_mouse_imp()
        if not lib.class_addMethod(
            ctypes.c_void_p(new_cls), ctypes.c_void_p(_sel("acceptsFirstMouse:")),
            ctypes.cast(imp, ctypes.c_void_p), b"c@:@"
        ):
            raise RuntimeError("class_addMethod acceptsFirstMouse: 失败")
        lib.objc_registerClassPair(ctypes.c_void_p(new_cls))
        lib.object_setClass(ctypes.c_void_p(view), ctypes.c_void_p(new_cls))
        _FIRST_MOUSE_VIEWS.add(view)
        mac_log(f"{tag}: acceptsFirstMouse 已开启 view={view}", tag="mac")
        return True
    except Exception as exc:  # noqa: BLE001
        mac_log(f"{tag}: acceptsFirstMouse 注入失败 {exc!r}", tag="mac-error")
        return False
