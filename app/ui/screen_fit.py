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

# 桌面 TodoDock 宽度基准（保持 336；仅当存在「带提醒」任务时对齐列表页宽度）
DOCK_BASE_WIDTH = 336

# 各窗口默认尺寸 (w, h) —— 首次打开的舒适大小（按 1440×900 可视区收紧）
WINDOW_DEFAULTS = {
    "todo_list": (440, 460),
    "todo_add": (440, 560),
    "sticky": (400, 380),
    "settings": (460, 520),
    "player": (336, 280),
    "alarm_list": (380, 420),
    "alarm_add": (400, 540),
    "timer": (300, 250),
    "scene": (460, 390),
    "status": (340, 205),
}

# 最小尺寸 = 默认尺寸（用户要求：窗口只能从默认大小「放大」，不能缩到默认之下）
WINDOW_MINS = dict(WINDOW_DEFAULTS)


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
