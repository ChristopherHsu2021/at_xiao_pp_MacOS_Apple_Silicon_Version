"""应用主题（QSS），贴合 UI 设计稿的奶油橙暖色调。

所有功能窗口统一使用该主题；宠物窗为透明无边框，单独处理。
"""

import sys

from app.ui.screen_fit import scale_qss

# 平台相关字体栈：macOS 没有 Microsoft YaHei，引用它会触发 Qt 每次启动弹出
# "Replace uses of missing font family" 警告并多耗 ~500ms。按平台选首选字体，
# 既消除告警、又保证各平台用上原生中文字体。
if sys.platform == "darwin":
    PRIMARY_FONT = "PingFang SC"
    UI_FONT_STACK = "'PingFang SC', 'Hiragino Sans GB', 'Heiti SC', sans-serif"
elif sys.platform == "win32":
    PRIMARY_FONT = "Microsoft YaHei"
    UI_FONT_STACK = "'Microsoft YaHei', 'PingFang SC', 'Segoe UI', sans-serif"
else:
    PRIMARY_FONT = "Noto Sans CJK SC"
    UI_FONT_STACK = "'Noto Sans CJK SC', 'WenQuanYi Micro Hei', sans-serif"

QSS = scale_qss("""
/* ===== 全局 ===== */
QWidget {
    font-family: {ui_font};
    font-size: 13px;
    color: #3d2b1f;
}
QDialog { background: transparent; }
QLabel { color: #3d2b1f; }
QLabel#muted { color: #a08e7a; }

/* ===== 玻璃卡片窗口 ===== */
QWidget#GlassWindow { background: #fffaf5; border: 1px solid rgba(249,117,16,0.18); border-radius: 16px; }

/* ===== 标题栏 ===== */
.window-bar {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #fff7ee, stop:1 #fdeedf);
    border-top-left-radius: 16px; border-top-right-radius: 16px;
    border-bottom: 1px solid rgba(249,117,16,0.14);
}
.window-title { font-size: 16px; font-weight: 800; color: #3d2b1f; }
.field-label { font-size: 13px; font-weight: 600; color: #6b5744; }

/* ===== 按钮 ===== */
QPushButton {
    background: rgba(249,117,16,0.06);
    border: 1.5px solid rgba(249,117,16,0.22);
    color: #6b5744;
    font-size: 14px; font-weight: 600;
    padding: 8px 18px; border-radius: 12px;
}
QPushButton:hover { background: rgba(249,117,16,0.14); color: #f97510; border-color: rgba(249,117,16,0.4); }
QPushButton:disabled { color: #c9bcae; background: rgba(160,142,122,0.08); border-color: rgba(160,142,122,0.2); }
QPushButton#primary {
    background: #f97510; color: #fff; border: 1.5px solid #f97510;
}
QPushButton#primary:hover { background: #ffa940; border-color: #ffa940; }
QPushButton#danger:hover { color: #e53935; border-color: #e53935; background: rgba(229,57,53,0.06); }

/* ===== 输入框 ===== */
QLineEdit, QComboBox, QDateTimeEdit, QSpinBox {
    background: #fff8f0;
    border: 1.5px solid rgba(249,117,16,0.22);
    border-radius: 8px; padding: 9px 12px;
    color: #3d2b1f; font-size: 14px;
}
QLineEdit:focus, QComboBox:focus, QDateTimeEdit:focus { border-color: #f97510; background: #fff; }
QComboBox QAbstractItemView { background: #fff; selection-background-color: #f97510; }

/* ===== 列表 ===== */
QListWidget { background: rgba(255,255,255,0.7); border: 1px solid rgba(249,117,16,0.14);
    border-radius: 10px; outline: 0; }
QListWidget::item { padding: 10px 14px; border-radius: 8px; }
QListWidget::item:hover { background: rgba(249,117,16,0.10); }
QListWidget::item:selected { background: rgba(249,117,16,0.18); color: #f97510; }

/* ===== 滑块 ===== */
QSlider::groove:horizontal { height: 6px; background: rgba(249,117,16,0.12); border-radius: 3px; }
QSlider::handle:horizontal { width: 18px; height: 18px; margin: -6px 0;
    background: #f97510; border: 3px solid #fff; border-radius: 9px; }
QSlider::sub-page:horizontal { background: #f97510; border-radius: 3px; }

/* ===== 复选/开关 ===== */
QCheckBox { font-size: 14px; color: #6b5744; spacing: 8px; }
QCheckBox::indicator { width: 20px; height: 20px; border: 2px solid rgba(160,142,122,0.35);
    border-radius: 6px; background: #fff; }
QCheckBox::indicator:checked { background: #f97510; border-color: #f97510; }
QCheckBox::indicator:checked { image: url(none); }
QScrollArea { background: transparent; }
QScrollBar:vertical { width: 10px; background: transparent; margin: 4px 0; }
QScrollBar::handle:vertical { background: rgba(160,142,122,0.35); border-radius: 5px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
""").replace("{ui_font}", UI_FONT_STACK)

# 主题色常量（供代码使用）
COLOR = {
    "bg": "#fdf6ee",
    "bg2": "#f5e6d3",
    "orange": "#f97510",
    "orange_light": "#ffa940",
    "green": "#4caf50",
    "text": "#3d2b1f",
    "text2": "#6b5744",
    "gray": "#a08e7a",
    "border": "rgba(249,117,16,0.22)",
    "glass": "rgba(255,255,255,0.92)",
}

GLASS_STYLE = scale_qss(
    "background: #fffaf5; border: 1px solid rgba(249,117,16,0.18);"
    " border-radius: 20px;"
)

# ---------------------------------------------------------------------------
# 任务标题统一渲染（2026-09-21 需求：「TodoDock / 任务清单页面 / 便签页面 三者的任务
# 标题渲染要同步」）
# ---------------------------------------------------------------------------
# 三处此前各写一套，同一个任务标题呈现完全不同的字号：
#   - 任务清单页 / TodoDock 的行标题：LABEL_QSS（旧 13px/500）
#   - 便签卡片标题：QLineEdit#stickyTitle（旧 20px/500 + 下划线）
# → 用户截图里「同一个任务，在清单里是小字、在便签里是大字」。现集中到此处定义，
# 三处（含添加页的标题输入框）引用同一常量，改一处即全局同步。
#
# 为什么取 16px：与「添加/编辑页」的任务标题输入框（QLineEdit#titleInput，16px/600）同源，
# 本就是设计稿里「任务标题」的既定尺度。对列表行/挂件行而言不至于撑高行距（进度 ~24px），
# 对便签标题而言不至于大到与正文脱节。想整体调大/调小：只改 TASK_TITLE_SIZE 一处。
TASK_TITLE_SIZE = 16            # 设计像素（scale_qss 会按 UI_SCALE 等比缩放）
TASK_TITLE_WEIGHT = 600
TASK_TITLE_FG = "#3B2A1A"
TASK_TITLE_DONE_FG = "#A08E7A"


def task_title_qss(done=False):
    """任务标题样式（任务清单行 / TodoDock 行 / 便签标题 共用）。

    ``done=True`` → 灰字 + 删除线（与 ElideLabel.set_done 自绘的删除线同色同义）。
    """
    color = TASK_TITLE_DONE_FG if done else TASK_TITLE_FG
    strike = "text-decoration:line-through;" if done else ""
    return scale_qss(
        f"font-size:{TASK_TITLE_SIZE}px;color:{color};"
        f"font-weight:{TASK_TITLE_WEIGHT};{strike}"
    )


# 区域标题（TodoDock 顶栏「📋 任务清单」与任务清单页顶栏标题共用同一套渲染）
PAGE_TITLE_SIZE = 15
PAGE_TITLE_WEIGHT = 700
PAGE_TITLE_FG = "#3d2b1f"
TITLE_BAR_QSS = scale_qss(
    "QLabel#window-title, QLabel#dockTitle {"
    f"font-size:{PAGE_TITLE_SIZE}px;font-weight:{PAGE_TITLE_WEIGHT};"
    f"color:{PAGE_TITLE_FG};"
    "background:transparent;}"
)


def apply_theme(app):
    """为 QApplication 应用主题。"""
    app.setStyleSheet(QSS)
