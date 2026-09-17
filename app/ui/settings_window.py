"""设置窗口：开机自启 / 语言 / 音量 / 画面大小 / 工作时间 / 版权；返回或保存。"""

import os

from PyQt6.QtCore import QObject, QRectF, Qt, QThread, QTime, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QDialog, QWidget, QLabel, QPushButton, QSlider, QHBoxLayout, QVBoxLayout,
    QTimeEdit, QGraphicsDropShadowEffect, QStackedWidget, QTextEdit,
    QLineEdit,
)

from app.core import admin_auth, config, pathutil, voice_media
from app.core.voice import say
from app.core.i18n import tr
from app.ui.common import PeekCard


LANGS = [("简体中文", "zh-CN"), ("繁體中文", "zh-TW"), ("English", "en")]


SETTINGS_QSS = """
QWidget#settingsCard {
    background: #fffaf5;
    border: 1px solid rgba(255,255,255,0.60);
    border-radius: 20px;
}
QWidget#windowBar {
    background: transparent;
    border-bottom: 1px solid rgba(249,117,16,0.12);
    border-top-left-radius: 20px;
    border-top-right-radius: 20px;
}
QWidget#settingsBody,
QWidget#settingsFooter,
QWidget#settingRow,
QWidget#workTimeBox {
    background: transparent;
}
QWidget#langTabs {
    background: rgba(249,117,16,0.06);
}
QWidget#settingsFooter {
    border-top: 1px solid rgba(249,117,16,0.12);
    border-bottom-left-radius: 20px;
    border-bottom-right-radius: 20px;
}
QWidget#copyrightBand {
    background: transparent;
    border-top: 1px solid rgba(249,117,16,0.12);
}
QLabel#windowTitle {
    color: #3d2b1f;
    font-size: 15px;
    font-weight: 700;
}
QLabel#settingName {
    color: #3d2b1f;
    font-size: 13px;
    font-weight: 700;
}
QLabel#settingDesc,
QLabel#workLabel,
QLabel#workSep {
    color: #a08e7a;
    font-size: 12px;
    font-weight: 500;
}
QLabel#copyright {
    color: rgba(160,142,122,0.35);
    font-size: 11px;
    font-weight: 700;
}
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
QPushButton#langTab {
    background: transparent;
    border: none;
    border-radius: 16px;
    color: #a08e7a;
    font-size: 12px;
    font-weight: 700;
    padding: 0 18px;
}
QPushButton#langTab:checked {
    background: #f97510;
    color: #fff;
}
QPushButton#langTab:hover:!checked {
    color: #6b5744;
    background: rgba(249,117,16,0.06);
}
QSlider::groove:horizontal {
    height: 6px;
    background: rgba(249,117,16,0.12);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 18px;
    height: 18px;
    margin: -7px 0;
    background: #f97510;
    border: 3px solid #fff;
    border-radius: 9px;
}
QTimeEdit#workInput {
    background: rgba(249,117,16,0.04);
    border: 1.5px solid rgba(249,117,16,0.12);
    border-radius: 6px;
    color: #3d2b1f;
    font-family: "Cascadia Code", Consolas, monospace;
    font-size: 12px;
    font-weight: 700;
    padding: 0 8px;
}
QTimeEdit#workInput:focus {
    background: #fff;
    border-color: #f97510;
}
QTimeEdit#workInput::up-button,
QTimeEdit#workInput::down-button {
    width: 0;
    height: 0;
    border: none;
}
QTextEdit#voiceText {
    background: rgba(255,255,255,0.72);
    border: 1.5px solid rgba(249,117,16,0.18);
    border-radius: 12px;
    color: #3d2b1f;
    font-size: 13px;
    font-weight: 600;
    padding: 10px;
}
QTextEdit#voiceText:focus { background: #fff; border-color: #f97510; }
QLabel#adminHint,
QLabel#timeLabel {
    color: #a08e7a;
    font-size: 12px;
    font-weight: 600;
}
QLabel#adminTitle {
    color: #3d2b1f;
    font-size: 15px;
    font-weight: 800;
}
QLabel#dialogTitle {
    color: #3d2b1f;
    font-size: 14px;
    font-weight: 800;
}
QLabel#dialogText {
    color: #8d7a68;
    font-size: 12px;
    font-weight: 600;
}
QLineEdit#adminPassword {
    background: rgba(249,117,16,0.04);
    border: 1.5px solid rgba(249,117,16,0.16);
    border-radius: 10px;
    color: #3d2b1f;
    font-size: 13px;
    font-weight: 700;
    padding: 0 10px;
    selection-background-color: rgba(249,117,16,0.20);
}
QLineEdit#adminPassword:focus {
    background: #fff;
    border-color: #f97510;
}
QWidget#dialogCard {
    background: #fffaf5;
    border: 1px solid rgba(255,255,255,0.70);
    border-radius: 18px;
}
"""


class VoiceGenerateWorker(QObject):
    finished = pyqtSignal(bool, str, str)

    def __init__(self, text: str, output_wav: str):
        super().__init__()
        self.text = text
        self.output_wav = output_wav

    @pyqtSlot()
    def run(self):
        try:
            voice_media.generate_to_file(self.text, self.output_wav)
            self.finished.emit(True, self.output_wav, "")
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(False, "", str(exc))


class StyledMessageDialog(QDialog):
    def __init__(self, parent, title: str, message: str):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedSize(292, 168)
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        card = QWidget(self)
        card.setObjectName("dialogCard")
        card.setStyleSheet(SETTINGS_QSS)
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 7)
        shadow.setColor(QColor(180, 120, 50, 32))
        card.setGraphicsEffect(shadow)
        root.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        title_l = QLabel(tr(title))
        title_l.setObjectName("dialogTitle")
        title_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_l = QLabel(tr(message))
        text_l.setObjectName("dialogText")
        text_l.setWordWrap(True)
        text_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title_l)
        lay.addWidget(text_l, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        ok_b = QPushButton(tr("确定"))
        ok_b.setObjectName("primaryBtn")
        ok_b.setFixedSize(70, 32)
        ok_b.clicked.connect(self.accept)
        row.addWidget(ok_b)
        row.addStretch(1)
        lay.addLayout(row)


class AdminPasswordDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedSize(322, 198)
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        card = QWidget(self)
        card.setObjectName("dialogCard")
        card.setStyleSheet(SETTINGS_QSS)
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 7)
        shadow.setColor(QColor(180, 120, 50, 32))
        card.setGraphicsEffect(shadow)
        root.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        title = QLabel(tr("权限验证"))
        title.setObjectName("dialogTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip = QLabel(tr("请输入系统管理员密码"))
        tip.setObjectName("dialogText")
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.password = QLineEdit()
        self.password.setObjectName("adminPassword")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setFixedHeight(36)
        self.password.returnPressed.connect(self.accept)
        lay.addWidget(title)
        lay.addWidget(tip)
        lay.addWidget(self.password)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        cancel_b = QPushButton(tr("取消"))
        ok_b = QPushButton(tr("确定"))
        cancel_b.setObjectName("secondaryBtn")
        ok_b.setObjectName("primaryBtn")
        cancel_b.setFixedSize(64, 32)
        ok_b.setFixedSize(64, 32)
        cancel_b.clicked.connect(self.reject)
        ok_b.clicked.connect(self.accept)
        row.addWidget(cancel_b)
        row.addWidget(ok_b)
        lay.addLayout(row)

    def value(self) -> str:
        return self.password.text()


class Switch(QPushButton):
    def __init__(self, on=True):
        super().__init__()
        self._on = bool(on)
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QPushButton{background:transparent;border:none;padding:0;margin:0;}")
        self.clicked.connect(self._toggle)

    def _toggle(self):
        self._on = not self._on
        self.update()

    def is_on(self):
        return self._on

    def paintEvent(self, e):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#f97510") if self._on else QColor(232, 225, 218))
        painter.drawRoundedRect(QRectF(self.rect()), 12, 12)
        knob_x = self.width() - 21 if self._on else 3
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(knob_x, 3, 18, 18))


class SettingsWindow(QDialog):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._drag_pos = None
        self.lang = config.settings.get("language", "zh-CN")
        self._row_texts = []
        self._preview_wav = ""
        self._voice_thread = None
        self._voice_worker = None
        self._in_admin_voice = False
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(480, 560)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.audio.setVolume(config.settings.get("volume", 50) / 100)
        self.player.positionChanged.connect(self._preview_position_changed)
        self.player.durationChanged.connect(self._preview_duration_changed)
        self.player.playbackStateChanged.connect(self._preview_state_changed)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.card = PeekCard(self, scale=1.16)
        self.card.setObjectName("settingsCard")
        self.card.setStyleSheet(SETTINGS_QSS)
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root.addWidget(self.card)

        card_lay = QVBoxLayout(self.card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.setSpacing(0)
        card_lay.addWidget(self._bar())

        self.stack = QStackedWidget()
        self.stack.setObjectName("settingsBody")
        body = QWidget()
        body.setObjectName("settingsBody")
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(0, 8, 0, 10)
        body_l.setSpacing(0)

        self.autostart = Switch(config.settings.get("autostart", True))
        body_l.addWidget(self._row("开机自启动", "系统启动时自动运行 AT小PP", self.autostart))

        body_l.addWidget(self._row("语言", "界面显示与语音播报语言", self._lang_tabs()))

        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(config.settings.get("volume", 50))
        self.vol.setFixedWidth(150)
        body_l.addWidget(self._row("音量大小", "语音播报与音乐音量", self.vol))

        self.size = QSlider(Qt.Orientation.Horizontal)
        self.size.setRange(50, 150)
        self.size.setValue(config.settings.get("sizeScale", 100))
        self.size.setFixedWidth(150)
        body_l.addWidget(self._row("画面大小", "桌面角色的显示尺寸", self.size))

        body_l.addWidget(self._row("工作时间", "该时段默认显示工作状态", self._work_time_controls()))
        self.stack.addWidget(body)
        self.stack.addWidget(self._admin_voice_page())
        card_lay.addWidget(self.stack, 1)

        self.copyright_band = self._copyright()
        self.settings_footer = self._footer()
        card_lay.addWidget(self.copyright_band)
        card_lay.addWidget(self.settings_footer)
        self._set_settings_footer()

    def _bar(self):
        bar = QWidget()
        bar.setObjectName("windowBar")
        bar.setFixedHeight(58)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 0, 18, 0)
        self.title_label = QLabel("⚙️ " + tr("设置"))
        self.title_label.setObjectName("windowTitle")
        lay.addWidget(self.title_label)
        lay.addStretch(1)
        bar.mousePressEvent = self._bar_press
        bar.mouseMoveEvent = self._bar_move
        return bar

    def _row(self, name, desc, control):
        row = QWidget()
        row.setObjectName("settingRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(16)
        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(2)
        name_l = QLabel(tr(name))
        name_l.setObjectName("settingName")
        desc_l = QLabel(tr(desc))
        desc_l.setObjectName("settingDesc")
        self._row_texts.append((name_l, name, desc_l, desc))
        info.addWidget(name_l)
        info.addWidget(desc_l)
        lay.addLayout(info, 1)
        lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        return row

    def _lang_tabs(self):
        wrap = QWidget()
        wrap.setObjectName("langTabs")
        wrap.setStyleSheet(
            "QWidget#langTabs{background:rgba(249,117,16,0.06);border-radius:20px;}"
        )
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(4)
        self.lang_btns = []
        for label, code in LANGS:
            btn = QPushButton(label)
            btn.setObjectName("langTab")
            btn.setCheckable(True)
            btn.setFixedHeight(34)
            btn.setChecked(code == self.lang)
            btn.clicked.connect(lambda _=False, c=code: self._pick_lang(c))
            self.lang_btns.append(btn)
            lay.addWidget(btn)
        return wrap

    def _work_time_controls(self):
        wt = config.settings.get("workTime", {})
        wrap = QWidget()
        wrap.setObjectName("workTimeBox")
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.work_labels = []
        self.m_am_s = self._time_edit(wt.get("morning", ["09:00", "12:00"])[0])
        self.m_am_e = self._time_edit(wt.get("morning", ["09:00", "12:00"])[1])
        self.m_pm_s = self._time_edit(wt.get("afternoon", ["13:30", "18:00"])[0])
        self.m_pm_e = self._time_edit(wt.get("afternoon", ["13:30", "18:00"])[1])
        lay.addLayout(self._work_row("上午", self.m_am_s, self.m_am_e))
        lay.addLayout(self._work_row("下午", self.m_pm_s, self.m_pm_e))
        return wrap

    def _work_row(self, label, start, end):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        lab = QLabel(tr(label))
        lab.setObjectName("workLabel")
        lab.setFixedWidth(32)
        self.work_labels.append((lab, label))
        sep = QLabel("-")
        sep.setObjectName("workSep")
        row.addWidget(lab)
        row.addWidget(start)
        row.addWidget(sep)
        row.addWidget(end)
        return row

    def _time_edit(self, value):
        edit = QTimeEdit(self._qtime(value))
        edit.setObjectName("workInput")
        edit.setDisplayFormat("HH:mm")
        edit.setFixedSize(76, 32)
        edit.setButtonSymbols(QTimeEdit.ButtonSymbols.NoButtons)
        return edit

    def _copyright(self):
        band = QWidget()
        band.setObjectName("copyrightBand")
        band.setFixedHeight(60)
        lay = QHBoxLayout(band)
        lay.setContentsMargins(18, 0, 18, 0)
        text = QLabel(config.character.copyright or "Copyright © 2026 Christopher Hsu. All rights reserved.")
        text.setObjectName("copyright")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        band.setCursor(Qt.CursorShape.PointingHandCursor)
        band.mousePressEvent = self._try_open_admin_voice
        lay.addWidget(text)
        return band

    def _admin_voice_page(self):
        page = QWidget()
        page.setObjectName("settingsBody")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(0)

        self.admin_title = QLabel(tr("音频生成"))
        self.admin_title.setObjectName("adminTitle")
        lay.addWidget(self.admin_title)
        lay.addSpacing(8)

        self.admin_desc = QLabel(tr("生成的音频可试听，保存后写入本地附加语音库"))
        self.admin_desc.setObjectName("adminHint")
        self.admin_desc.setWordWrap(True)
        lay.addWidget(self.admin_desc)
        lay.addSpacing(15)

        self.voice_text = QTextEdit()
        self.voice_text.setObjectName("voiceText")
        self.voice_text.setPlaceholderText(tr("输入要生成的播报内容"))
        self.voice_text.setFixedHeight(122)
        lay.addWidget(self.voice_text)
        lay.addSpacing(14)

        self.generate_btn = QPushButton(tr("生成"))
        self.generate_btn.setObjectName("primaryBtn")
        self.generate_btn.setFixedHeight(36)
        self.generate_btn.clicked.connect(self._generate_preview_voice)
        lay.addWidget(self.generate_btn)
        lay.addSpacing(14)

        player_row = QHBoxLayout()
        player_row.setContentsMargins(0, 0, 0, 0)
        player_row.setSpacing(8)
        self.play_btn = QPushButton("▶")
        self.play_btn.setObjectName("secondaryBtn")
        self.play_btn.setFixedSize(44, 32)
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._toggle_preview)
        self.preview_slider = QSlider(Qt.Orientation.Horizontal)
        self.preview_slider.setRange(0, 0)
        self.preview_slider.setEnabled(False)
        self.preview_slider.sliderMoved.connect(self.player.setPosition)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("timeLabel")
        self.time_label.setFixedWidth(92)
        player_row.addWidget(self.play_btn)
        player_row.addWidget(self.preview_slider, 1)
        player_row.addWidget(self.time_label)
        lay.addLayout(player_row)
        lay.addStretch(1)
        return page

    def _footer(self):
        footer = QWidget()
        footer.setObjectName("settingsFooter")
        footer.setFixedHeight(58)
        lay = QHBoxLayout(footer)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(8)
        lay.addStretch(1)
        self.back_btn = QPushButton(tr("返回"))
        self.save_btn = QPushButton(tr("保存"))
        self.back_btn.setObjectName("secondaryBtn")
        self.save_btn.setObjectName("primaryBtn")
        self.back_btn.setFixedSize(64, 32)
        self.save_btn.setFixedSize(64, 32)
        lay.addWidget(self.back_btn)
        lay.addWidget(self.save_btn)
        return footer

    def _connect_button(self, button, slot):
        try:
            button.clicked.disconnect()
        except TypeError:
            pass
        button.clicked.connect(slot)

    def _set_settings_footer(self):
        self.back_btn.setText(tr("返回"))
        self.save_btn.setText(tr("保存"))
        self.save_btn.setEnabled(True)
        self._connect_button(self.back_btn, self.close)
        self._connect_button(self.save_btn, self._save)

    def _set_admin_footer(self):
        self.back_btn.setText(tr("返回"))
        self.save_btn.setText(tr("保存"))
        self.save_btn.setEnabled(bool(self._preview_wav and os.path.exists(self._preview_wav)))
        self._connect_button(self.back_btn, self._leave_admin_voice)
        self._connect_button(self.save_btn, self._save_preview_voice)

    def _qtime(self, hhmm):
        h, m = (hhmm.split(":") + ["0", "0"])[:2]
        return QTime(int(h), int(m))

    def _pick_lang(self, code):
        self.lang = code
        for btn, (_, lang_code) in zip(self.lang_btns, LANGS):
            btn.setChecked(lang_code == code)

    def _save(self):
        config.settings.set("autostart", self.autostart.is_on(), save=False)
        config.settings.set("language", self.lang, save=False)
        config.settings.set("volume", self.vol.value(), save=False)
        self.audio.setVolume(self.vol.value() / 100)
        config.settings.set("sizeScale", self.size.value(), save=False)
        config.settings.set("workTime", {
            "morning": [self.m_am_s.time().toString("HH:mm"), self.m_am_e.time().toString("HH:mm")],
            "afternoon": [self.m_pm_s.time().toString("HH:mm"), self.m_pm_e.time().toString("HH:mm")],
        }, save=True)
        if self.ctx:
            self.ctx.apply_settings()
        self.retranslate_ui()
        say(config.character.system_func.get("setting", {}).get("save", "好嘟，设置已经保存捏"))

    def _try_open_admin_voice(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        dialog = AdminPasswordDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if not admin_auth.verify_admin_password(dialog.value()):
            self._show_message("权限不足", "用户暂无权限进入此页面")
            return
        self._in_admin_voice = True
        self.stack.setCurrentIndex(1)
        self.copyright_band.hide()
        self.settings_footer.show()
        self._set_admin_footer()
        self.title_label.setText("⚙️ " + tr("音频生成"))

    def _leave_admin_voice(self):
        self._clear_admin_voice()
        self._in_admin_voice = False
        self.player.setSource(QUrl())
        self.stack.setCurrentIndex(0)
        self.copyright_band.show()
        self.settings_footer.show()
        self.retranslate_ui()
        self._set_settings_footer()
        self.card.update()
        self.update()

    def _clear_admin_voice(self):
        self.player.stop()
        self._preview_wav = ""
        self.voice_text.clear()
        self.play_btn.setEnabled(False)
        if self._in_admin_voice:
            self.save_btn.setEnabled(False)
        self.preview_slider.setEnabled(False)
        self.preview_slider.setRange(0, 0)
        self.time_label.setText("00:00 / 00:00")

    def _generate_preview_voice(self):
        text = self.voice_text.toPlainText().strip()
        if not text:
            self._show_message("无法生成", "内容不能为空")
            return
        self.player.stop()
        out = pathutil.data_file("tts", "admin_voice_preview.wav")
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText(tr("生成中"))
        self.save_btn.setEnabled(False)
        self._voice_thread = QThread(self)
        self._voice_worker = VoiceGenerateWorker(text, out)
        self._voice_worker.moveToThread(self._voice_thread)
        self._voice_thread.started.connect(self._voice_worker.run)
        self._voice_worker.finished.connect(self._voice_generated)
        self._voice_worker.finished.connect(self._voice_thread.quit)
        self._voice_worker.finished.connect(self._voice_worker.deleteLater)
        self._voice_thread.finished.connect(self._voice_thread.deleteLater)
        self._voice_thread.start()

    def _voice_generated(self, ok: bool, path: str, error: str):
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText(tr("生成"))
        self._voice_thread = None
        self._voice_worker = None
        if not ok:
            self._show_message("生成失败", error or tr("生成失败"))
            return
        self._preview_wav = path
        self.player.setSource(QUrl.fromLocalFile(path))
        self.play_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.preview_slider.setEnabled(True)

    def _toggle_preview(self):
        if not self._preview_wav or not os.path.exists(self._preview_wav):
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _save_preview_voice(self):
        text = self.voice_text.toPlainText().strip()
        try:
            dest = voice_media.save_additional(self._preview_wav, text)
            self._show_message("保存完成", f"{tr('已保存到')}：\n{dest}")
        except Exception as exc:  # noqa: BLE001
            self._show_message("保存失败", str(exc))

    def _show_message(self, title: str, message: str):
        StyledMessageDialog(self, title, message).exec()

    def _preview_position_changed(self, pos: int):
        if not self.preview_slider.isSliderDown():
            self.preview_slider.setValue(pos)
        self._update_time_label()

    def _preview_duration_changed(self, dur: int):
        self.preview_slider.setRange(0, max(0, dur))
        self._update_time_label()

    def _preview_state_changed(self, state):
        self.play_btn.setText("Ⅱ" if state == QMediaPlayer.PlaybackState.PlayingState else "▶")

    def _update_time_label(self):
        self.time_label.setText(f"{self._fmt_ms(self.player.position())} / {self._fmt_ms(self.player.duration())}")

    @staticmethod
    def _fmt_ms(value: int) -> str:
        seconds = max(0, int(value // 1000))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def retranslate_ui(self):
        self.title_label.setText("⚙️ " + tr("设置"))
        for name_l, name, desc_l, desc in self._row_texts:
            name_l.setText(tr(name))
            desc_l.setText(tr(desc))
        for label, source in getattr(self, "work_labels", []):
            label.setText(tr(source))
        self.back_btn.setText(tr("返回"))
        self.save_btn.setText(tr("保存"))
        # 同步语言按钮 checked 状态，确保设置窗与托盘/配置一致
        current = config.settings.get("language", "zh-CN")
        self.lang = current
        for btn, (_, lang_code) in zip(getattr(self, "lang_btns", []), LANGS):
            btn.setChecked(lang_code == current)
        if hasattr(self, "admin_title"):
            self.admin_title.setText(tr("音频生成"))
            self.admin_desc.setText(tr("生成的音频可试听，保存后写入本地附加语音库"))
            self.voice_text.setPlaceholderText(tr("输入要生成的播报内容"))

    def _bar_press(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.pos()

    def _bar_move(self, e):
        if self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
            if self._in_admin_voice:
                self._leave_admin_voice()
            else:
                self.close()
            return
        super().keyPressEvent(e)
