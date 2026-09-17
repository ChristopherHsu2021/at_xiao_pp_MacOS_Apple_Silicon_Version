"""闹钟窗口：列表（时间/重复/铃声/开关）+ 添加（时间、重复、铃声模糊搜索、自定义语音）。"""

import os

from PyQt6.QtCore import QDate, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor, QIcon, QIntValidator, QPainter, QPen, QPixmap, QPolygonF,
)
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QGraphicsDropShadowEffect,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from app.core import alarm as alarm_mod, assets, config
from app.core.i18n import tr
from app.core.voice import say
from app.ui.common import PeekCard, NoticeDialog
from app.ui.context_menu import ActionPopupMenu


def _alarm_menu_icon(kind):
    """绘制同尺寸的菜单图标，避免不同字体字形造成错位。"""
    pixmap = QPixmap(22, 22)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#6b5744"), 1.8, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if kind == "edit":
        body = QPolygonF([
            QPointF(5.0, 16.7), QPointF(6.0, 12.9),
            QPointF(14.8, 4.1), QPointF(18.0, 7.3),
            QPointF(9.2, 16.1), QPointF(5.0, 16.7),
        ])
        painter.drawPolygon(body)
        painter.drawLine(QPointF(13.4, 5.5), QPointF(16.6, 8.7))
        painter.drawLine(QPointF(5.0, 16.7), QPointF(4.2, 18.8))
        painter.drawLine(QPointF(4.2, 18.8), QPointF(6.4, 18.0))
    else:
        painter.drawRoundedRect(6, 7, 10, 12, 1.8, 1.8)
        painter.drawLine(QPointF(4.5, 6.0), QPointF(17.5, 6.0))
        painter.drawLine(QPointF(8.5, 3.8), QPointF(13.5, 3.8))
        painter.drawLine(QPointF(9.0, 9.5), QPointF(9.0, 16.5))
        painter.drawLine(QPointF(13.0, 9.5), QPointF(13.0, 16.5))
    painter.end()
    return QIcon(pixmap)


ALARM_QSS = """
QWidget#alarmCard {
    background: #fffaf5;
    border: 1px solid rgba(255,255,255,0.60);
    border-radius: 20px;
}
QWidget#alarmPage,
QWidget#alarmBody,
QWidget#alarmListWidget,
QWidget#alarmDays {
    background: transparent;
    border-radius: 20px;
}
QStackedWidget {
    background: transparent;
    border: none;
}
QWidget#windowBar {
    background: #fffaf5;
    border-bottom: 1px solid rgba(249,117,16,0.12);
    border-top-left-radius: 20px;
    border-top-right-radius: 20px;
}
QLabel#windowTitle {
    color: #3d2b1f;
    font-size: 15px;
    font-weight: 700;
}
QPushButton#primaryBtn {
    background: #ff7613;
    border: 1.5px solid #ff7613;
    border-radius: 16px;
    color: #fff;
    font-size: 12px;
    font-weight: 700;
    padding: 0 14px;
}
QPushButton#primaryBtn:hover { background: #ffa940; border-color: #ffa940; }
QPushButton#secondaryBtn {
    background: transparent;
    border: 1.5px solid rgba(249,117,16,0.16);
    border-radius: 16px;
    color: #6b5744;
    font-size: 12px;
    font-weight: 600;
    padding: 0 10px;
}
QPushButton#secondaryBtn:hover {
    background: rgba(249,117,16,0.08);
    color: #f97510;
}
QScrollArea { border: none; background: transparent; border-bottom-left-radius: 20px; border-bottom-right-radius: 20px; }
QScrollArea > QWidget > QWidget { background: transparent; border-bottom-left-radius: 20px; border-bottom-right-radius: 20px; }
QScrollBar:vertical { width: 4px; background: transparent; margin: 6px 0; }
QScrollBar::handle:vertical { background: rgba(160,142,122,0.35); border-radius: 2px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QLabel#alarmTime {
    color: #3d2b1f;
    font-family: "Cascadia Code", Consolas, monospace;
    font-size: 26px;
    font-weight: 800;
}
QLabel#alarmRepeat { color: #6b5744; font-size: 12px; font-weight: 500; }
QLabel#alarmRing { color: #a08e7a; font-size: 11px; font-weight: 500; }
QWidget#alarmRow { background: #fffaf5; border-radius: 8px; }
QWidget#alarmRow:hover { background: rgba(249,117,16,0.10); }
QLabel#fieldLabel {
    color: #6b5744;
    font-size: 12px;
    font-weight: 600;
}
QLineEdit#timeNum {
    background: #fff8f0;
    border: 1.5px solid rgba(249,117,16,0.12);
    border-radius: 8px;
    color: #3d2b1f;
    font-family: "Cascadia Code", Consolas, monospace;
    font-size: 24px;
    font-weight: 800;
    selection-background-color: rgba(249,117,16,0.20);
}
QLineEdit#timeNum:focus { background: #fff; border-color: #f97510; }
QLabel#timeColon { color: #a08e7a; font-size: 22px; font-weight: 800; }
QLineEdit#fieldInput, QComboBox#fieldInput, QDateEdit#fieldInput {
    background: #fff8f0;
    border: 1.5px solid rgba(249,117,16,0.12);
    border-radius: 8px;
    color: #3d2b1f;
    font-size: 13px;
    padding: 0 12px;
}
QLineEdit#fieldInput:focus, QComboBox#fieldInput:focus, QDateEdit#fieldInput:focus {
    background: #fff;
    border-color: #f97510;
}
QLineEdit#fieldInput::placeholder { color: rgba(160,142,122,0.35); }
QComboBox#fieldInput::drop-down { width: 30px; border: none; background: transparent; }
QComboBox#fieldInput::down-arrow { image: none; }
QComboBox QAbstractItemView {
    background: #fffaf5;
    border: 1px solid rgba(249,117,16,0.18);
    color: #3d2b1f;
    selection-background-color: rgba(249,117,16,0.10);
    selection-color: #f97510;
    outline: 0;
}
QDateEdit#fieldInput::drop-down { width: 30px; border: none; background: transparent; }
QDateEdit#fieldInput::down-arrow { image: none; }
QListWidget#ringList {
    background: #fffaf5;
    border: none;
    outline: 0;
    color: #3d2b1f;
    font-size: 12px;
    font-weight: 500;
}
QListWidget#ringList::item {
    height: 38px;
    border-radius: 8px;
    padding-left: 12px;
}
QListWidget#ringList::item:hover { background: rgba(249,117,16,0.10); }
QListWidget#ringList::item:selected {
    background: rgba(249,117,16,0.10);
    color: #f97510;
    font-weight: 700;
}
QCheckBox#dayCheck {
    color: #6b5744;
    font-size: 12px;
    spacing: 4px;
}
QCheckBox#dayCheck::indicator {
    width: 14px;
    height: 14px;
    border: 2px solid rgba(160,142,122,0.35);
    border-radius: 5px;
    background: transparent;
}
QCheckBox#dayCheck::indicator:checked { background: #f97510; border-color: #f97510; }
"""


class Switch(QPushButton):
    def __init__(self, on=True):
        super().__init__()
        self._on = bool(on)
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QPushButton{background:transparent;border:none;padding:0;margin:0;}")

    def is_on(self):
        return self._on

    def set_on(self, value):
        self._on = bool(value)
        self.update()

    def paintEvent(self, e):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#f97510") if self._on else QColor(232, 225, 218))
        painter.drawRoundedRect(QRectF(self.rect()), 12, 12)
        knob_x = self.width() - 21 if self._on else 3
        knob = QRectF(knob_x, 3, 18, 18)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(knob)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._on = not self._on
            self.update()
        super().mouseReleaseEvent(e)


class AlarmRow(QWidget):
    def __init__(self, alarm, on_changed, on_edit, on_delete):
        super().__init__()
        self.alarm = alarm
        self.on_changed = on_changed
        self.on_edit = on_edit
        self.on_delete = on_delete
        self.setObjectName("alarmRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 12, 8, 12)
        lay.setSpacing(12)

        time = QLabel(f"{int(alarm['hour']):02d}:{int(alarm['minute']):02d}")
        time.setObjectName("alarmTime")
        time.setFixedWidth(78)
        time.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(time)

        info_w = QWidget()
        info_w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        info = QVBoxLayout(info_w)
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(2)
        rep = QLabel(self._repeat_text())
        rep.setObjectName("alarmRepeat")
        ring = QLabel(self._ring_text())
        ring.setObjectName("alarmRing")
        info.addWidget(rep)
        info.addWidget(ring)
        lay.addWidget(info_w, 1)

        sw = Switch(alarm.get("enabled", True))
        sw.clicked.connect(lambda: self._toggle(sw))
        sw.contextMenuEvent = self._show_context_menu
        lay.addWidget(sw)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.on_edit(self.alarm)
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e):  # noqa: N802
        self._show_context_menu(e)

    def _show_context_menu(self, e):
        alarm = dict(self.alarm)
        edit_callback = self.on_edit
        delete_callback = self.on_delete
        e.accept()
        self._context_menu = ActionPopupMenu(self.window(), [
            (tr("编辑"), lambda a=alarm, cb=edit_callback: cb(a)),
            (tr("删除"), lambda a=alarm, cb=delete_callback: cb(a)),
        ]).show_at(e.globalPos())

    def _repeat_text(self):
        rep = self.alarm.get("repeat", "daily")
        if rep == "daily":
            return tr("每天")
        if rep == "weekdays":
            return tr("工作日（周一至周五）")
        if rep == "custom":
            names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            picked = [tr(names[i]) for i in self.alarm.get("custom_days", []) if 0 <= i < 7]
            return f"{tr('自定义')} · {'、'.join(picked)}" if picked else tr("自定义")
        once = self.alarm.get("once_date") or ""
        return f"{tr('仅一次')} · {once.replace('-', '/')}" if once else tr("仅一次")

    def _ring_text(self):
        source_mark = f"（{tr('来自任务')}）" if self.alarm.get("source") == "todo" else ""
        if self.alarm.get("ringtone"):
            return f"🔔 {self.alarm.get('ringtone')} {source_mark}".strip()
        if self.alarm.get("custom_text"):
            return f"🗣️ \"{self.alarm['custom_text']}\" {source_mark}".strip()
        return f"🗣️ \"{tr('时间到了')}\" {source_mark}".strip()

    def _toggle(self, sw):
        alarm_mod.update(self.alarm["id"], enabled=sw.is_on())
        self.on_changed()


class AlarmWindow(QDialog):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._drag_pos = None
        self._selected_ring = None
        self._editing_alarm = None
        self._field_labels = []
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._list_size = (380, 460)
        self._add_size = (340, 640)
        self.setFixedSize(*self._list_size)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.card = PeekCard(self, scale=1.12)
        self.card.setObjectName("alarmCard")
        self.card.setStyleSheet(ALARM_QSS)
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(180, 120, 50, 32))
        self.card.setGraphicsEffect(shadow)
        root.addWidget(self.card)

        card_lay = QVBoxLayout(self.card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.setSpacing(0)
        self.stack = QStackedWidget()
        card_lay.addWidget(self.stack)
        self._build_list_page()
        self._build_add_page()

    def _bar(self, title, show_add=False):
        bar = QWidget()
        bar.setObjectName("windowBar")
        bar.setFixedHeight(58)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 0, 18, 0)
        title_l = QLabel(title)
        title_l.setObjectName("windowTitle")
        if show_add:
            self._list_title = title_l
        else:
            self._form_title = title_l
        lay.addWidget(title_l)
        lay.addStretch(1)
        if show_add:
            self._list_add_btn = QPushButton("+ " + tr("添加"))
            self._list_add_btn.setObjectName("primaryBtn")
            self._list_add_btn.setFixedSize(72, 32)
            self._list_add_btn.clicked.connect(self._show_add)
            lay.addWidget(self._list_add_btn)
            self._list_back_btn = QPushButton(tr("返回"))
            self._list_back_btn.setObjectName("secondaryBtn")
            self._list_back_btn.setFixedSize(58, 32)
            self._list_back_btn.clicked.connect(self.close)
            lay.addWidget(self._list_back_btn)
        bar.mousePressEvent = self._bar_press
        bar.mouseMoveEvent = self._bar_move
        return bar

    def _build_list_page(self):
        page = QWidget()
        page.setObjectName("alarmPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._bar("⏰️ " + tr("闹钟"), True))

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self.list_w = QWidget()
        self.list_w.setObjectName("alarmListWidget")
        self.list_w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.list_lay = QVBoxLayout(self.list_w)
        self.list_lay.setContentsMargins(10, 8, 10, 12)
        self.list_lay.setSpacing(0)
        self.scroll.setWidget(self.list_w)
        root.addWidget(self.scroll, 1)
        self.stack.addWidget(page)
        self._render()

    def _build_add_page(self):
        page = QWidget()
        page.setObjectName("alarmPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._bar(tr("添加闹钟"), False))

        body = QWidget()
        body.setObjectName("alarmBody")
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(18, 18, 18, 8)
        body_l.setSpacing(0)

        time_row = QHBoxLayout()
        time_row.setSpacing(8)
        self.h_in = self._time_input("07", 23)
        self.m_in = self._time_input("00", 59)
        colon = QLabel(":")
        colon.setObjectName("timeColon")
        colon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        colon.setFixedWidth(16)
        time_row.addWidget(self.h_in)
        time_row.addWidget(colon)
        time_row.addWidget(self.m_in)
        time_row.addStretch(1)
        body_l.addLayout(time_row)
        body_l.addSpacing(16)

        body_l.addWidget(self._field_label("重复"))
        body_l.addSpacing(6)
        self.repeat_combo = QComboBox()
        self.repeat_combo.setObjectName("fieldInput")
        for value in (tr("仅一次"), tr("每天"), tr("工作日（周一至周五）"), tr("自定义")):
            self.repeat_combo.addItem(value)
        self.repeat_combo.setCurrentIndex(1)
        self.repeat_combo.setFixedHeight(46)
        self.repeat_combo.currentIndexChanged.connect(self._on_repeat)
        body_l.addWidget(self.repeat_combo)

        self.repeat_extra = QStackedWidget()
        self.repeat_extra.setFixedHeight(46)

        empty_once_space = QWidget()
        empty_once_space.setObjectName("alarmBody")

        once_page = QWidget()
        once_page.setObjectName("alarmBody")
        once_l = QVBoxLayout(once_page)
        once_l.setContentsMargins(0, 0, 0, 0)
        self.once_date = QDateEdit(QDate.currentDate())
        self.once_date.setObjectName("fieldInput")
        self.once_date.setDisplayFormat("yyyy/MM/dd")
        self.once_date.setCalendarPopup(True)
        self.once_date.setFixedHeight(46)
        once_l.addWidget(self.once_date)

        empty_weekday_space = QWidget()
        empty_weekday_space.setObjectName("alarmBody")

        self.days_w = QWidget()
        self.days_w.setObjectName("alarmDays")
        self.days_w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        days_l = QHBoxLayout(self.days_w)
        days_l.setContentsMargins(0, 0, 0, 0)
        days_l.setSpacing(6)
        self.day_btns = []
        for label in ["一", "二", "三", "四", "五", "六", "日"]:
            cb = QCheckBox(label)
            cb.setObjectName("dayCheck")
            self.day_btns.append(cb)
            days_l.addWidget(cb)
        self.repeat_extra.addWidget(empty_once_space)
        self.repeat_extra.addWidget(once_page)
        self.repeat_extra.addWidget(empty_weekday_space)
        self.repeat_extra.addWidget(self.days_w)
        body_l.addSpacing(8)
        body_l.addWidget(self.repeat_extra)
        body_l.addSpacing(16)

        body_l.addWidget(self._field_label("铃声"))
        body_l.addSpacing(6)
        self.ring_search = QLineEdit()
        self.ring_search.setObjectName("fieldInput")
        self.ring_search.setPlaceholderText(tr("搜索歌曲..."))
        self.ring_search.setFixedHeight(46)
        self.ring_search.textChanged.connect(self._filter_ring)
        body_l.addWidget(self.ring_search)
        body_l.addSpacing(10)

        self.ring_list = QListWidget()
        self.ring_list.setObjectName("ringList")
        self.ring_list.setFixedHeight(108)
        self.ring_list.itemClicked.connect(self._pick_ring)
        body_l.addWidget(self.ring_list)
        body_l.addSpacing(16)

        body_l.addWidget(self._field_label("自定义语音播报（选填）"))
        body_l.addSpacing(6)
        self.custom_text = QLineEdit()
        self.custom_text.setObjectName("fieldInput")
        self.custom_text.setPlaceholderText(tr('例如："该起床啦"'))
        self.custom_text.setFixedHeight(46)
        body_l.addWidget(self.custom_text)
        body_l.addStretch(1)
        body_l.addSpacing(12)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        self.delete_b = QPushButton(tr("删除"))
        self.cancel_b = QPushButton(tr("取消"))
        self.save_b = QPushButton(tr("保存"))
        self.delete_b.setObjectName("secondaryBtn")
        self.cancel_b.setObjectName("secondaryBtn")
        self.save_b.setObjectName("primaryBtn")
        self.delete_b.setFixedSize(64, 34)
        self.cancel_b.setFixedSize(64, 34)
        self.save_b.setFixedSize(64, 34)
        self.delete_b.clicked.connect(self._delete_editing)
        self.cancel_b.clicked.connect(self._show_list)
        self.save_b.clicked.connect(self._save)
        self.delete_b.hide()
        footer.addWidget(self.delete_b)
        footer.addWidget(self.cancel_b)
        footer.addWidget(self.save_b)
        body_l.addLayout(footer)
        root.addWidget(body, 1)
        self.stack.addWidget(page)
        self._filter_ring("")

    def _field_label(self, text):
        label = QLabel(tr(text))
        label.setObjectName("fieldLabel")
        self._field_labels.append((label, text))
        return label

    def retranslate_ui(self):
        self._list_title.setText("⏰️ " + tr("闹钟"))
        self._list_add_btn.setText("+ " + tr("添加"))
        self._list_back_btn.setText(tr("返回"))
        self._form_title.setText(tr("编辑闹钟") if self._editing_alarm else tr("添加闹钟"))
        for label, source in self._field_labels:
            label.setText(tr(source))
        idx = self.repeat_combo.currentIndex()
        self.repeat_combo.blockSignals(True)
        self.repeat_combo.clear()
        for value in (tr("仅一次"), tr("每天"), tr("工作日（周一至周五）"), tr("自定义")):
            self.repeat_combo.addItem(value)
        self.repeat_combo.setCurrentIndex(idx)
        self.repeat_combo.blockSignals(False)
        for button, source in zip(self.day_btns, ["一", "二", "三", "四", "五", "六", "日"]):
            button.setText(tr(source))
        self.ring_search.setPlaceholderText(tr("搜索歌曲..."))
        self.custom_text.setPlaceholderText(tr('例如："该起床啦"'))
        self.delete_b.setText(tr("删除"))
        self.cancel_b.setText(tr("取消"))
        self.save_b.setText(tr("保存"))
        self._render()

    def _time_input(self, value, maximum):
        edit = QLineEdit(value)
        edit.setObjectName("timeNum")
        edit.setFixedSize(68, 58)
        edit.setMaxLength(2)
        edit.setValidator(QIntValidator(0, maximum, edit))
        edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edit.editingFinished.connect(lambda e=edit, mx=maximum: self._normalize_time(e, mx))
        return edit

    def _normalize_time(self, edit, maximum):
        value = max(0, min(maximum, int(edit.text() or "0")))
        edit.setText(f"{value:02d}")

    def _on_repeat(self, idx):
        page_map = {0: 1, 1: 0, 2: 2, 3: 3}
        self.repeat_extra.setCurrentIndex(page_map.get(idx, 0))

    def _filter_ring(self, text):
        self.ring_list.clear()
        query = text.lower()
        none_item = QListWidgetItem()
        none_item.setData(Qt.ItemDataRole.UserRole, "")
        self.ring_list.addItem(none_item)
        for path in assets.list_music_files():
            name = os.path.splitext(os.path.basename(path))[0]
            if query in name.lower():
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.ring_list.addItem(item)
        self._refresh_ring_marks()

    def _pick_ring(self, item):
        self._selected_ring = item.data(Qt.ItemDataRole.UserRole) or None
        self._refresh_ring_marks()

    def _refresh_ring_marks(self):
        for i in range(self.ring_list.count()):
            item = self.ring_list.item(i)
            name = item.data(Qt.ItemDataRole.UserRole) or None
            label = name or tr("不选择歌曲")
            item.setText(("◉  " if name == self._selected_ring else "○  ") + label)

    def _render(self):
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        alarms = alarm_mod.load()
        if not alarms:
            empty = QLabel(tr("暂无闹钟，点『添加』设置捏～"))
            empty.setStyleSheet("color:#a08e7a;font-size:13px;padding:20px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list_lay.addWidget(empty)
        for alarm in alarms:
            self.list_lay.addWidget(
                AlarmRow(alarm, self._on_alarm_changed, self._show_edit,
                         self._delete_alarm)
            )
        self.list_lay.addStretch(1)

    def _on_alarm_changed(self):
        self._render()
        self.ctx.refresh_todo()

    def _delete_alarm(self, alarm):
        alarm_mod.delete(alarm["id"])
        self._on_alarm_changed()

    def refresh_external(self):
        self._render()

    def _show_add(self):
        self._editing_alarm = None
        self._form_title.setText(tr("添加闹钟"))
        self.delete_b.hide()
        self._reset_form()
        self.setFixedSize(*self._add_size)
        self.stack.setCurrentIndex(1)

    def _show_edit(self, alarm):
        self._editing_alarm = dict(alarm)
        self._populate_form(self._editing_alarm)
        self._form_title.setText(tr("编辑闹钟"))
        self.delete_b.show()
        self.setFixedSize(*self._add_size)
        self.stack.setCurrentIndex(1)

    def _show_list(self):
        self._editing_alarm = None
        if hasattr(self, "delete_b"):
            self.delete_b.hide()
        self.setFixedSize(*self._list_size)
        self.stack.setCurrentIndex(0)

    def _reset_form(self):
        self.h_in.setText("07")
        self.m_in.setText("00")
        self.repeat_combo.setCurrentIndex(1)
        self.once_date.setDate(QDate.currentDate())
        for btn in self.day_btns:
            btn.setChecked(False)
        self._selected_ring = None
        self.ring_search.clear()
        self.custom_text.clear()

    def _populate_form(self, alarm):
        self.h_in.setText(f"{int(alarm.get('hour', 7)):02d}")
        self.m_in.setText(f"{int(alarm.get('minute', 0)):02d}")
        rep_map = {"once": 0, "daily": 1, "weekdays": 2, "custom": 3}
        self.repeat_combo.setCurrentIndex(rep_map.get(alarm.get("repeat"), 1))
        if alarm.get("once_date"):
            date = QDate.fromString(alarm["once_date"], "yyyy-MM-dd")
            if date.isValid():
                self.once_date.setDate(date)
        picked_days = set(alarm.get("custom_days", []))
        for i, btn in enumerate(self.day_btns):
            btn.setChecked(i in picked_days)
        self._selected_ring = alarm.get("ringtone")
        self.ring_search.clear()
        if self._selected_ring is None:
            self._selected_ring = None
            self.ring_list.clearSelection()
            self.ring_list.setCurrentItem(None)
        self.custom_text.setText(alarm.get("custom_text") or "")

    def _delete_editing(self):
        if not self._editing_alarm:
            return
        alarm_mod.delete(self._editing_alarm["id"])
        self._editing_alarm = None
        self._render()
        self.ctx.refresh_todo()
        self._show_list()

    def _save(self):
        self._normalize_time(self.h_in, 23)
        self._normalize_time(self.m_in, 59)
        rep_map = {0: "once", 1: "daily", 2: "weekdays", 3: "custom"}
        rep = rep_map[self.repeat_combo.currentIndex()]
        selected = self.ring_list.currentItem()
        ringtone = selected.data(Qt.ItemDataRole.UserRole) if selected and selected.isSelected() else self._selected_ring
        ringtone = ringtone or None
        custom_text = self.custom_text.text().strip()
        if ringtone:
            custom_text = ""
        elif not custom_text:
            custom_text = "时间到了"
        kwargs = {
            "hour": int(self.h_in.text() or "0"),
            "minute": int(self.m_in.text() or "0"),
            "repeat": rep,
            "ringtone": ringtone,
            "custom_text": custom_text or None,
            "once_date": None,
            "custom_days": [],
        }
        if rep == "once":
            kwargs["once_date"] = self.once_date.date().toString("yyyy-MM-dd")
        if rep == "custom":
            kwargs["custom_days"] = [i for i, btn in enumerate(self.day_btns) if btn.isChecked()]
        ok, reason = alarm_mod.validate_schedule(kwargs)
        if not ok:
            NoticeDialog(self, tr("提醒时间过近"), tr(reason)).exec()
            return
        if self._editing_alarm:
            alarm_mod.update(self._editing_alarm["id"], **kwargs)
        else:
            alarm_mod.add(**kwargs)
        self.custom_text.clear()
        self._render()
        self._show_list()
        self.ctx.refresh_todo()
        say(config.character.system_func.get("alarm", {}).get("addSuccess", "好嘟，闹钟设置完成捏"))

    def _bar_press(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.pos()

    def _bar_move(self, e):
        if self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
            if self.stack.currentIndex() == 1:
                self._show_list()
            else:
                self.close()
            return
        super().keyPressEvent(e)
