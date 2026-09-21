"""待办清单窗口：全选 / 添加 / 删除 / 勾选划线，本地持久化，每周一清理。

页面拆分：
- 列表页（默认视图）：渲染与交互保持原样，仅「点击任务标题文字」改为无行为（右键菜单仍可编辑/删除）。
- 添加/编辑页：按 index.html 设计重建（标题输入 + 富文本编辑器 + 提醒 + 优先级 + 保存/取消）。
- 窗口改为可缩放（无边框边缘/角落拖拽），布局随窗口宽度自适应；卜卜 PeekCard 背景摆放与透明度不变。
"""

from PyQt6.QtWidgets import (
    QDialog, QWidget, QLabel, QPushButton, QLineEdit, QTextEdit, QDateTimeEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QBoxLayout, QAbstractButton, QCalendarWidget, QSizePolicy, QFrame,
    QGraphicsDropShadowEffect, QComboBox, QApplication,
)
from PyQt6.QtCore import (
    Qt, QDateTime, QTimer, QEvent, QSize, QRectF, QPointF,
    QPropertyAnimation, QEasingCurve, pyqtProperty,
)
from PyQt6.QtGui import (
    QColor, QFontMetrics, QPainter, QPen, QBrush, QCursor, QIcon, QPainterPath,
    QPolygonF, QVector3D, QPalette, QLinearGradient,
)

from app.core import todo, config
from app.core import alarm as alarm_mod
from app.core.voice import say
from app.core.i18n import tr
from app.core.todo_signals import bus
from app.ui.common import (
    PeekCard, NoticeDialog, promote_popup_topmost,
    EditContextMenu, CTX_MENU_TEXT_QSS, guard_ui, note_front, keep_on_top,
)
from app.ui.screen_fit import fit_window, scale_qss, s, WINDOW_DEFAULTS
from app.ui.style import (
    TASK_TITLE_FG, TASK_TITLE_SIZE, TASK_TITLE_WEIGHT,
    TITLE_BAR_QSS, PAGE_TITLE_SIZE, task_title_qss,
)
from app.ui.mac_window import apply_stage_exempt, set_resizable
from app.ui.context_menu import ActionPopupMenu, ACTION_POPUP_QSS
from app.ui.rich_editor import RichEditor, svg_icon


# 「任务标题」字体本体（字号/字重/颜色）在 WINDOW_QSS 里的插值片段 —— 取值全部来自
# app/ui/style.TASK_TITLE_*，与清单行 / TodoDock 行 / 便签标题同源（改 style.py 一处即可）。
# 注意：WINDOW_QSS 外层还有一层 scale_qss，所以这里写的是**设计像素**（不要自己缩放）。
_TITLE_INPUT_FONT = (
    f"font-size:{TASK_TITLE_SIZE}px;font-weight:{TASK_TITLE_WEIGHT};"
    f"color:{TASK_TITLE_FG};"
)


WINDOW_QSS = scale_qss("""
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
    /* 顶栏「📋 任务清单」标题：与 TodoDock 顶栏共用同一套渲染。
       样式本体在 app/ui/style.TITLE_BAR_QSS（widget 级设定，见 TodoWindow._build），
       这里刻意不再写死一份，避免两处数字各自漂移（三处标题渲染同步的需求根源）。 */
    background: transparent;
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
/* 标题输入框就是「任务标题」这套渲染在添加页的落点：字号/字重/颜色从
   app/ui/style.TASK_TITLE_* 插值进来（**不再手写数字**），改 style.py 一处即可全局同步。 */
QLineEdit#titleInput {
    border: 1.5px solid #F1E4D3; border-radius: 14px;
    background: #FFFDFA; """ + _TITLE_INPUT_FONT + """
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
""")


CHECK_QSS = scale_qss("""
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
""")

# 任务标题（列表行 / TodoDock 行 / 便签标题）统一取自 app/ui/style.task_title_qss：
# 字号、字重、颜色、完成态颜色只有一处定义（需求：「三者的任务标题渲染要同步」）。
LABEL_QSS = task_title_qss(False)
DONE_LABEL_QSS = task_title_qss(True)
# 列表行右侧信息标签（对齐 index.html 的 .tag / .tag.p-low / .tag.p-mid / .tag.p-high：
# 小号圆角标签，低=绿 / 中=橙 / 高=红）。
# 注意：QSS 的 border-radius 在大半径（如 999px）时会被 Qt 完全忽略（实测 8px 才生效），
# 故改用自绘的 TagLabel（见下方类），确保圆角真实可见、文字不裁切。
TAG_BG, TAG_FG = "#F4F0E8", "#8A7358"
_TAG_PRIO_COLORS = {"低": ("#EDF7EC", "#4C9A54"),
                    "中": ("#FFF7EE", "#EA6A1F"),
                    "高": ("#FDECEC", "#C53D36")}
# 便签左上角「优先级呼吸灯」的实心圆颜色：低=绿 / 中=橙 / 高=红。
# ★ 2026-09-21 提高区分度/对比度（用户反馈「tododock/便签页面的优先级显示区分度、
#   颜色对比度不高」）：原来的 #43C463 / #F97316 / #E5534C 三色亮度接近（绿偏亮、
#   橙偏亮、红居中），在 12px 的小圆点上、「低 vs 中」「中 vs 高」远看容易混。
#   现改为色相拉开 + 饱和度拉满的一档主色：绿更正、橙更纯、红更沉，肉眼一眼可分。
_PRIO_DOT_COLORS = {"低": "#16A34A",
                    "中": "#F97316",
                    "高": "#DC2626"}
# 优先级「实心标签」底色（TodoDock 玻璃标签、便签顶部文字 chip 共用）：
# 把主色再压深一档，使「纯白字 + 饱和底」的对比度 ≥ 4.5:1
# （白字压在主色 #16A34A / #F97316 上只有 ~2.0 对比度，压深后才有 5:1 左右）。
_PRIO_TAG_FILL = {"低": "#15803D",
                  "中": "#B45309",
                  "高": "#B91C1C"}
# 兼容旧名（TodoDock 玻璃标签此前引用的是 _PRIO_DOT_COLORS）
_PRIO_GLASS_FILL = _PRIO_TAG_FILL


def priority_tag_colors(prio: str):
    """优先级标签配色（与 index.html 的 .tag.p-low/.p-mid/.p-high 一致）。"""
    return _TAG_PRIO_COLORS.get(prio, (TAG_BG, TAG_FG))


class TagLabel(QLabel):
    """自绘圆角标签：用 QPainter 画圆角矩形背景（radius 指定，默认胶囊形），
    避免 QSS border-radius 大半径被 Qt 忽略导致圆角不生效；
    文字居中绘制，不会被裁切。用于列表行右侧的「提醒时间 / 优先级」标签。

    玻璃模式（glass=True，桌面挂件 TodoDock 的优先级标签使用）：
    全透明挂件贴在桌面上，实色标签会显得很"贴纸"。这里改成
    「带颜色的半透明毛玻璃」——
      1) 彩色半透明底（alpha≈0.30，桌面/壁纸透出来，底色仍保留色相）；
      2) 上白下暗的纵向渐变（玻璃的厚度与反光感）；
      3) 同色系细描边（alpha≈0.55，勾出玻璃边缘，避免半透明糊掉边界）；
      4) 文字色压深一档，保证在半透明底上仍然清晰。
    纯 Qt 绘制、跨平台一致，不依赖任何原生模糊/截屏（mac 上抓屏会触发
    屏幕录制权限弹窗，故不采用真·背景模糊）。"""

    # 玻璃模式的绘制参数（集中在此，便于统一调参）
    # 注意：玻璃底色用**优先级实底色**（_PRIO_TAG_FILL：低绿/中橙/高红），不能用标签的
    # 浅色底（#FDECEC 那类浅色半透明后几乎等于白色，在浅色壁纸上完全看不出颜色）。
    #
    # ★ 2026-09-21 提高对比度（用户反馈「优先级颜色对比度不高」）：
    #   旧参数填充 alpha 只有 95（≈0.37）→ 一旦贴在浅色壁纸/浅色桌面图标上，三档颜色
    #   都被冲淡成「差不多的浅色块」，既分不出档位、白/深字也都不够醒目。
    #   现把填充提到 225（≈0.88，桌面只透出一点点氛围），描边加深，并用纯白文字—— 
    #   深绿/深琥珀/深红 三底 + 白字，档位区分与文字对比度同时达标。
    _GLASS_FILL_ALPHA = 225       # 彩色底不透明度（越接近 255 越"实"，颜色越认得清）
    _GLASS_EDGE_ALPHA = 235       # 描边透明度
    _GLASS_TOP_LIGHT = 38         # 顶部高光（白），压低避免把饱和底洗淡
    _GLASS_MID_LIGHT = 10         # 中段高光
    _GLASS_BOTTOM_SHADE = 30      # 底部暗调（玻璃厚度）
    _GLASS_TEXT = (255, 255, 255)  # 玻璃模式文字色：实底上纯白对比度最高

    def __init__(self, text="", bg=TAG_BG, fg=TAG_FG, radius=8, glass=False, parent=None):
        super().__init__(text, parent)
        self._bg = QColor(bg)
        self._fg = QColor(fg)
        self._radius = float(radius)
        self._glass = bool(glass)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setContentsMargins(s(10), s(3), s(10), s(3))
        if self._glass:
            # 桌面挂件上的白字小标签：加粗一档，深底白字才不"发虚"
            f = self.font()
            f.setBold(True)
            self.setFont(f)

    def set_colors(self, bg, fg):
        self._bg, self._fg = QColor(bg), QColor(fg)
        self.update()

    def set_glass(self, on: bool):
        """切换毛玻璃模式（桌面挂件用 True，卡片列表页保持实色）。"""
        on = bool(on)
        if on != self._glass:
            self._glass = on
            self.update()

    def paintEvent(self, e):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        if self._glass:
            self._paint_glass(painter, rect)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._bg)
            painter.drawRoundedRect(rect, self._radius, self._radius)
        # 文字：玻璃模式改用纯白（填充已接近不透明，白字对比度最高；
        # 旧的「把文字色压深」在半透明浅底上才有意义，现在的实底上反而会糊）
        text_color = self._fg
        if self._glass:
            text_color = QColor(*self._GLASS_TEXT)
        painter.setPen(text_color)
        painter.setFont(self.font())
        painter.drawText(self.rect(),
                         int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter),
                         self.text())

    def _paint_glass(self, painter, rect):
        """毛玻璃底：半透明彩色 + 上白下暗渐变 + 同色系细描边。"""
        r = self._radius
        # 1) 彩色半透明底
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._bg.red(), self._bg.green(), self._bg.blue(),
                                self._GLASS_FILL_ALPHA))
        painter.drawRoundedRect(rect, r, r)

        # 2) 玻璃厚度：纵向渐变（顶亮、底暗）。渐变直接当画刷画圆角矩形 ——
        #    天然贴合圆角，不需要 setClipPath（那套写法在本项目的 Qt/offscreen
        #    组合下会直接崩进程，已实测排除）。
        grad = QLinearGradient(0, rect.top(), 0, rect.bottom() + 1)
        grad.setColorAt(0.0, QColor(255, 255, 255, self._GLASS_TOP_LIGHT))
        grad.setColorAt(0.55, QColor(255, 255, 255, self._GLASS_MID_LIGHT))
        grad.setColorAt(1.0, QColor(0, 0, 0, self._GLASS_BOTTOM_SHADE))
        painter.setBrush(QBrush(grad))
        painter.drawRoundedRect(rect, r, r)

        # 3) 同色系细描边：勾出玻璃边缘（纯半透明会糊掉边界）。
        #    坑（实测）：先前用「setBrush(Qt.BrushStyle.NoBrush) + QPen(color, 1)
        #    + QRect.adjusted(0.5,...) 描边」这套写法，在本项目的 Qt 组合下绘制时
        #    直接崩进程（无 traceback，进程静默退出）。改为「透明 QColor 画刷 +
        #    原矩形 + 浮点线宽 + 显式 PenStyle」后稳定，别再改回去。
        edge = self._bg.darker(140)
        painter.setBrush(QColor(0, 0, 0, 0))     # 透明画刷：只描边不填充
        painter.setPen(QPen(QColor(edge.red(), edge.green(), edge.blue(),
                                   self._GLASS_EDGE_ALPHA),
                            1.0, Qt.PenStyle.SolidLine))
        painter.drawRoundedRect(rect, r, r)

class ElideLabel(QLabel):
    """单行标题标签：宽度不足时右侧省略号；鼠标悬停时横向滑动展示完整文字。

    关键：覆盖 minimumSizeHint 返回极小宽度，允许在 HBoxLayout 中被压缩，
    把剩余空间让给右侧的「提醒时间 / 优先级」标签（Fixed 不收缩），避免遮挡它们。
    显示长度随右侧标签宽度自动变化（有提醒时间则更短，无则更长）—— 纯由布局 + 重绘决定。
    """

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._full = text or ""
        self._extra_tip = ""     # 附加 hover 提示（如 TodoDock 的「提醒时间：年-月-日 时:分」）
        self._offset = 0.0
        self._hover = False
        # 是否由「外部」驱动 hover（macOS 桌面挂件 TodoDock：App 非激活时 Qt 根本不派发
        # hover，见 app/ui/todo_dock.py 的「hover」小节）。外部接管时忽略原生 enter/leave，
        # 并关掉原生 tooltip（提示改由挂件自绘卡片给出），避免两套 hover 互相打架。
        self._external_hover = False
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
        self._refresh_tooltip()

    def set_extra_tip(self, text):
        """附加 hover 提示：TodoDock 取消「提醒时间」常显后，改在任务标题上 hover 显示。

        2026-09-21 需求（用户截图）：hover 白框**只用于显示提醒时间**，不再附带标题/内容
        全文——长标题在卡片里折行会把桌面糊住（截图里白框内容就是被省略标题的全文）。
        没有提醒时间的任务 → 不设提示（``has_hover_info()`` 为假 → 任何位置都不弹框）。
        标题本身过长时仍可读全：悬停时行内「跑马灯」横向滑动（见 paintEvent）。
        """
        self._extra_tip = text or ""
        self._refresh_tooltip()

    def hover_tip_text(self):
        """hover 提示全文 = 仅「提醒时间」（空串表示不该弹提示框）。"""
        return self._extra_tip

    def has_hover_info(self):
        """是否该弹 hover 提示框：**只取决于有没有提醒时间**（2026-09-21 需求）。

        原实现还会在「标题被省略」时弹框显示标题全文，现按需求取消：hover 白框只承载
        提醒时间，没有提醒时间就没有白框。
        """
        return bool(self._extra_tip)

    def set_external_hover_owner(self, external):
        """把本标签的 hover 交给外部驱动（桌面挂件轮询）。

        - 外部接管：关掉原生 mouseTracking 与原生 tooltip（提示由挂件自绘卡片给出）。
        - 交还原生：恢复 mouseTracking 并按 _extra_tip/_full 重挂 tooltip。
        """
        self._external_hover = bool(external)
        if self._external_hover:
            self.setMouseTracking(False)
            self.setToolTip(None)
        else:
            self.setMouseTracking(True)
            self._refresh_tooltip()

    def set_hovered(self, on):
        """hover 状态的**唯一入口**：原生 enter/leave 与外部轮询都走这里。

        统一入口是必须的：挂件上「Qt 原生 hover」与「挂件轮询 hover」都可能触发，
        若各自改 _hover / 各自启停动画，两者会在边界处互相打断（跑马灯反复重启动）。
        """
        on = bool(on)
        if on == self._hover:
            return
        self._hover = on
        if on:
            full_w = self.fontMetrics().horizontalAdvance(self._full)
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
        else:
            self._anim.stop()
            self._offset = 0.0
        self.update()

    def _refresh_tooltip(self):
        if self._external_hover:
            self.setToolTip(None)      # 外部接管：提示改由挂件自绘提示卡给出
            return
        # 只挂「提醒时间」；没有提醒时间 → 不挂 tooltip（不弹白框）——2026-09-21 需求。
        self.setToolTip(self._extra_tip or None)

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
        # 唯一入口：外部接管（桌面挂件轮询）时忽略原生 hover，避免两套状态互相打断
        if not self._external_hover:
            self.set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        if not self._external_hover:
            self.set_hovered(False)
        super().leaveEvent(event)


CALENDAR_QSS = scale_qss("""
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
""")


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
        self.setFixedSize(s(42), s(24))
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
    """任务复选框（自绘圆角方框 + 对勾）。

    2026-09-21 按《修改意见》：复选框整体缩小一档（22 → 19，再经 80% 全局缩放 → 15px）。
    同时把勾选几何从「写死的像素坐标」改为「按控件尺寸的等比分数」——原来的
    (6,11)/(9,15)/(16,6) 是按 22px 画的，控件缩小后对勾会偏大偏外，现在任意尺寸都居中成比例。
    """

    # 设计尺寸（会经 s() 缩放到当前 UI_SCALE）；TodoDock 复用本类，样式自动一致
    DESIGN_SIZE = 19

    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        side = s(self.DESIGN_SIZE)
        self.setFixedSize(side, side)
        self.setStyleSheet("QPushButton{background:transparent;border:none;padding:0;margin:0;}")

    def paintEvent(self, e):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        w, h = rect.width(), rect.height()
        radius = w * 0.28
        stroke = max(1.0, w * 0.10)
        if not self.isChecked():
            pen = QPen(QColor(160, 142, 122, 76), stroke)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, radius, radius)
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#ff7613")))
        painter.drawRoundedRect(rect, radius, radius)
        # 对勾：三点等比（相对内框的分数与 22px 设计稿一致 → 25%/50%、40%/70%、75%/25%）
        pen = QPen(QColor("#ffffff"), max(1.0, w * 0.10))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        tick = [QPointF(rect.left() + w * 0.25, rect.top() + h * 0.50),
                QPointF(rect.left() + w * 0.40, rect.top() + h * 0.70),
                QPointF(rect.left() + w * 0.75, rect.top() + h * 0.25)]
        painter.drawPolyline(QPolygonF(tick))


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
    def __init__(self, task, on_toggle, on_edit=None, on_delete=None, on_interact=None,
                 enable_context_menu=True, open_sticky_on_click=True, glass_tag=False,
                 show_remind_tag=True):
        """glass_tag=True：优先级标签用「带颜色的半透明毛玻璃」底（桌面挂件 TodoDock 用）。

        列表页/便签页仍是实色卡片背景，标签保持实色更清晰 → 默认 False。

        show_remind_tag=False（TodoDock 用）：不显示「提醒时间」标签 —— 该标签是
        「年-月-日 时:分」的长串，会明显撑宽挂件；改为在任务标题上挂 hover 提示
        「提醒时间：年-月-日 时:分」。
        """
        super().__init__()
        # ★ 行高永久固定为自身 sizeHint：绝不接受布局分来的额外空间。
        #   否则一旦父布局比内容高（例如窗口高度被算大、或平台字体度量变了），Qt 会把
        #   多余空间塞进「唯一可伸展」的行里 → 行被拉高、内容垂直居中 → 表现为
        #   「头部与首项之间、项与项之间的间距忽大忽小」（用户实测 macOS 上交互后
        #   任务行间距翻倍）。任务清单页与桌面挂件 TodoDock 共用本行控件。
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.glass_tag = bool(glass_tag)
        self.task = task
        self.on_toggle = on_toggle
        self.on_edit = on_edit
        self.on_delete = on_delete
        self.on_interact = on_interact
        self.enable_context_menu = enable_context_menu
        if enable_context_menu:
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        else:
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(s(8), s(10), s(8), s(10))
        lay.setSpacing(s(10))
        self.check = TodoCheckBox()
        self.check.setChecked(task["done"])
        self.check.toggled.connect(self._toggled)
        self.check.contextMenuEvent = self._show_context_menu if enable_context_menu else (lambda e: None)
        # 列表页：标题文字点击不做任何行为（按需求临时改为无操作），保留右键菜单编辑/删除。
        self.text = ElideLabel(task.get("title") or task.get("content") or "")
        self.text.setStyleSheet(LABEL_QSS)
        self.text.setCursor(Qt.CursorShape.PointingHandCursor)
        if enable_context_menu:
            self.text.contextMenuEvent = self._show_context_menu
        # 左键点击标题文字 → 打开便签式任务卡片窗口（右键仍走编辑/删除菜单）
        if open_sticky_on_click:
            self.text.mousePressEvent = self._on_title_press
        # 右侧信息（对齐 index.html 的 .tc-meta）：提醒时间（有提醒才显示）+ 优先级（必有）
        remind = task.get("remind") if task.get("remind_enabled", True) else None
        due_text = self._format_remind(remind)
        prio = task.get("priority") or "中"
        self.meta = QWidget()
        meta_lay = QHBoxLayout(self.meta)
        meta_lay.setContentsMargins(s(0), s(0), s(0), s(0))
        meta_lay.setSpacing(s(8))
        if due_text and show_remind_tag:
            meta_lay.addWidget(self._make_tag(due_text, TAG_BG, TAG_FG))
        if due_text and not show_remind_tag:
            # TodoDock：取消「提醒时间」常显（长串会撑宽挂件）→ 改为标题 hover 提示
            self.text.set_extra_tip(f"{tr('提醒时间')}：{due_text}")
        # 优先级标签文字跟随语言（低/中/高 → Low/Medium/High）；配色仍按原始中文键查表，
        # 数据库里的 priority 值保持「低/中/高」不改，避免破坏既有数据与逻辑。
        prio_bg, prio_fg = priority_tag_colors(prio)
        if self.glass_tag:
            # 毛玻璃底改用优先级**实底色**（_PRIO_TAG_FILL：低绿/中橙/高红）：
            # 浅色底（#EDF7EC 那类）半透明后等于白色，在桌面上完全看不出优先级。
            prio_bg = _PRIO_TAG_FILL.get(prio, prio_bg)
        meta_lay.addWidget(
            self._make_tag(tr(prio), prio_bg, prio_fg, glass=self.glass_tag))
        self.meta.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        if enable_context_menu:
            self.meta.contextMenuEvent = self._show_context_menu
        lay.addWidget(self.check)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.meta)
        self._apply()

    def _make_tag(self, text, bg, fg, radius=8, glass=False):
        """右侧圆角标签；不给它收缩空间，保证标签文字永远完整。"""
        tag = TagLabel(text, bg, fg, radius, glass=glass)
        if self.enable_context_menu:
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
        if self.enable_context_menu:
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

    def set_done_state(self, done):
        """由全局 ``done_changed`` 信号驱动：就地刷新本行标题渲染（删除线 + 置灰）。

        不重持久化——持久化已由信号源（``todo.toggle`` / ``todo.set_done``）完成。
        幂等：done 没变就早退，所以「信号源自己那一行」收到自己的广播也不会重复做事。

        注意：必须用 ``blockSignals`` 包住 ``setChecked``——否则设复选框会触发它的
        ``toggled`` → 再次进入 ``_toggled`` → 二次 ``todo.toggle`` 把状态翻回 → 死循环/抖动。
        """
        done = bool(done)
        if self.task.get("done") == done:
            return
        self.task["done"] = done
        self.check.blockSignals(True)
        try:
            self.check.setChecked(done)
        finally:
            self.check.blockSignals(False)
        self._apply()


# 任务清单（列表页）窗口尺寸（MacBook Air 2020 / 1440×900 基准：宽与桌面挂件对齐，
# 高放宽到 560 可多显示约 8~9 条任务）。桌面挂件 TodoDock 也以它的宽度为基准：
# 挂件里只要存在「带提醒时间」的任务，宽度就对齐到列表页（见 _DOCK_WIDTH_WITH_REMIND）。
LIST_WINDOW_SIZE = (352, 368)


class TodoWindow(QDialog):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._drag_pos = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._list_size = LIST_WINDOW_SIZE
        # 添加/编辑页默认尺寸：352×606（2026-09-21 按意见附图 1:1 反推）。
        # 原 352×448 装不下「任务标题 + 富文本工具栏(两行) + 提醒时间 + 优先级 + 底部按钮」，
        # 表现为内容互相压盖（意见里「混杂显示不清」）。
        self._add_size = (352, 606)
        # 最小尺寸 = 各模式默认尺寸（用户要求：只能从默认大小放大，不能缩小）
        # （列表页 440 宽 = 标题 + 四个按钮 + 边距，英文模式最宽，留足余量）
        self._list_min = self._list_size
        self._add_min = self._add_size
        # 卜卜在添加/编辑页以「底面 1/3 半径的 1/4 圆」展示，大小随窗口缩放
        # （由 PeekCard.set_quarter_radius 在 resize 时按宽度动态设置）；
        # 列表页 add_mode=False，完全保持原样（零 UI 改动）。
        self.editing_task = None
        self.priority = "中"
        # 便签窗口注册表：task_id -> StickyNoteWindow（用于列表↔便签双向同步与删除时关闭）
        self.sticky_windows = {}
        self.setMinimumSize(*self._list_min)
        self.resize(*self._list_size)
        # macOS：无边框窗口追加 NSResizableWindowMask，可由用户从边缘自由缩放
        # （Windows 端复用既有 ResizeGrip 自绘握把，本调用 darwin 下才生效）
        fit_window(self, "todo_list", resizable=True)
        self._build()
        self._build_grips()
        # 订阅全局 done_changed：列表行 / 便签（若已打开）就地刷新标题渲染，
        # 与「Dock 勾选 / 便签勾选」也即时同步（无需整表重建）。UniqueConnection 防重复连。
        bus().done_changed.connect(self._on_done_changed,
                                    Qt.ConnectionType.UniqueConnection)

    def _build(self):
        frame_root = QVBoxLayout(self)
        frame_root.setContentsMargins(s(0), s(0), s(0), s(0))
        frame_root.setSpacing(s(0))

        self.container = PeekCard(self, scale=1.08)
        self.container.setObjectName("GlassWindow")
        self.container.setStyleSheet(WINDOW_QSS)
        shadow = QGraphicsDropShadowEffect(self.container)
        shadow.setBlurRadius(s(22))
        shadow.setOffset(s(0), s(8))
        shadow.setColor(QColor(180, 120, 50, 32))
        self.container.setGraphicsEffect(shadow)
        frame_root.addWidget(self.container)

        outer = QVBoxLayout(self.container)
        outer.setContentsMargins(s(0), s(0), s(0), s(0))
        outer.setSpacing(s(0))

        self.header = QWidget()
        self.header.setObjectName("window-bar")
        self.header.setFixedHeight(s(58))
        header_lay = QHBoxLayout(self.header)
        header_lay.setContentsMargins(s(18), s(0), s(18), s(0))
        header_lay.setSpacing(s(6))
        self.title_label = QLabel("📋 " + tr("任务清单"))
        self.title_label.setObjectName("window-title")
        # 顶栏标题样式与 TodoDock 顶栏同源（style.TITLE_BAR_QSS）→ 两处渲染完全一致
        self.title_label.setStyleSheet(TITLE_BAR_QSS)
        header_lay.addWidget(self.title_label)
        header_lay.addStretch(1)
        # 编辑态专属：关闭按钮（自绘 X 图标，不再使用字符 ✕）
        self.close_b = QPushButton()
        self.close_b.setObjectName("todoClose")
        self.close_b.setIcon(QIcon(svg_icon("close", 18, "#8A7358")))
        self.close_b.setIconSize(QSize(s(18), s(18)))
        self.close_b.setFixedSize(s(34), s(34))
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
            b.setFixedHeight(s(32))
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
        root.setContentsMargins(s(0), s(0), s(0), s(0))
        root.setSpacing(s(0))

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
        self.list_lay.setContentsMargins(s(12), s(8), s(12), s(12))
        self.list_lay.setSpacing(s(0))
        self.scroll.setWidget(self.list_widget)
        root.addWidget(self.scroll, 1)

        # ===== 添加/编辑面板（匹配 index.html 设计） =====
        self.add_panel = QWidget()
        self.add_panel.setObjectName("add-panel")
        self.add_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.add_panel.setVisible(False)
        ap_root = QVBoxLayout(self.add_panel)
        ap_root.setContentsMargins(s(0), s(0), s(0), s(0))
        ap_root.setSpacing(s(0))

        # 页面主体不放滚动区：表单整体随窗口缩放自适应，
        # 只有「任务内容」编辑区自身可滚动（满足“主体无滚动条、仅内容可滚动”）。
        self.add_content = QWidget()
        self.add_content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        ac = QVBoxLayout(self.add_content)
        # 内容框透明、整宽铺满：卜卜透过透明内容显示，不另起空白列（详见 PeekCard 的
        # 1/4 圆 + 45° 左上平移，使嘴巴/眼睛完整露出）。
        ac.setContentsMargins(s(24), s(18), s(24), s(6))
        ac.setSpacing(s(16))
        self._narrow = None  # 窄宽度内边距状态缓存

        # 任务标题
        # ★ 字段标签提升为实例属性：原先是局部变量 → retranslate_ui 拿不到引用，
        #   切语言后仍是旧语言（这正是截图里「任务标题/任务内容/提醒时间/优先级」
        #   在英文模式下残留中文的根因）。
        self.f_title_label = QLabel()
        self.f_title_label.setObjectName("fieldLabel")
        self.f_title_label.setTextFormat(Qt.TextFormat.RichText)
        title_label = self.f_title_label
        title_label.setText(tr("任务标题") + ' <span style="color:#F97316;font-weight:700">*</span>')
        self.title_in = QLineEdit()
        self.title_in.setObjectName("titleInput")
        self.title_in.setPlaceholderText(tr("给任务起个标题，比如：完成季度复盘"))
        self.title_in.setFixedHeight(s(44))
        self.title_in.setMaxLength(80)
        self.title_in.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        ac.addWidget(title_label)
        ac.addWidget(self.title_in)

        # 任务内容（富文本）
        self.f_content_label = QLabel(tr("任务内容"))
        self.f_content_label.setObjectName("fieldLabel")
        content_label = self.f_content_label
        self.editor = RichEditor()
        self.editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.editor_frame = QFrame()
        self.editor_frame.setObjectName("editorFrame")
        self.editor_frame.setProperty("focused", False)
        self.editor_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        fl = QVBoxLayout(self.editor_frame)
        fl.setContentsMargins(s(0), s(0), s(0), s(0))
        fl.setSpacing(s(0))
        fl.addWidget(self.editor)
        # 编辑区聚焦时高亮外框（Qt QSS 不支持 :focus-within，改用动态属性）
        self.editor.focusIn.connect(lambda: self._set_editor_focus(True))
        self.editor.focusOut.connect(lambda: self._set_editor_focus(False))
        ac.addWidget(content_label)
        ac.addWidget(self.editor_frame, 1)

        # 提醒时间 + 优先级
        meta = QHBoxLayout()
        meta.setSpacing(s(16))
        self.meta_row = meta
        # 提醒
        remind_col = QVBoxLayout()
        remind_col.setSpacing(s(6))
        remind_head = QHBoxLayout()
        remind_head.setSpacing(s(6))
        self.f_remind_label = QLabel(tr("提醒时间"))
        self.f_remind_label.setObjectName("fieldLabel")
        rlab = self.f_remind_label
        # 与优先级列的表头等高，保证两列的「输入控件」起始 y 对齐
        rlab.setFixedHeight(s(24))
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
        self.remind_in.setFixedHeight(s(40))
        self.remind_in.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.remind_in.setEnabled(False)
        self.remind_chk.toggled.connect(self._on_remind_toggled)
        remind_col.addLayout(remind_head)
        remind_col.addWidget(self.remind_in)
        meta.addLayout(remind_col, 1)
        # 优先级
        prio_col = QVBoxLayout()
        prio_col.setSpacing(s(6))
        self.f_prio_label = QLabel(tr("优先级"))
        self.f_prio_label.setObjectName("fieldLabel")
        plab = self.f_prio_label
        plab.setFixedHeight(s(24))  # 与提醒列的表头等高（含开关），两列控件对齐
        prio_col.addWidget(plab)
        chips_row = QHBoxLayout()
        chips_row.setSpacing(s(8))
        self.chips = []
        for p in ("低", "中", "高"):
            chip = QPushButton(tr(p))
            chip.setObjectName("todoChip")
            # 窄窗时也保证 chips 不被压扁（宽度不足时由提醒栏让位）
            chip.setMinimumWidth(s(58))
            chip.setFixedHeight(s(40))  # 与提醒时间输入框等高，两列底部对齐
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
        footer.setContentsMargins(s(24), s(12), s(24), s(18))
        footer.setSpacing(s(12))
        self.footer_lay = footer
        footer.addStretch(1)
        self.cancel_b = QPushButton(tr("取消"))
        self.save_b = QPushButton(tr("保存任务"))
        self.cancel_b.setObjectName("panelCancel")
        self.save_b.setObjectName("panelSave")
        self.cancel_b.setFixedHeight(s(42))
        self.save_b.setFixedHeight(s(42))
        # 不设最小宽度：窄窗（470）时按钮要能和右侧卜卜让位区共存，不互相挤压
        self.cancel_b.setMinimumWidth(s(0))
        self.save_b.setMinimumWidth(s(0))
        self.cancel_b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_b.clicked.connect(self._hide_editor)
        self.save_b.clicked.connect(self._save)
        footer.addWidget(self.cancel_b)
        footer.addWidget(self.save_b)
        ap_root.addWidget(self.footer)

        root.addWidget(self.add_panel)

        self._apply_responsive_margins()
        self._apply_field_labels()   # 字段标签 + 编辑器文案统一由该方法落地（便于切语言复用）
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
        """顶部四个按钮宽度：在「任务清单」标题完整显示的前提下尽量收窄。

        2026-09-21 需求：按钮宽度减小，让各语言下的标题（任务清单 / 任務清單 / Task List）
        完整显示。原实现固定 62/68px，四个按钮 + 间距 + 页边距把 352px 窗口挤到标题只剩
        ~46px → 「任务清单」被截断。

        2026-09-21 二次修正（用户反馈「『添加』两字显示不全」）：
        原实现用「统一公式 文本宽 + 2*s(13)」算宽度，**忽略了四个按钮的内边距并不相同**——
        ``QPushButton#todoPrimary`` 是 ``padding: 0 14px``，``todoSecondary/todoDanger`` 是
        ``padding: 0 10px``（见 WINDOW_QSS）。四个按钮被强行设成同一宽度后，主按钮「添加」
        的内容区比其它按钮窄 2*s(4)≈6.4px，于是只有它被裁掉半边字；英文（Delete 最长）还会
        因测量字体不是粗体（QSS 是 font-weight:700）而低估宽度。

        现改为**直接问 Qt 要 sizeHint**：QStyleSheetStyle 会把该按钮自己的 QSS 字号 +
        内边距 + 边框 + 文本宽度全部算进去，主/次按钮各自准确，将来改 QSS 也自动跟随。
        sizeHint 会写下固定宽度约束，所以调用前先复位 min/max，保证可重复调用（切语言）。
        """
        btns = (self.sel_all, self.add_b, self.del_b, self.back_b)
        for b in btns:
            # 复位上一次 setFixedWidth 留下的约束，否则 sizeHint 会直接返回旧宽度（自锁）
            b.setMinimumWidth(0)
            b.setMaximumWidth(16777215)          # QWIDGETSIZE_MAX
        # 每个按钮按自己的 QSS 内边距算；取四者最大值 → 四个按钮等宽且都不裁字
        need = max(b.sizeHint().width() for b in btns)
        # ★ 保险余量（别删）：主按钮「添加」的 sizeHint 与「文字宽 + 内边距」几乎贴平
        #   （实测内容区宽 == 文字宽，零余量）。而 Windows 微软雅黑与 macOS PingFang SC
        #   的汉字步进并不完全相同，零余量在 mac 上会再次裁掉半个字。留 ~6px 冗余。
        slack = int(round(s(8)))
        w = max(int(round(s(48))), int(need) + slack)   # 下限保证点击热区
        # 标题保底宽度：任何语言下「📋 任务清单」都完整可见（布局优先满足它）
        title_font = self.title_label.font()
        title_font.setPixelSize(s(PAGE_TITLE_SIZE))   # 同 style.TITLE_BAR_QSS 的 font-size
        tfm = QFontMetrics(title_font)
        title_min = tfm.horizontalAdvance(self.title_label.text()) + s(4)
        self.title_label.setMinimumWidth(title_min)
        # ★ 最后夹一道：保证「4 按钮 + 3 间距 + 页边距 + 标题保底」不超出设计宽度。
        #   否则英文（Delete 最长）在 macOS 字体下变宽时，固定宽按钮会把标题挤出窗口。
        #   用 WINDOW_DEFAULTS 的设计宽而非 self.header.width()：本方法在构造期被调用，
        #   那时 header 还没被布局赋予真实宽度，读它会得到无效值。
        layout = self.header.layout()
        if layout is not None:
            m = layout.contentsMargins()
            design_w = WINDOW_DEFAULTS.get("todo_list", (352, 368))[0]
            budget = design_w - m.left() - m.right() - layout.spacing() * (len(btns) - 1) - title_min
            if budget > 0:
                w = min(w, max(int(round(s(48))), budget // len(btns)))
        for b in btns:
            b.setFixedWidth(int(w))

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
            empty.setStyleSheet(scale_qss("color:#a08e7a;font-size:16px;padding:20px;"))
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list_lay.addWidget(empty)
        for t in tasks:
            self.list_lay.addWidget(
                TaskRow(t, self._after_task_toggle, self._edit_task,
                        self._delete_task, self.ctx.stop_alarm)
            )
        self.list_lay.addStretch(1)
        self._prune_stickies()
        # 同步刷新常驻任务清单挂件（若已创建）
        dock = getattr(self.ctx, "todo_dock", None)
        if dock is not None:
            dock.refresh()

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
        # 编辑已有任务时：若该任务便签已打开，实时预览呼吸灯颜色。
        # 定稿在编辑结束时完成（保存→新色；返回/取消→按存储回退），见 _hide_editor。
        task = getattr(self, "editing_task", None)
        if task:
            win = self.sticky_windows.get(task.get("id"))
            if win is not None and hasattr(win, "preview_priority"):
                win.preview_priority(prio)

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
        edited_id = self.editing_task.get("id") if self.editing_task else None
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
        # 编辑结束：让该任务的便签呼吸灯回到「存储里的真实优先级」——
        # 保存 → 新优先级（_save 已写库）；返回/取消 → 旧优先级（回退实时预览）。
        if edited_id is not None:
            win = self.sticky_windows.get(edited_id)
            if win is not None:
                win.sync_state()

    def _apply_field_labels(self):
        """刷新添加/编辑页的字段标签（含必填星号）+ 富文本编辑器内部文案。

        这些标签原先在 _build() 里用局部变量创建，切语言时无法被更新 →
        英文模式下 「任务标题/任务内容/提醒时间/优先级」残留中文（用户截图问题）。
        """
        if hasattr(self, "f_title_label"):
            self.f_title_label.setText(
                tr("任务标题") + ' <span style="color:#F97316;font-weight:700">*</span>')
        if hasattr(self, "f_content_label"):
            self.f_content_label.setText(tr("任务内容"))
        if hasattr(self, "f_remind_label"):
            self.f_remind_label.setText(tr("提醒时间"))
        if hasattr(self, "f_prio_label"):
            self.f_prio_label.setText(tr("优先级"))
        editor = getattr(self, "editor", None)
        if editor is not None and hasattr(editor, "retranslate"):
            editor.retranslate()

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
        # 添加/编辑页文案（字段标签 + 富文本编辑器工具栏/占位）
        self._apply_field_labels()
        self.title_in.setPlaceholderText(tr("给任务起个标题，比如：完成季度复盘"))
        self.cancel_b.setText(tr("取消"))
        self.save_b.setText(tr("保存任务"))
        for chip, p in zip(self.chips, ("低", "中", "高")):
            chip.setText(tr(p))
            chip.setProperty("active", self.priority == p)
            chip.style().polish(chip)
        # 已打开的便签卡片同步切语言（标题占位、工具栏、优先级呼吸灯提示）
        for win in list(getattr(self, "sticky_windows", {}).values()):
            if win is not None and hasattr(win, "retranslate_ui"):
                win.retranslate_ui()
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
            # 重新聚焦已开的便签：记为最近使用并抬到最前，避免被其它卡片盖住
            note_front(existing, raise_now=True)
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

    def _on_done_changed(self, tid, done):
        """全局完成态变化（来自列表/Dock/便签任意入口）：就地刷新本窗口的相关渲染。

        - 列表里该任务的行：``TaskRow.set_done_state``（删除线 + 置灰），不整表重建。
        - 该任务已打开的便签窗口：``sync_state`` 刷标题删除线/颜色与确认键。
        信号源自己那一行/便签也会收到广播，处理函数幂等，不会重复做事。
        """
        for row in self.findChildren(TaskRow):
            if row.task.get("id") == tid:
                row.set_done_state(done)
                break
        sticky = self.sticky_windows.get(tid)
        if sticky is not None:
            sticky.sync_state()

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

# 便签默认背景色（= STICKY_COLORS 的「主题色」）。持久化在 todos.json 的 bg 字段，
# 打开便签时读回；未设置过的老任务按此默认值渲染。
STICKY_DEFAULT_BG = "#fffaf5"

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
        bl.setContentsMargins(s(14), s(6), s(10), s(6))
        bl.setSpacing(s(6))
        lbl = QLabel(tr("便签背景"))
        # 与上方菜单项（复制任务/清空内容/撤销…）字体样式保持一致：同为 CTX_MENU_TEXT_QSS(13px)，
        # 不再单独压成 12px（否则「便签背景」比其它项明显小一号）。
        lbl.setStyleSheet(CTX_MENU_TEXT_QSS)
        bl.addWidget(lbl)
        sw_row = QWidget()
        sl = QHBoxLayout(sw_row)
        sl.setContentsMargins(s(0), s(0), s(0), s(0))
        sl.setSpacing(s(6))
        for _name, col in STICKY_COLORS:
            sw = QPushButton()
            sw.setFixedSize(s(18), s(18))
            sw.setCursor(Qt.CursorShape.PointingHandCursor)
            sw.setToolTip(tr(_name))
            sw.setStyleSheet(scale_qss(
                f"background:{col};border:1px solid #ccc;border-radius:9px;"))
            sw.clicked.connect(lambda _checked=False, c=col: self._set_bg(c))
            sl.addWidget(sw)
        sl.addStretch(1)
        bl.addWidget(sw_row)
        lay.addWidget(bg_row)

    def _set_bg(self, col):
        # 与菜单项走同一条关闭链路（_trigger 内含已销毁防护）
        self._trigger(lambda: self.sticky.set_bg(col))


class PriorityPulseDot(QWidget):
    """便签卡片左上角的「优先级呼吸灯」：小号实心圆 + 缓慢明暗/大小往复（呼吸灯效果）。

    - 颜色按任务优先级：低=绿 / 中=橙 / 高=红（见 _PRIO_DOT_COLORS）。
    - 呼吸曲线用 QPropertyAnimation 三关键帧 (0.25 → 1.0 → 0.25) + InOutSine，
      循环无限；同时驱动「核心透明度」与「外圈柔光半径」，视觉上像一盏呼吸的指示灯。
    - 设 WA_TransparentForMouseEvents：点击可穿过它落到卡片背景，
      因此顶部栏仍可整条拖动（不因多了一个圆点而丢掉左上角的拖拽热区）。
    """

    _MIN, _MAX = 0.25, 1.0

    def __init__(self, prio="中", diameter=12, parent=None):
        super().__init__(parent)
        self._d = diameter
        self._color = QColor(_PRIO_DOT_COLORS.get(prio, _PRIO_DOT_COLORS["中"]))
        self._pulse = self._MAX
        self.setFixedSize(diameter, diameter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 呼吸灯动画：父对象设为 self，随控件一起销毁，无泄漏
        self._anim = QPropertyAnimation(self, b"pulse", self)
        self._anim.setDuration(1800)
        self._anim.setKeyValueAt(0.0, self._MIN)
        self._anim.setKeyValueAt(0.5, self._MAX)
        self._anim.setKeyValueAt(1.0, self._MIN)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.start()

    # --- 动画属性：0.25（最暗/最小）→ 1.0（最亮/最大） ---
    def _get_pulse(self):
        return self._pulse

    def _set_pulse(self, value):
        self._pulse = float(value)
        self.update()

    pulse = pyqtProperty(float, fget=_get_pulse, fset=_set_pulse)

    def set_priority(self, prio):
        """任务优先级变化时更新呼吸灯颜色。"""
        self._color = QColor(_PRIO_DOT_COLORS.get(prio, _PRIO_DOT_COLORS["中"]))
        self.update()

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        t = (self._pulse - self._MIN) / (self._MAX - self._MIN)   # 0..1
        # 外圈柔光：半径随呼吸微涨、透明度随呼吸增强
        glow = QColor(self._color)
        glow.setAlphaF(0.13 + 0.20 * t)
        r_glow = self.width() * (0.40 + 0.10 * t)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QRectF(cx - r_glow, cy - r_glow, r_glow * 2, r_glow * 2))
        # 核心实心圆：透明度 0.55 → 1.0（呼吸主体）
        core = QColor(self._color)
        core.setAlphaF(0.55 + 0.45 * t)
        r_core = self.width() * (0.27 + 0.06 * t)
        p.setBrush(QBrush(core))
        p.drawEllipse(QRectF(cx - r_core, cy - r_core, r_core * 2, r_core * 2))
        # ★ 2026-09-21 提高对比度：核心圆外加一圈白色描边环。
        #   便签底色是可切换的多色（含米色/浅黄/深色），纯色圆点贴在浅色底上边界会糊，
        #   加白环后无论卡片什么底色都有一道明确的轮廓，档位颜色也更容易辨。
        #   坑（实测，见 TagLabel._paint_glass 注释）：描边只能用「透明 QColor 画刷 +
        #   浮点线宽 + 显式 PenStyle」，不能用 setBrush(Qt.BrushStyle.NoBrush)，那套在本
        #   项目的 Qt 组合下会静默崩进程。
        lw = max(1.0, self.width() * 0.09)
        p.setBrush(QColor(0, 0, 0, 0))
        p.setPen(QPen(QColor(255, 255, 255, 240), lw, Qt.PenStyle.SolidLine))
        r_ring = r_core + lw * 0.75
        p.drawEllipse(QRectF(cx - r_ring, cy - r_ring, r_ring * 2, r_ring * 2))


class StickyNoteWindow(QDialog):
    """便签式任务卡片窗口（对齐参考 HTML 的 #taskCard）。

    ★ 窗口与卡片结构（2026-09-21 第三次返工后定稿，勿再回退）：
      历史上便签卡片是用 ``QGraphicsView + QGraphicsScene + QGraphicsProxyWidget``
      承载的（为了做「卡片旋转」），结果在 macOS 上稳定复现三个顽疾：
        1. **卡片变透明**：代理承载的内嵌控件，其不透明实底（#fffaf5）会被系统
           合成成半透明，壁纸直接透过来（截图实证）；
        2. **点不动**：鼠标事件要经「视图 → 场景 → 代理 → 内嵌控件」三级路由，
           Qt::Dialog + WA_TranslucentBackground 下这条链路并不可靠，按钮/输入框
           全部无响应；
        3. **拖不动**：拖拽依赖「子控件 event.ignore() 冒泡到窗口自身
           mousePressEvent」这一脆弱约定，事件在代理层就被吃掉。
      现改为与 ``TodoWindow``（任务清单主窗口，macOS 上一切正常）**完全同构**的结构：
        窗口(QDialog + Frameless + StaysOnTop + TranslucentBackground)
          └─ 根布局(0 边距) → self.note（QWidget + WA_StyledBackground + 不透明圆角底色）
               └─ 普通子控件层级：顶部栏(呼吸灯/优先级 chip/3 按钮) / 标题 / 富文本编辑器
      卡片底色由 QSS 实底绘制，不再有任何代理层 → 不透明、可点、可拖。
    - 基类取 QDialog：窗口类型为 Qt::Dialog。Qt::Window 类型的 WA_TranslucentBackground
      窗口在 App 失活时会被系统整块丢掉内容（仅剩窗口阴影一圈「边框」）。
    - 拖拽：把 ``_drag_press/_drag_move/_drag_release`` 直接接到顶部栏与卡片背景自身
      的鼠标事件上（与 TodoWindow 顶栏拖拽同源），靠 Qt 隐式抓取 + 绝对坐标跟随。
      不用 startSystemMove（子控件上下文调用会抛 NSException 硬崩）、不用 grabMouse
      （半透明无边框窗上偶发失效）。
    - 可边缘/角落缩放（ResizeGrip + macOS 原生 resizable styleMask）。
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
        # 「置顶（锁定）」状态：True = 用户点了顶部栏的置顶按钮（选定态）——不可移动、
        # 不可缩放、层级最高且不被其它页面/应用遮挡；再点一次取消（回到普通卡片行为）。
        # 这是唯一状态源：``_locked`` 是为 ResizeGrip 保留的只读属性别名（见下方 property），
        # 而 common.keep_on_top / release_topmost 与 main._keep_topmost 按这个名字识别
        # 「只抬不降」的窗口（统一的判定见 common.is_pinned_top）。
        self._pinned_top = False
        self._drag_pos = None  # 拖拽偏移（按下点 - 窗口左上角），非 None 表示正在拖动
        self._done = bool(task.get("done", False))
        self._prio = task.get("priority") or "中"   # 供左上角优先级呼吸灯取色
        self._rotate = 0
        self._bg = QColor(STICKY_DEFAULT_BG)  # 软件主题米色（默认背景，实际值下面 set_bg 读回）

        # ★ 窗口类型必须是 Qt::Dialog（见类注释）：否则 macOS 下 App 失活后
        #   WA_TranslucentBackground 内容被系统整块丢掉、便签变透明只剩边框。
        self.setWindowFlags(Qt.WindowType.Dialog
                           | Qt.WindowType.FramelessWindowHint
                           | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 最小 = 默认尺寸（用户要求只能放大）。默认 320×280 必须能**完整**看到底部那条
        # 富文本工具栏（含窄宽度换行后的第二行：高亮/清除格式）——这是 2026-09-21 用户
        # 意见附图的诉求。注意：光靠窗口高度不够，正文（QTextEdit）在紧凑模式下的最小高
        # 才是压垮布局的那一环（详见 rich_editor 里 setMinimumHeight 处的算式）：改造前
        # 竖向需求 371px > 280px → 布局溢出把工具栏裁掉，用户只有往下拉大才慢慢露出来。
        # 真实默认/最小尺寸仍以 screen_fit.WINDOW_DEFAULTS["sticky"] 为准（下方 fit_window 覆盖）。
        self.setMinimumSize(320, 280)
        self.setMaximumSize(1100, 900)

        self._build_note()
        self._build_grips()
        # MacBook Air 2020（1440×900）基准的舒适默认大小；macOS 下追加原生边缘缩放
        fit_window(self, "sticky", resizable=True, max_size=(1100, 900))
        # ★ 2026-09-21 兜底（用户意见附图：「默认尺寸下看不到富文本工具栏」）：
        #   窗口高度必须 ≥ 卡片布局的真实最小高度，否则 QVBoxLayout 无处可让，只能把
        #   底部那条**固定高度**的工具栏挤出窗口 → 换行后的第二行（高亮/清除格式）被裁。
        #   仅把正文最小高改小（rich_editor 里 s(56)）已经够用，但那套算式依赖
        #   「按钮 28px + 内宽 288px 恰好换成 9+2 两行」；一旦字体/缩放/按钮尺寸变化
        #   多换出一行，就会再次裁切。这里改为**按真实布局反算**并抬升最小高。
        #   正常情况（需求 233 < 280）本方法是空操作，只在异常时兜底。
        self._ensure_toolbar_visible()
        # 便签背景色持久化（2026-09-21 修 Bug）：读回该任务上次选的色；
        # 没设置过则用默认主题米色。persist=False —— 初始化不该写库。
        self.set_bg(task.get("bg") or STICKY_DEFAULT_BG, persist=False)
        # 打开便签时立即载入该任务的真实标题与富文本内容（修复：之前永远显示占位符）
        self.title.setText(task.get("title", "") or "")
        self.editor.set_html(task.get("content", ""))
        self.sync_state()
        # 订阅全局 done_changed：列表行 / Dock 行任一入口勾选本任务时，本便签标题
        # 删除线/颜色与确认键即刻同步（无需靠列表的 notify_sticky 特例）。UniqueConnection 防重复连。
        bus().done_changed.connect(self._on_done_changed,
                                    Qt.ConnectionType.UniqueConnection)

    # ---------- 尺寸兜底 ----------
    def _ensure_toolbar_visible(self):
        """把窗口最小高度抬到「底部富文本工具栏完整可见」所需的高度（异常时兜底）。

        背景：便签的默认尺寸与最小尺寸是**同一个值** 320×280（screen_fit.WINDOW_DEFAULTS
        经 fit_window 写成了显式最小值）。显式最小值会让 QLayout 的 SetDefaultConstraint
        失效（Qt 只在「控件没有显式最小尺寸」时才用布局最小高约束主窗口），于是布局
        可以被压到自身最小高之下 —— 被压掉的恰好是底部那条 setFixedHeight 的工具栏。

        算式（s() = ×0.8 后的实际像素）：
          卡片内宽 = 320 − 2×s(20)=16 → 288
          11 个 28px 按钮 + 4px 水平间距 → 第一行 9 个、第二行 2 个
          工具栏高 = 上 s(8)=6 + 28 + 4 + 28 + 下 s(8)=6 = 72
          整卡需求 = 上16 + 顶栏19 + 10 + 标题29 + 13 + (正文45 + 13 + 工具栏72) + 下16
                   = 233 ≤ 280 → 默认尺寸下无需改动（本方法为**空操作**）。

        构造期窗口宽度还是 0，直接量 toolbar.width() 会把每个按钮都判成单独一行而算出
        天大的高度，所以先用**设计宽度**预置工具栏高度，再按布局最小高反算。
        """
        try:
            design_w = WINDOW_DEFAULTS.get("sticky", (320, 280))[0]
            inner = max(1, design_w - 2 * s(20))     # 卡片左右内边距各 s(20)
            tb = getattr(self.editor, "toolbar", None)
            if tb is not None:
                wrapped = tb.flow.heightForWidth(inner)
                if wrapped > 0:
                    tb.setFixedHeight(wrapped)       # 预置：让布局最小高算得对
            need = self.note.layout().minimumSize().height()
            if need > self.minimumHeight():
                self.setMinimumHeight(need)
                if self.height() < need:
                    self.resize(self.width(), need)
        except Exception:
            # 纯兜底逻辑：任何异常都不该影响便签打开（宁可维持 320×280 原样）。
            pass

    # ---------- 构建 ----------
    def _build_note(self):
        # ★ 卡片本体 = 窗口根布局内的直接子控件（见类注释：不再经 QGraphicsView /
        #   QGraphicsProxyWidget）。QSS 实底 + WA_StyledBackground → 底色**完全不透明**。
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.note = QWidget()
        self.note.setObjectName("stickyNote")
        self.note.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root.addWidget(self.note)
        nl = QVBoxLayout(self.note)
        nl.setContentsMargins(s(20), s(20), s(20), s(20))   # HTML p-5 = 20px
        nl.setSpacing(s(0))

        # 顶部操作栏（同时也是拖拽手柄）
        self.bar = QWidget()
        self.bar.setFixedHeight(s(24))
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(s(0), s(0), s(0), s(0))
        bl.setSpacing(s(12))                        # HTML gap-3 = 12px
        self.btn_complete = QPushButton()
        self.btn_pin = QPushButton()
        self.btn_close = QPushButton()
        # 按钮提示语（原先三个按钮都没有 tooltip，「置顶」这种行为完全靠猜；
        # 用户这次给置顶按钮定义了明确的语义，必须有提示语说清「点=锁定/再点=取消」）。
        for b, role in ((self.btn_complete, "complete"),
                        (self.btn_pin, "pin"),
                        (self.btn_close, "close")):
            b.setObjectName("stickyBtn")
            b.setProperty("role", role)
            b.setFixedSize(s(24), s(24))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIcon(QIcon(self._btn_icon(role, False)))
            b.setIconSize(QSize(s(20), s(20)))
            # 写入 :hover 以启用 WA_Hover，使事件过滤器能切换 hover 图标配色
            b.setStyleSheet(scale_qss(
                "QPushButton{background:transparent;border:none;padding:0;}"
                "QPushButton:hover{background:rgba(0,0,0,0.06);border-radius:8px;}"))
            b.installEventFilter(self)
        self.btn_complete.setToolTip(tr("完成"))
        self.btn_close.setToolTip(tr("关闭"))
        self._refresh_pin_tip()
        # ★ 左上角优先级呼吸灯（低=绿 / 中=橙 / 高=红）：插在 stretch 之前 → 位于顶部栏
        #   最左侧；三个操作按钮仍被 addStretch 顶在右侧，其余布局零改动。
        #   圆点自身 WA_TransparentForMouseEvents，所以顶部栏整条仍可按下拖动。
        self.dot = PriorityPulseDot(self._prio, diameter=s(14))
        self.dot.setToolTip(tr("优先级") + "：" + tr(self._prio))
        bl.addWidget(self.dot)
        # ★ 2026-09-21 补「优先级文字 chip」（用户反馈「便签页面优先级区分度不高」）：
        #   便签原来只用一枚 12px 的小圆点表示优先级，低/中/高三色在浅色卡片上很难区分，
        #   不悬停看 tooltip 甚至不知道是哪一档。这里补一个同色系实底 + 白字的文字标签，
        #   「低 / 中 / 高」直接写出来，一眼可辨；高度压到 20 以内以适配 24px 的顶部栏。
        self.prio_tag = TagLabel(tr(self._prio), _PRIO_TAG_FILL.get(self._prio, TAG_BG),
                                 "#FFFFFF", radius=6)
        self.prio_tag.setFixedHeight(s(20))
        self.prio_tag.setToolTip(tr("优先级") + "：" + tr(self._prio))
        bl.addWidget(self.prio_tag)
        bl.addStretch(1)
        bl.addWidget(self.btn_complete)
        bl.addWidget(self.btn_pin)
        bl.addWidget(self.btn_close)
        nl.addWidget(self.bar)
        nl.addSpacing(s(12))                         # HTML 顶部栏 mb-3 = 12px

        # 可编辑标题（text-xl 20px / font-medium / 下划线；完成时删除线 + 变灰）
        self.title = QLineEdit()
        self.title.setObjectName("stickyTitle")
        self.title.setPlaceholderText(tr("任务标题"))
        self.title.setFixedHeight(s(36))
        nl.addWidget(self.title)
        nl.addSpacing(s(16))                         # HTML 标题 mb-4 = 16px

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
        # ★ 拖拽移动（与 TodoWindow 顶栏拖拽同源，macOS 实测可靠）：把「按下 / 移动 /
        #   释放」直接接到控件自身的鼠标事件上，靠 Qt 的隐式抓取拿到后续移动，绝对坐标
        #   跟随窗口。顶部栏空白区与卡片空白背景都能抓；标题 / 正文 / 按钮等子控件会先
        #   吃掉自己的按下事件 → 不受影响（文本照常能编辑、按钮照常能点）。
        #   注意：必须是「控件自身的 mousePressEvent」这个上下文，才能在 macOS 上安全
        #   拿到整段拖拽（曾在子控件的事件过滤器里直接调 startSystemMove → NSException
        #   硬崩；也试过 grabMouse → 半透明无边框窗上偶发捕获不到移动）。
        for _w in (self.bar, self.note):
            _w.mousePressEvent = self._drag_press
            _w.mouseMoveEvent = self._drag_move
            _w.mouseReleaseEvent = self._drag_release
        self.btn_complete.clicked.connect(self.toggle_done)
        self.btn_pin.clicked.connect(self.toggle_pin)
        self.btn_close.clicked.connect(self.close)
        self.title.editingFinished.connect(self._on_title_edited)

        # ★ 「置顶（锁定）」描边层（2026-09-21）：锁定后窗口既拖不动也缩不了，若画面毫无
        #   变化，用户会以为程序卡死。这里用一层**透明覆盖框**画 2px 主题色描边表示「已选定」。
        #   用独立子控件而不是给 self.note 加 QSS border —— 后者的边框会参与内容矩形计算，
        #   锁定/取消的瞬间整张卡片的内容会跳 2px；覆盖框不参与任何布局，零副作用。
        #   WA_TransparentForMouseEvents：纯装饰层，绝不能吃掉顶部栏/边缘握把的按下事件。
        self.lock_frame = QFrame(self.note)
        self.lock_frame.setObjectName("stickyLockFrame")
        self.lock_frame.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lock_frame.setStyleSheet(scale_qss(
            "QFrame#stickyLockFrame{background:transparent;"
            "border:2px solid #F9730F;border-radius:8px;}"))
        self.lock_frame.setGeometry(self.rect())
        self.lock_frame.setVisible(False)

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
        # 握把必须是窗口内**最上层**的子控件，否则会被铺满窗口的卡片（self.note）盖住
        # 而收不到边缘的按下事件（表现为「边缘拖不动、缩放失效」）。
        # 存成列表：resizeEvent 重排、以及「置顶（锁定）」时整体隐藏都要用。
        self._grips = [self.grip_left, self.grip_right, self.grip_bottom,
                       self.grip_bl, self.grip_br]
        for g in self._grips:
            g.raise_()

    # ---------- 显示 ----------
    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        # macOS：便签卡片同样必须免除台前调度管理（否则切 App 时便签会被收进左侧缩略图条）
        apply_stage_exempt(self, tag="StickyNoteWindow")
        # ★ 打开便签即记为「最近使用」并立刻抬到最前：从任务清单页点标题开便签时，
        #   点击事件记的是任务清单窗口（而非便签本身），若不在此补一步，下一拍 1.5s
        #   置顶定时器会按 MRU 把任务清单抬到便签之上 → 便签「闪一下就被盖住、像消失」。
        #   便签自带 WindowStaysOnTopHint，keep_on_top 不会重建原生窗口、安全。
        note_front(self, raise_now=True)

    # ---------- 拖拽：控件自身鼠标事件 + Qt 隐式抓取 + 绝对坐标跟随 ----------
    # 由 _build_note 直接挂到 self.bar / self.note 的 mousePressEvent/Move/Release 上
    # （与 TodoWindow._bar_press/_bar_move 同源）。accept() 是必须的：只有接受了按下
    # 事件，Qt 才会把后续的移动事件持续投递给同一个控件（隐式抓取）。
    def _drag_press(self, e):
        # 置顶（锁定）态禁止移动：用户对该按钮的定义是「点击则选定：不能移动…」。
        if self._pinned_top or e.button() != Qt.MouseButton.LeftButton:
            e.ignore()
            return
        self._drag_pos = e.globalPosition().toPoint() - self.pos()
        e.accept()

    def _drag_move(self, e):
        if self._drag_pos is not None and not self._pinned_top:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()
            return
        e.ignore()

    def _drag_release(self, e):
        self._drag_pos = None
        e.accept()

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
        # 便签卡片任意位置右键：弹出统一的自绘菜单（含标题、内容、工具栏；
        # 拦截 QLineEdit/QTextEdit 的原生右键菜单，保证与设计完全一致）
        if et == QEvent.Type.ContextMenu and isinstance(obj, QWidget) \
                and (obj is self.note or self.note.isAncestorOf(obj)):
            # 右键落在标题 → 编辑动作作用于标题输入框；落在内容（含 QTextEdit 的
            # viewport）→ 作用于富文本编辑器；落在卡片空白 → 默认内容编辑器。
            target = self.title if obj is self.title else self.editor.editor
            # guard_ui：事件过滤器里构造弹窗，异常必须就地拦住（PyQt6 会把逃逸到
            # 虚函数外的 Python 异常升级成 qFatal → 整个 App abort，用户实测右键闪退）
            guard_ui("便签右键菜单", self._show_sticky_menu, event, target)
            return True
        return super().eventFilter(obj, event)

    # ---------- 完成（确认键）：双向同步 ----------
    def toggle_done(self):
        cur = todo.get_task(self.task_id)
        if cur is None:
            return
        new = not cur["done"]
        todo.set_done(self.task_id, new)
        # 列表项 / Dock 行 / 本便签的标题渲染由全局 done_changed 总线就地同步
        # （见各窗口 _on_done_changed），这里只负责刷新本窗口自身 + 闹钟播报。
        self.sync_state()
        if new:
            speak_later(config.character.system_func.get("todo", {}).get("complete", "嘻嘻，任务完成捏"))

    def _on_done_changed(self, tid, done):
        """全局完成态变化：仅当变化的正是本便签对应的任务时，刷新标题删除线/颜色与确认键。"""
        if tid != self.task_id:
            return
        self.sync_state()

    def _refresh_prio_tag(self):
        """刷新便签顶部栏的「优先级文字 chip」：文案跟随语言、底色跟随档位。"""
        tag = getattr(self, "prio_tag", None)
        if tag is None:
            return
        tag.setText(tr(self._prio))
        tag.set_colors(_PRIO_TAG_FILL.get(self._prio, TAG_BG), "#FFFFFF")
        tag.setToolTip(tr("优先级") + "：" + tr(self._prio))

    def preview_priority(self, prio):
        """编辑页实时预览：仅刷新左上角呼吸灯颜色与提示语，不改动其它状态。
        定稿由 sync_state 完成——保存后按新值、返回/取消后按存储旧值回退。"""
        self._prio = prio or self._prio
        if getattr(self, "dot", None) is not None:
            self.dot.set_priority(self._prio)
            self.dot.setToolTip(tr("优先级") + "：" + tr(self._prio))
        self._refresh_prio_tag()

    def sync_state(self):
        """根据任务最新 done 状态刷新：标题删除线+颜色、确认键图标、优先级呼吸灯。"""
        cur = todo.get_task(self.task_id)
        self._done = bool(cur["done"]) if cur else False
        # 优先级可能被主窗口改过 → 呼吸灯颜色同步
        self._prio = (cur or {}).get("priority") or self._prio
        if getattr(self, "dot", None) is not None:
            self.dot.set_priority(self._prio)
            self.dot.setToolTip(tr("优先级") + "：" + tr(self._prio))
        self._refresh_prio_tag()
        f = self.title.font()
        f.setStrikeOut(self._done)
        self.title.setFont(f)
        self.title.setStyleSheet(self._title_qss(self._done))
        self.btn_complete.setIcon(QIcon(self._btn_icon("complete", False)))
        self.btn_complete.setIconSize(QSize(s(20), s(20)))

    def retranslate_ui(self):
        """语言切换：刷新便签内文案（标题占位、编辑器工具栏/占位、呼吸灯与三按钮提示）。"""
        self.title.setPlaceholderText(tr("任务标题"))
        if getattr(self, "dot", None) is not None:
            self.dot.setToolTip(tr("优先级") + "：" + tr(self._prio))
        self._refresh_prio_tag()
        # 三按钮提示语（含「置顶 / 取消置顶」的状态相关文案）跟随语言
        if getattr(self, "btn_complete", None) is not None:
            self.btn_complete.setToolTip(tr("完成"))
        if getattr(self, "btn_close", None) is not None:
            self.btn_close.setToolTip(tr("关闭"))
        self._refresh_pin_tip()
        editor = getattr(self, "editor", None)
        if editor is not None and hasattr(editor, "retranslate"):
            editor.retranslate()

    def _title_qss(self, done):
        # 与「任务清单行 / TodoDock 行 / 添加页标题输入框」共用同一套任务标题渲染：
        # 字体本体（字号/字重/颜色/完成态删除线）只在 style.task_title_qss 里定义一次，
        # 便签只通过 extra 追加自己的「结构性差异」，不重复写字体 —— 保证「一处变全跟着变」。
        # 唯一保留的差异是这条 2px 下划线：它是便签「标题可直接编辑」的唯一视觉提示，
        # 去掉后整张卡片看不出哪里能改标题（如需彻底一致，删掉 extra 即可）。
        # HTML 参考：text-xl font-medium title-underline(2px #d8d8d8) pb-1(4px)
        body = task_title_qss(
            done, extra="border-bottom:2px solid #d8d8d8;padding:0 2px 4px 2px;"
        )
        return (
            "QLineEdit#stickyTitle{background:transparent;border:none;"
            + body +
            "}QLineEdit#stickyTitle:focus{border-bottom-color:#F97316;}"
        )

    # ---------- 置顶（锁定）：不可移动 / 不可缩放 / 层级最高 ----------
    @property
    def _locked(self):
        """只读别名：``ResizeGrip`` 读 ``window._locked`` 判断是否禁止缩放。

        唯一状态源是 ``_pinned_top``（见 set_pinned）。历史上有过两个属性各写一半的写法，
        极易出现「能拖但缩不了」这类半锁定状态，故这里只暴露只读属性，不提供 setter。
        """
        return self._pinned_top

    def toggle_pin(self):
        """置顶按钮：点一下「选定」（锁定），再点一下取消选定。"""
        self.set_pinned(not self._pinned_top)

    def set_pinned(self, on):
        """设置置顶（锁定）状态 —— 对齐用户对该按钮的完整定义：

        选定（on=True）：
          1. **不能移动** —— 拖拽按下直接忽略（见 ``_drag_press``）；
          2. **不能调整窗口大小** —— 隐藏 5 个自绘边缘握把（否则边缘仍是缩放光标），
             并摘掉 macOS 原生 styleMask 的 resizable 位（只挡握把挡不住原生缩放）；
          3. **显示优先级最高且不被其它页面或应用遮挡** —— 抬到 LEVEL_PINNED
             （NSModalPanelWindowLevel，高于其它 App 的浮动窗口、低于菜单栏与弹层）：
             App 的 1.5s 置顶定时器把它排在所有卡片**之后**抬层，用户的「点击谁谁在前」
             抬层也会在抬完之后把它再压回去（见 common._raise_pinned_above），
             并且用户切到别的 App 时其它卡片整体让路而它**不降层**。
        取消选定（on=False）：以上全部回退，恢复成普通卡片 —— 参与 MRU「点击谁谁在前」，
        并随其它卡片一起在用户切到别的 App 时让路（不妨碍用户使用其它页面或应用）。

        幂等；状态只有一个来源 ``_pinned_top``，任何入口（按钮 / 探针 / 将来加的右键菜单项）
        都必须走这里。
        """
        on = bool(on)
        self._pinned_top = on
        self.btn_pin.setIcon(QIcon(self._btn_icon("pin", False)))
        self.btn_pin.setIconSize(QSize(s(20), s(20)))
        self._refresh_pin_tip()
        # 边缘握把：锁定时隐藏（保留几何，取消时原样显示回来）
        for g in getattr(self, "_grips", []):
            try:
                g.setVisible(not on)
            except RuntimeError:
                continue
        # macOS 原生边缘缩放：锁定摘位 / 取消补位（与 fit_window(..., resizable=True) 对齐）
        set_resizable(self, not on, tag="sticky-pin")
        # 层级：置顶 → 抬到 LEVEL_PINNED 并压到最前；取消 → 回落浮层。
        # keep_on_top 内部按 _pinned_top 自动选层，这里无需传参。
        keep_on_top(self, bring_to_front=on)
        # 视觉反馈：锁定态显示 2px 主题色描边
        lock_frame = getattr(self, "lock_frame", None)
        if lock_frame is not None:
            if on:
                lock_frame.setGeometry(self.rect())
                lock_frame.raise_()
                lock_frame.show()
            else:
                lock_frame.hide()

    def _refresh_pin_tip(self):
        """置顶按钮提示语跟随状态（未锁定=「置顶」，已锁定=「取消置顶」）。"""
        btn = getattr(self, "btn_pin", None)
        if btn is None:
            return
        btn.setToolTip(tr("取消置顶") if self._pinned_top else tr("置顶"))

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
    def set_bg(self, color, persist=True):
        """设置便签背景色并（默认）持久化，修复「关闭再打开又变回默认色」。

        - ``color`` 为空/非法时回退默认主题色。
        - ``persist=False`` 只用于 __init__ 里的「读回上次颜色」——避免刚打开便签
          就无谓地写一次 todos.json；用户主动选色（右键色板）走默认 persist=True。
        """
        self._bg = QColor(color or STICKY_DEFAULT_BG)
        if not self._bg.isValid():
            self._bg = QColor(STICKY_DEFAULT_BG)
        # HTML rounded-lg = 8px
        self.note.setStyleSheet(scale_qss(
            f"QWidget#stickyNote{{background:{self._bg.name()};border-radius:8px;}}"))
        if persist:
            todo.set_bg(self.task_id, self._bg.name())

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
        new_task = todo.add(title, content_html, remind=None, alarm_id=None, priority="中",
                            bg=self._bg.name())      # 复制任务沿用当前背景色
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

    # ---------- 几何（窗口缩放时重新摆放边缘握把） ----------
    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        # 卡片（self.note）由窗口根布局自动铺满，无需手动同步尺寸 —— 这里只需把
        # 手工定位的 5 个边缘握把跟着窗口重排，并重申它们在最上层（不被卡片盖住）。
        m = 7
        self.grip_left.setGeometry(0, 0, m, self.height())
        self.grip_right.setGeometry(self.width() - m, 0, m, self.height())
        self.grip_bottom.setGeometry(m, self.height() - m, self.width() - 2 * m, m)
        self.grip_bl.setGeometry(0, self.height() - m, m, m)
        self.grip_br.setGeometry(self.width() - m, self.height() - m, m, m)
        for g in self._grips:
            # 不在此处 setVisible(True)：置顶锁定期间握把必须是隐藏的（见 set_pinned），
            # raise_() 对隐藏控件无副作用，安全。
            g.raise_()
        # 「置顶（锁定）」描边层跟随窗口尺寸（锁定期间才可见）
        lock_frame = getattr(self, "lock_frame", None)
        if lock_frame is not None:
            lock_frame.setGeometry(self.rect())
            if self._pinned_top:
                lock_frame.raise_()

    # ---------- 关闭：回写内容并解除注册（注意：关闭便签≠删除任务） ----------
    def closeEvent(self, e):  # noqa: N802
        todo.set_note(self.task_id, self.title.text().strip() or tr("未命名"),
                      self.editor.to_html())
        self.todo_window.unregister_sticky(self.task_id)
        self.todo_window._render()
        super().closeEvent(e)
