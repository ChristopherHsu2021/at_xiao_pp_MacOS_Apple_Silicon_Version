"""系统托盘：隐身恢复入口、设置、退出，以及闹钟/提醒的气泡通知。

当「居家 / 听歌」音乐播放器窗口开启时，右键菜单顶部会出现与卜卜音悦一致
的播放控制条（进度条 + 时间 + 上一首/播放暂停/下一首 + 显示/语言/退出）；
播放器关闭或处于「工作 / 歌手」等隐藏式播放时，该控制条不显示。
"""

import os

from PyQt6.QtWidgets import (
    QSystemTrayIcon, QMenu, QWidgetAction, QStyle, QApplication,
    QWidget, QLabel, QHBoxLayout, QVBoxLayout, QToolButton,
)
from PyQt6.QtGui import QIcon, QPixmap, QImage, QAction, QActionGroup
from PyQt6.QtCore import Qt

from app.core import config, assets
from app.core.i18n import tr
from app.ui.common import keep_on_top
from app.ui.music_player import SlimSlider


def _make_icon() -> QIcon:
    p = assets.find_image("桌面图标")
    if p and os.path.exists(p):
        pix = QPixmap(p).scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        return QIcon(pix)
    img = QImage(32, 32, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    return QIcon(QPixmap.fromImage(img))


class TrayManager(QSystemTrayIcon):
    def __init__(self, ctx, parent=None):
        super().__init__(_make_icon(), parent)
        self.ctx = ctx
        self.setToolTip(config.character.app_name)
        self._build_menu()
        self.setContextMenu(self.menu)
        self.activated.connect(self._on_activate)

    # ---------------- 菜单构建 ----------------
    def _build_menu(self):
        menu = QMenu()
        menu.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        menu.aboutToShow.connect(lambda m=menu: keep_on_top(m, bring_to_front=True))
        menu.setStyleSheet(
            "QMenu{background:#fff;border:1px solid rgba(249,117,16,0.3);border-radius:10px;padding:6px;}"
            "QMenu::item{padding:7px 18px 7px 10px;border-radius:8px;color:#3d2b1f;font-size:13px;}"
            "QMenu::item:selected{background:rgba(249,117,16,0.14);color:#f97510;}"
            "QLabel#trayTime{color:#7f6b58;font-size:11px;}"
            "QLabel#trayDur{color:#a08e7a;font-size:11px;}"
            "QToolButton{border:0;padding:4px;min-width:28px;min-height:26px;}"
            "QToolButton:hover{background:rgba(249,117,16,0.14);border-radius:4px;}"
        )
        self.menu = menu

        # ---- 音乐播放控制条相关项（仅播放器窗口未关闭时动态插入） ----
        self._build_music_controls()

        # ---- 应用级菜单项（常驻，顺序：待办/计时/闹钟/语言/设置/退出） ----
        self.todo_a = QAction("📋 " + tr("待办"), menu)
        self.todo_a.triggered.connect(lambda: self.ctx.open_todo())

        self.timer_a = QAction("⏱️ " + tr("计时"), menu)
        self.timer_a.triggered.connect(lambda: self.ctx.open_timer())

        self.alarm_a = QAction("⏰️ " + tr("闹钟"), menu)
        self.alarm_a.triggered.connect(lambda: self.ctx.open_alarm())

        # 语言子菜单：标题按当前语言显示为“🌐 汉/漢”或“🌐 Eng.”
        self.language_menu = QMenu(self._lang_menu_title(), menu)
        self.language_group = QActionGroup(self.language_menu)
        self.language_group.setExclusive(True)
        self.language_actions = {}
        for code, label in (("zh-CN", "简体中文"), ("zh-TW", "繁體中文"), ("en", "English")):
            action = QAction(label, self.language_menu)
            action.setCheckable(True)
            action.setChecked(config.settings.get("language", "zh-CN") == code)
            action.triggered.connect(lambda _checked=False, value=code: self.set_language(value))
            self.language_group.addAction(action)
            self.language_menu.addAction(action)
            self.language_actions[code] = action

        self.set_a = QAction("⚙️ " + tr("设置"), menu)
        self.set_a.triggered.connect(lambda: self.ctx.open_settings())

        # 托盘里只有一个“退出”= 退出整个软件；播放器的 X 按钮才是“退出播放器”
        self.quit_app_action = QAction("🚪 " + tr("退出"), menu)
        self.quit_app_action.triggered.connect(lambda: self.ctx.quit_app())

        # 应用菜单常驻顺序
        menu.addAction(self.todo_a)
        menu.addAction(self.timer_a)
        menu.addAction(self.alarm_a)
        menu.addAction(self.language_menu.menuAction())
        menu.addAction(self.set_a)
        menu.addAction(self.quit_app_action)

        # 初始隐藏音乐控制条（播放器未开启，动态插入未发生）
        self.set_music_visible(False)

    def _build_music_controls(self):
        """构建音乐控制条 action，但不加入菜单；由 set_music_visible 动态插入/移除。"""
        menu = self.menu
        music = self.ctx.music

        # 进度条 + 时间 + 播放控制（内嵌控件）
        controls = QWidget()
        outer = QVBoxLayout(controls)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(6)
        self.progress = SlimSlider("#f97510")
        self.progress.setRange(0, 1000)
        self.progress.setFixedHeight(16)
        self.progress.clicked.connect(self._seek_progress)
        self.progress.sliderReleased.connect(self._seek_progress)
        outer.addWidget(self.progress)

        time_row = QHBoxLayout()
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.setSpacing(6)
        self.cur_label = QLabel("00:00")
        self.cur_label.setObjectName("trayTime")
        self.dur_label = QLabel("00:00")
        self.dur_label.setObjectName("trayDur")
        time_row.addWidget(self.cur_label)
        time_row.addStretch(1)
        time_row.addWidget(self.dur_label)
        outer.addLayout(time_row)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addStretch(1)
        self.prev_button = self._button(QStyle.StandardPixmap.SP_MediaSeekBackward,
                                        tr("上一首"), music.prev)
        self.play_button = self._button(QStyle.StandardPixmap.SP_MediaPlay,
                                        tr("播放/暂停"), music.toggle_play)
        self.next_button = self._button(QStyle.StandardPixmap.SP_MediaSeekForward,
                                        tr("下一首"), music.next)
        row.addWidget(self.prev_button)
        row.addWidget(self.play_button)
        row.addWidget(self.next_button)
        row.addStretch(1)
        outer.addLayout(row)

        self.music_widget_action = QWidgetAction(menu)
        self.music_widget_action.setDefaultWidget(controls)

        # 控制条下方的分隔线
        self.player_sep = QAction(menu)
        self.player_sep.setSeparator(True)

        # 控制条区域与应用菜单之间的分隔线
        self.player_bottom_sep = QAction(menu)
        self.player_bottom_sep.setSeparator(True)

        # 连接播放器信号，实时同步进度与按钮状态
        music.player.positionChanged.connect(self.update_progress)
        music.player.durationChanged.connect(self.update_progress)
        music.player.playbackStateChanged.connect(self.update_play_button)

        self.update_progress()
        self.update_play_button()

    def _lang_menu_title(self):
        lang = config.settings.get("language", "zh-CN")
        if lang == "zh-TW":
            return "🌐 漢"
        if lang == "zh-CN":
            return "🌐 汉"
        return "🌐 Eng."

    def _button(self, standard_icon, tooltip, callback):
        button = QToolButton()
        button.setIcon(QApplication.instance().style().standardIcon(standard_icon))
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        return button

    # ---------------- 播放器可见性 ----------------
    def set_music_visible(self, visible: bool):
        """播放器窗口未关闭时把控制条插入菜单顶部；关闭后彻底移除，防止 QWidgetAction 残留渲染。"""
        current_actions = self.menu.actions()
        is_inserted = self.music_widget_action in current_actions

        if visible and not is_inserted:
            # 顺序：控制条 → 分隔线 → 应用菜单分隔线 → 待办
            self.menu.insertAction(self.todo_a, self.player_bottom_sep)
            self.menu.insertAction(self.player_bottom_sep, self.player_sep)
            self.menu.insertAction(self.player_sep, self.music_widget_action)
            self.update_progress()
            self.update_play_button()
        elif not visible and is_inserted:
            self.menu.removeAction(self.music_widget_action)
            self.menu.removeAction(self.player_sep)
            self.menu.removeAction(self.player_bottom_sep)

    # ---------------- 控制条交互 ----------------
    def show_player(self):
        music = self.ctx.music
        if music.window is None:
            music.ensure_window()
        w = music.window
        if w is None:
            return
        w.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        w.showNormal()
        w.raise_()
        w.activateWindow()
        w.sync()

    def set_language(self, language):
        if language not in self.language_actions:
            return
        config.settings.set("language", language, save=True)
        self.language_actions[language].setChecked(True)
        self.language_menu.setTitle(self._lang_menu_title())
        # AT小PP 通过 apply_settings 统一重翻所有界面与语音引擎
        self.ctx.apply_settings()

    def update_progress(self, *args):
        duration = max(0, int(self.ctx.music.player.duration()))
        position = max(0, int(self.ctx.music.player.position()))
        self.progress.setValue(min(1000, int(position * 1000 / duration)) if duration else 0)
        self.cur_label.setText(self._fmt(position))
        self.dur_label.setText(self._fmt(duration))

    def update_play_button(self, *args):
        icon = (QStyle.StandardPixmap.SP_MediaPause
                if self.ctx.music.player.isPlaying()
                else QStyle.StandardPixmap.SP_MediaPlay)
        self.play_button.setIcon(QApplication.instance().style().standardIcon(icon))

    def _seek_progress(self, *args):
        duration = max(0, int(self.ctx.music.player.duration()))
        if duration <= 0:
            return
        self.ctx.music.player.setPosition(int(self.progress.value() / 1000.0 * duration))

    @staticmethod
    def _fmt(ms):
        total = max(0, int(ms // 1000))
        return f"{total // 60:02d}:{total % 60:02d}"

    # ---------------- 重翻 ----------------
    def retranslate_ui(self):
        # 不重建菜单（保留音乐控制条与信号连接），仅更新文案与 checked 状态。
        current = config.settings.get("language", "zh-CN")
        self.todo_a.setText("📋 " + tr("待办"))
        self.timer_a.setText("⏱️ " + tr("计时"))
        self.alarm_a.setText("⏰️ " + tr("闹钟"))
        self.set_a.setText("⚙️ " + tr("设置"))
        self.quit_app_action.setText("🚪 " + tr("退出"))
        self.language_menu.setTitle(self._lang_menu_title())
        for code, action in self.language_actions.items():
            action.setChecked(code == current)
        self.prev_button.setToolTip(tr("上一首"))
        self.play_button.setToolTip(tr("播放/暂停"))
        self.next_button.setToolTip(tr("下一首"))
        self.update_play_button()

    # ---------------- 托盘点击 ----------------
    def _on_activate(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.ctx.pet_hidden():
                self.ctx.restore_pet()
            else:
                self.ctx.hide_pet()

    def notify(self, title: str, message: str):
        self.showMessage(title, message, self.icon(), 4000)
