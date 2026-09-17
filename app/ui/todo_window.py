"""待办清单窗口：全选 / 添加 / 删除 / 勾选划线，本地持久化，每周一清理。"""

from PyQt6.QtWidgets import (
    QDialog, QWidget, QLabel, QPushButton, QLineEdit, QDateTimeEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QCheckBox, QCalendarWidget,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import Qt, QDateTime, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush

from app.core import todo, config
from app.core import alarm as alarm_mod
from app.core.voice import say
from app.core.i18n import tr
from app.ui.common import PeekCard, NoticeDialog
from app.ui.context_menu import ActionPopupMenu


WINDOW_QSS = """
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
    font-size: 15px;
    font-weight: 700;
    color: #3d2b1f;
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
QCheckBox#remindCheck {
    color: #6b5744;
    font-size: 12px;
    font-weight: 600;
    spacing: 8px;
}
QCheckBox#remindCheck::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid rgba(160,142,122,0.30);
    border-radius: 6px;
    background: transparent;
}
QCheckBox#remindCheck::indicator:checked {
    background: #ff7613;
    border-color: #ff7613;
}
QScrollArea { border: none; background: transparent; border-bottom-left-radius: 20px; border-bottom-right-radius: 20px; }
QScrollBar:vertical { width: 4px; background: transparent; margin: 6px 0; }
QScrollBar::handle:vertical { background: rgba(160,142,122,0.35); border-radius: 2px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


CHECK_QSS = """
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
"""

LABEL_QSS = "font-size:13px;color:#3d2b1f;font-weight:500;"
DONE_LABEL_QSS = "font-size:13px;color:#a08e7a;font-weight:500;text-decoration:line-through;"
TIME_QSS = "font-size:11px;color:#a08e7a;font-family:Consolas,'Cascadia Code',monospace;font-weight:600;"

CALENDAR_QSS = """
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
"""


def speak_later(text):
    QTimer.singleShot(80, lambda: say(text))


class TodoCheckBox(QPushButton):
    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(22, 22)
        self.setStyleSheet("QPushButton{background:transparent;border:none;padding:0;margin:0;}")

    def paintEvent(self, e):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#ff7613")))
            painter.drawRoundedRect(rect, 6, 6)
        else:
            pen = QPen(QColor(160, 142, 122, 76), 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 6, 6)
            return
        pen = QPen(QColor("#ffffff"), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(6, 11, 9, 15)
        painter.drawLine(9, 15, 16, 6)


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


class TaskRow(QWidget):
    def __init__(self, task, on_toggle, on_edit, on_delete, on_interact=None):
        super().__init__()
        self.task = task
        self.on_toggle = on_toggle
        self.on_edit = on_edit
        self.on_delete = on_delete
        self.on_interact = on_interact
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(10)
        self.check = TodoCheckBox()
        self.check.setChecked(task["done"])
        self.check.toggled.connect(self._toggled)
        self.check.contextMenuEvent = self._show_context_menu
        self.text = QLabel(task["content"])
        self.text.setStyleSheet(LABEL_QSS)
        self.text.setCursor(Qt.CursorShape.PointingHandCursor)
        self.text.mousePressEvent = lambda e: self._edit(e)
        self.text.contextMenuEvent = self._show_context_menu
        remind = task.get("remind") if task.get("remind_enabled", True) else None
        self.time = QLabel(self._format_remind(remind))
        self.time.setStyleSheet(TIME_QSS)
        self.time.setMinimumWidth(86)
        self.time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.time.contextMenuEvent = self._show_context_menu
        lay.addWidget(self.check)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.time)
        self._apply()

    def _format_remind(self, value):
        if not value:
            return ""
        dt = QDateTime.fromString(value, "yyyy-MM-dd HH:mm")
        return dt.toString("MM/dd HH:mm") if dt.isValid() else value

    def _toggled(self, checked):
        if self.on_interact:
            self.on_interact()
        self.task["done"] = checked
        todo.toggle(self.task["id"])
        self._apply()
        if checked:
            speak_later(config.character.system_func.get("todo", {}).get("complete", "嘻嘻，任务完成捏"))
        self.on_toggle()

    def _edit(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.task.get("done"):
            if self.on_interact:
                self.on_interact()
            self.on_edit(self.task)

    def contextMenuEvent(self, event):  # noqa: N802
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
        else:
            self.text.setStyleSheet(LABEL_QSS)


class TodoWindow(QDialog):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._drag_pos = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._list_size = (480, 296)
        self._add_size = (320, 278)
        self.editing_task = None
        self.setFixedSize(*self._list_size)
        self._build()

    def _build(self):
        frame_root = QVBoxLayout(self)
        frame_root.setContentsMargins(0, 0, 0, 0)
        frame_root.setSpacing(0)

        self.container = PeekCard(self, scale=1.08)
        self.container.setObjectName("GlassWindow")
        self.container.setStyleSheet(WINDOW_QSS)
        shadow = QGraphicsDropShadowEffect(self.container)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(180, 120, 50, 32))
        self.container.setGraphicsEffect(shadow)
        frame_root.addWidget(self.container)

        outer = QVBoxLayout(self.container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = QWidget()
        self.header.setObjectName("window-bar")
        self.header.setFixedHeight(58)
        header_lay = QHBoxLayout(self.header)
        header_lay.setContentsMargins(18, 0, 18, 0)
        header_lay.setSpacing(6)
        self.title_label = QLabel("📋 " + tr("任务清单"))
        self.title_label.setObjectName("window-title")
        header_lay.addWidget(self.title_label)
        header_lay.addStretch(1)
        self.sel_all = QPushButton(tr("全选"))
        self.add_b = QPushButton("+ " + tr("添加"))
        self.del_b = QPushButton(tr("删除"))
        self.back_b = QPushButton(tr("返回"))
        self.sel_all.setObjectName("todoSecondary")
        self.add_b.setObjectName("todoPrimary")
        self.del_b.setObjectName("todoDanger")
        self.back_b.setObjectName("todoSecondary")
        for b in (self.sel_all, self.add_b, self.del_b, self.back_b):
            b.setFixedHeight(32)
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
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

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
        self.list_lay.setContentsMargins(12, 8, 12, 12)
        self.list_lay.setSpacing(0)
        self.scroll.setWidget(self.list_widget)
        root.addWidget(self.scroll, 1)

        # 添加面板
        self.add_panel = QWidget()
        self.add_panel.setObjectName("add-panel")
        self.add_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.add_panel.setVisible(False)
        ap = QVBoxLayout(self.add_panel)
        ap.setContentsMargins(18, 18, 18, 18)
        ap.setSpacing(8)
        self.content_in = QLineEdit()
        self.content_in.setPlaceholderText(tr("输入任务内容..."))
        self.content_in.setFixedHeight(40)
        self.content_in.setFixedWidth(284)
        self.remind_chk = QCheckBox(tr("提醒时间"))
        self.remind_chk.setObjectName("remindCheck")
        self.remind_in = CalendarDateTimeEdit(QDateTime.currentDateTime())
        self.remind_in.setDisplayFormat("yyyy/MM/dd HH:mm")
        self.remind_in.setCalendarPopup(True)
        calendar = QCalendarWidget(self.remind_in)
        calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        calendar.setStyleSheet(CALENDAR_QSS)
        self.remind_in.setCalendarWidget(calendar)
        self.remind_in.setFixedHeight(40)
        self.remind_in.setFixedWidth(284)
        self.remind_in.setEnabled(False)
        self.remind_chk.toggled.connect(self._on_remind_toggled)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 8, 0, 0)
        footer.setSpacing(8)
        footer.addStretch(True)
        self.cancel_b = QPushButton(tr("取消"))
        self.save_b = QPushButton(tr("保存"))
        self.cancel_b.setObjectName("todoSecondary")
        self.save_b.setObjectName("todoPrimary")
        self.cancel_b.setFixedHeight(32)
        self.save_b.setFixedHeight(32)
        self.cancel_b.clicked.connect(self._hide_editor)
        self.save_b.clicked.connect(self._save)
        footer.addWidget(self.cancel_b)
        footer.addWidget(self.save_b)
        self.content_label = QLabel(tr("任务内容"))
        self.content_label.setStyleSheet("font-size:12px;color:#6b5744;font-weight:600;")
        ap.addWidget(self.content_label)
        ap.addWidget(self.content_in)
        ap.addSpacing(6)
        ap.addWidget(self.remind_chk)
        ap.addWidget(self.remind_in)
        ap.addStretch(1)
        ap.addLayout(footer)
        root.addWidget(self.add_panel)

        self._render()

    def set_title(self, title: str):
        self.title_label.setText(title)

    def _apply_header_button_widths(self):
        is_en = config.settings.get("language") == "en"
        self.sel_all.setFixedWidth(86 if is_en else 78)
        self.add_b.setFixedWidth(84 if is_en else 78)
        self.del_b.setFixedWidth(82 if is_en else 72)
        self.back_b.setFixedWidth(68 if is_en else 62)

    def _bar_press(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.pos()

    def _bar_move(self, e):
        if self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
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
            empty.setStyleSheet("color:#a08e7a;font-size:16px;padding:20px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list_lay.addWidget(empty)
        for t in tasks:
            self.list_lay.addWidget(
                TaskRow(t, self._after_task_toggle, self._edit_task,
                        self._delete_task, self.ctx.stop_alarm)
            )
        self.list_lay.addStretch(1)

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

    def _show_editor(self, task=None):
        self.editing_task = task
        show_add = True
        if task:
            self._populate_editor(task)
        else:
            self.content_in.clear()
            self.remind_chk.setChecked(False)
            self.remind_in.setDateTime(QDateTime.currentDateTime())
        self.add_panel.setVisible(show_add)
        self.scroll.setVisible(not show_add)
        self.sel_all.setVisible(not show_add)
        self.add_b.setVisible(not show_add)
        self.del_b.setVisible(not show_add)
        self.back_b.setVisible(not show_add)
        self.set_title(tr("编辑任务") if task else tr("添加任务"))
        self.setFixedSize(*(self._add_size if show_add else self._list_size))
        self.content_in.setFocus()

    def _populate_editor(self, task):
        self.content_in.setText(task.get("content", ""))
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
        self.editing_task = None
        self.content_in.clear()
        self.remind_chk.setChecked(False)
        self.add_panel.setVisible(False)
        self.scroll.setVisible(True)
        self.sel_all.setVisible(True)
        self.add_b.setVisible(True)
        self.del_b.setVisible(True)
        self.back_b.setVisible(True)
        self.set_title("📋 " + tr("任务清单"))
        self.setFixedSize(*self._list_size)

    def retranslate_ui(self):
        if self.add_panel.isVisible():
            self.set_title(tr("编辑任务") if self.editing_task else tr("添加任务"))
        else:
            self.set_title("📋 " + tr("任务清单"))
        self.sel_all.setText(tr("全选"))
        self.add_b.setText("+ " + tr("添加"))
        self.del_b.setText(tr("删除"))
        self.back_b.setText(tr("返回"))
        self._apply_header_button_widths()
        self.content_label.setText(tr("任务内容"))
        self.content_in.setPlaceholderText(tr("输入任务内容..."))
        self.remind_chk.setText(tr("提醒时间"))
        self.cancel_b.setText(tr("取消"))
        self.save_b.setText(tr("保存"))
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
        content = self.content_in.text().strip()
        if not content:
            return
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
            content, remind, old_alarm_id, enabled=remind_enabled
        )
        if self.editing_task:
            todo.update_task(
                self.editing_task["id"], content, remind,
                alarm_id=alarm_id, remind_enabled=remind_enabled,
            )
        else:
            todo.add(content, remind, alarm_id=alarm_id)
        self._hide_editor()
        self._render()
        self.ctx.refresh_alarm()
        speak_later(config.character.system_func.get("todo", {}).get("addSuccess", "好嘟，任务保存好捏"))

    def _delete(self):
        removed = todo.delete_done()
        self._render()
        self.ctx.refresh_alarm()
        if removed:
            speak_later(config.character.system_func.get("todo", {}).get("delete", "这条任务已经删掉捏"))
