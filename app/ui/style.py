"""应用主题（QSS），贴合 UI 设计稿的奶油橙暖色调。

所有功能窗口统一使用该主题；宠物窗为透明无边框，单独处理。
"""

import sys

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

QSS = ("""
/* ===== 全局 ===== */
QWidget {
    font-family: {ui_font};
    color: #3d2b1f;
}
QDialog { background: transparent; }
QLabel { color: #3d2b1f; }
QLabel#muted { color: #a08e7a; }

/* ===== 玻璃卡片窗口 ===== */
QWidget#GlassWindow { background: #fffaf5; border: 1px solid rgba(249,117,16,0.18); border-radius: 12px; }

/* ===== 标题栏 ===== */
.window-bar {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #fff7ee, stop:1 #fdeedf);
    border-top-left-radius: 12px; border-top-right-radius: 12px;
    border-bottom: 1px solid rgba(249,117,16,0.14);
}
.window-title { font-size: 15px; font-weight: 700; color: #3d2b1f; }
.field-label { font-size: 12px; font-weight: 600; color: #6b5744; }

/* ===== 按钮 ===== */
QPushButton {
    background: rgba(249,117,16,0.06);
    border: 1.5px solid rgba(249,117,16,0.22);
    color: #6b5744;
    font-size: 13px; font-weight: 600;
    padding: 7px 16px; border-radius: 12px;
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
    border-radius: 8px; padding: 8px 10px;
    color: #3d2b1f; font-size: 13px;
}
QLineEdit:focus, QComboBox:focus, QDateTimeEdit:focus { border-color: #f97510; background: #fff; }
QComboBox QAbstractItemView { background: #fff; selection-background-color: #f97510; }

/* ===== 列表 ===== */
QListWidget { background: rgba(255,255,255,0.7); border: 1px solid rgba(249,117,16,0.14);
    border-radius: 10px; outline: 0; }
QListWidget::item { padding: 9px 12px; border-radius: 8px; }
QListWidget::item:hover { background: rgba(249,117,16,0.10); }
QListWidget::item:selected { background: rgba(249,117,16,0.18); color: #f97510; }

/* ===== 滑块 ===== */
QSlider::groove:horizontal { height: 6px; background: rgba(249,117,16,0.12); border-radius: 3px; }
QSlider::handle:horizontal { width: 18px; height: 18px; margin: -6px 0;
    background: #f97510; border: 3px solid #fff; border-radius: 9px; }
QSlider::sub-page:horizontal { background: #f97510; border-radius: 3px; }

/* ===== 复选/开关 ===== */
QCheckBox { font-size: 13px; color: #6b5744; spacing: 8px; }
QCheckBox::indicator { width: 20px; height: 20px; border: 2px solid rgba(160,142,122,0.35);
    border-radius: 6px; background: #fff; }
QCheckBox::indicator:checked { background: #f97510; border-color: #f97510; }
QCheckBox::indicator:checked { image: url(none); }
QScrollArea { background: transparent; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 4px 0; }
QScrollBar::handle:vertical { background: rgba(160,142,122,0.35); border-radius: 4px; min-height: 28px; }
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

GLASS_STYLE = (
    "background: #fffaf5; border: 1px solid rgba(249,117,16,0.18);"
    " border-radius: 20px;"
)


def apply_theme(app):
    """为 QApplication 应用主题。"""
    app.setStyleSheet(QSS)
