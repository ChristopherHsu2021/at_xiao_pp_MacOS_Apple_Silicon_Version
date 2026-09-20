"""MacBook Air 2020（13.3" Retina，默认缩放 **1440×900** 逻辑分辨率）UI 尺寸基准。

集中管理「舒适默认尺寸」（**该默认尺寸同时就是缩放的最小尺寸**），避免各窗口散落硬编码。
取值依据见用户提供的屏幕参数参考文件（物理 286.5×179.1mm / 16:10；逻辑可视区 1440×900；
菜单栏 ≈24pt、Dock ≈64pt → 单窗可用高 ≈812pt）。设计原则：窗口以紧凑的默认尺寸打开，
用户只能「放大」不能缩小到默认之下；除桌宠与桌面 TodoDock 外，所有窗口都可缩放。

仅 darwin 下 make_resizable 生效（无边框窗口追加 NSResizableWindowMask）；其它平台
由既有的 Qt ResizeGrip 自绘握把处理缩放，本模块不改变其逻辑。
"""

from PyQt6.QtCore import QSize

# 逻辑可视区域（UI 基准）
SCREEN_LOGICAL = QSize(1440, 900)

# 桌面 TodoDock 宽度基准（与 _DOCK_WIDTH 对齐，1440×900 基准的 80% = 269；当前未直接使用，保留作参考）
DOCK_BASE_WIDTH = 269

# 各窗口默认尺寸 (w, h) —— 首次打开的舒适大小（按 1440×900 可视区收紧）
# 等比缩放到 MacBook Air 2020 基准的 80%（2026-09-20）：在 1440×900 可视区更克制，
# 单开一两个窗口也能轻松排布；最小尺寸仍 = 默认尺寸（只能放大）。
#
# 2026-09-21 按用户《修改意见》以「1440×900 逻辑可视区 ↔ 桌面截图 1:1」反推校正：
#   - 截图里 1443×904 px 对应 1440×900 pt，故 1 px ≈ 1 pt，可直读窗口像素尺寸；
#   - todo_add → 352×606（原 448 高不够，富文本工具栏与「提醒时间/优先级」互相压盖）
#   - settings → 368×458（按意见附图 1:1 刻算）
#   - sticky   → 320×280（默认高度落到「正文框下横线」处，富文本工具栏下拉后才露出）
#   - alarm_add 默认 432 保持；仅当「重复」选到「仅一次 / 自定义」时临时增高到 490
#     （见 alarm_window.AlarmWindow._add_size_expanded）
WINDOW_DEFAULTS = {
    "todo_list": (352, 368),
    "todo_add": (352, 606),
    "sticky": (320, 280),
    "settings": (368, 458),
    "player": (269, 224),
    "alarm_list": (304, 336),
    "alarm_add": (320, 432),
    "timer": (240, 200),
    "scene": (368, 312),
    "status": (272, 164),
}

# 最小尺寸 = 默认尺寸（用户要求：窗口只能从默认大小「放大」，不能缩到默认之下）
WINDOW_MINS = dict(WINDOW_DEFAULTS)


# ---------------------------------------------------------------------------
# 全局 UI 等比缩放（2026-09-20）：窗口「内饰」（内边距 / 间距 / 字号 / 图标与控件
# 固定尺寸 / 圆角 / 指示器 / 滚动条 / 右键菜单）随默认尺寸一起缩到 1440×900 基准的 80%。
# 仅作用于「像素维度」，颜色 / 百分比 / 坐标 / 时长一律不碰。
# ---------------------------------------------------------------------------
import re as _re

UI_SCALE = 0.8

# 只匹配 px / pt 维度；rgba 颜色（逗号分隔小数）、百分比 N%、坐标、时长都不带 px/pt，安全。
_QSS_DIM_RE = _re.compile(r"(\d+(?:\.\d+)?)(px|pt)\b")


def s(value):
    """把一个像素尺寸等比缩放到 UI_SCALE（0 保持不变；非 0 至少 1px，避免塌成 0）。"""
    if value == 0:
        return 0
    return max(1, int(round(value * UI_SCALE)))


def scale_qss(qss):
    """把样式表里所有 px / pt 维度乘以 UI_SCALE；不动颜色、百分比、坐标等。

    用于「内饰」等比缩放：字号、内边距、圆角、复选/开关指示器、滚动条、滑块、菜单样式等
    全部随窗口一起缩小，视觉上才「整体成比例」。
    """
    def _rep(m):
        v = float(m.group(1))
        if v == 0:
            return m.group(0)          # 0px 保持 0，避免被 s() 抬成 1px
        return f"{s(v)}{m.group(2)}"
    return _QSS_DIM_RE.sub(_rep, qss)


def fit_window(widget, key, resizable=True, max_size=None):
    """按基准给窗口设置「默认大小 + 最小尺寸」并（macOS）开启边缘缩放。

    - widget：顶层窗口（QDialog / QWidget）
    - key：WINDOW_DEFAULTS / WINDOW_MINS 中的键
    - resizable：是否在 macOS 下追加 NSResizableWindowMask（桌宠/TodoDock 传 False）
    - max_size：(w, h) 或 None；None 表示不限制最大（由 Qt/用户决定）
    """
    from app.ui.mac_window import make_resizable

    default = WINDOW_DEFAULTS.get(key, (widget.width(), widget.height()))
    minimum = WINDOW_MINS.get(key, (320, 240))
    widget.setMinimumSize(*minimum)
    if max_size is not None:
        widget.setMaximumSize(*max_size)
    widget.resize(*default)
    if resizable:
        make_resizable(widget, tag=key)
    return widget
