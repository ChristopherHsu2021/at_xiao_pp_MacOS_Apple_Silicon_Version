"""AT小PP 桌面宠物 · 主入口与应用控制器。

运行模式（由命令行参数分发）：
  --install    启动安装向导
  --uninstall  执行卸载
  (无参数)      正常运行桌面宠物

App 同时充当各 UI 模块的 ctx（上下文）：集中管理宠物窗、托盘、音乐播放器，
以及后台调度（数值衰减 / 闲置睡觉 / 闹钟与待办提醒 / 每周一清理）。
"""

import sys
import os
import random
from datetime import datetime

# macOS 透明/圆角窗口需要图层化渲染，否则透明背景窗口会异常。
if sys.platform == "darwin":
    os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")

# macOS 冻结包（.app）：OpenSSL 的默认 CA 路径指向构建机的 Python 安装目录，
# 在用户机器上不存在 → urllib/https 全部 CERTIFICATE_VERIFY_FAILED，
# 表现为音乐播放器「网络搜索彻底失效」（Windows 有系统证书商店回退所以没事）。
# 用 certifi 的 CA 包兜底（在首次任何网络请求前设置）。
if sys.platform == "darwin" and not os.environ.get("SSL_CERT_FILE"):
    try:
        import certifi

        os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        pass

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QTimer, QPoint

from app.core import assets, config, pathutil
from app.core.state import state
from app.core.speech import pick_line
from app.core.voice import (
    init_voice, apply_settings_to_voice, say, say_temporary, stop_speaking, on_spoken,
)
from app.core import todo, alarm as alarm_mod
from app.ui.style import apply_theme
from app.ui.pet_window import PetWindow, PET_WAKE_MESSAGE
from app.ui.tray import TrayManager
from app.ui.music_player import MusicPlayer
from app.ui.todo_window import TodoWindow
from app.ui.alarm_window import AlarmWindow
from app.ui.timer_window import TimerWindow
from app.ui.settings_window import SettingsWindow
from app.ui.scene_window import PreparationItemWindow
from app.ui.install_window import (
    InstallerWindow, UninstallerWindow, acquire_single_instance,
    show_running_warning, schedule_inno_uninstall_cleanup, is_admin,
    relaunch_as_admin, launch_detached_deelevated,
)
from app.ui.common import keep_on_top, release_topmost


APP_INSTANCE_MUTEX = "Local\\ATXiaoPPMain"


def _wake_existing_main_window() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        title = config.character.app_name
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return False
        # 由原实例在 Qt 主线程内完成显示，避免外部进程直接修改窗口状态，
        # 导致 Qt 的 isVisible() 与 Win32 实际状态不同步。
        user32.PostMessageW(hwnd, PET_WAKE_MESSAGE, 0, 0)
        return True
    except Exception:  # noqa: BLE001
        return False



def _boot_voice_line(now: datetime | None = None) -> str:
    now = now or datetime.now()
    if 4 <= now.hour < 12:
        return "早上好"
    if 12 <= now.hour < 18:
        return "下午好"
    return "晚上好"


class App:
    def __init__(self):
        self.pet = PetWindow(self)
        self.music = MusicPlayer(self)
        self.tray = TrayManager(self)
        self.windows = {}          # 复用单例窗口
        self.scene = None
        self._scene_kind = None
        self._scene_name = None
        self._completing_scene = False
        self._alarm_text_timer = QTimer()
        self._alarm_text_timer.setInterval(5000)
        self._alarm_text_timer.timeout.connect(self._repeat_alarm_text)
        self._active_alarm_text = None
        self._alarm_active = False
        self._quitting = False
        self._quit_connected = False
        self._popup_menu_open = False
        self._topmost_released = False

        self.tray.show()
        self._position_pet()
        self.pet.show()
        QApplication.instance().applicationStateChanged.connect(lambda _state: self._keep_topmost())
        self._keep_topmost()

        self._start_schedulers()
        self._boot()

    # ---------------- 位置 ----------------
    def _position_pet(self):
        screen = QApplication.primaryScreen().availableGeometry()
        margin = 24
        max_x = max(screen.left() + margin, screen.right() - self.pet.width() - margin)
        max_y = max(screen.top() + margin, screen.bottom() - self.pet.height() - margin)
        x = random.randint(screen.left() + margin, max_x)
        y = random.randint(screen.top() + margin, max_y)
        self.pet.move(x, y)

    # ---------------- 启动播报 ----------------
    def _boot(self):
        say(_boot_voice_line())

    # ---------------- 后台调度 ----------------
    def _start_schedulers(self):
        # 数值衰减（60s 周期）
        QTimer.singleShot(60000, self._decay_loop)
        # 闲置/工作时段图片刷新（10s）
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self.pet.refresh_image)
        self._refresh_timer.start(10000)
        # 闹钟 + 待办提醒（20s）
        self._remind_timer = QTimer()
        self._remind_timer.timeout.connect(self._check_reminders)
        self._remind_timer.start(20000)
        # 每周一清理（每小时）
        self._cleanup_timer = QTimer()
        self._cleanup_timer.timeout.connect(lambda: todo.cleanup_weekly())
        self._cleanup_timer.start(3600000)
        todo.cleanup_weekly()
        self._topmost_timer = QTimer()
        self._topmost_timer.timeout.connect(self._keep_topmost)
        self._topmost_timer.start(1500)

    def _decay_loop(self):
        state.decay()
        QTimer.singleShot(60000, self._decay_loop)

    def _check_reminders(self):
        now = datetime.now()
        alarms = alarm_mod.load()
        # 闹钟
        for a in alarms:
            if alarm_mod.should_ring(a, now):
                self._fire_alarm(a, now)
                alarm_mod.mark_rung(a, now)
        # 待办提醒
        tasks = todo.all_tasks()
        alarm_ids = {a.get("id") for a in alarms}
        changed = False
        for t in tasks:
            # 有关联闹钟的待办由闹钟统一播报，避免同一提醒播报两遍。
            if (t.get("done") or not t.get("remind") or
                    not t.get("remind_enabled", True) or
                    t.get("alarm_id") in alarm_ids):
                continue
            try:
                when = datetime.strptime(t["remind"], "%Y-%m-%d %H:%M")
            except Exception:  # noqa: BLE001
                continue
            notify_key = when.strftime("%Y-%m-%d %H:%M")
            if now >= when and t.get("notified") != notify_key:
                t["notified"] = notify_key
                changed = True
                self.tray.notify(tr_task(t["content"]), "⏰️ " + tr_task("时间到捏"))
                say(t["content"] + "，时间到捏")
        if changed:
            todo.save(tasks)

    def _fire_alarm(self, a, now):
        # 同一时间只允许一个闹钟占用播报通道，避免旧语音/歌曲与新闹钟叠加。
        self.stop_alarm()
        self._alarm_active = True
        name = a.get("ringtone") or a.get("custom_text") or ""
        self.tray.notify(tr_alarm("闹钟"), "⏰️ " + (name or tr_alarm("时间到捏")))
        if a.get("ringtone"):
            import os
            from app.core import assets
            cand = [p for p in assets.list_music_files()
                    if os.path.splitext(os.path.basename(p))[0] == a["ringtone"]]
            if cand:
                self.music.play_alarm(cand[0])
            else:
                say(config.character.system_func.get("alarm", {}).get("remind", "叮——时间到捏"))
        elif a.get("custom_text"):
            self._active_alarm_text = a["custom_text"]
            say_temporary(self._active_alarm_text)
            self._alarm_text_timer.start()
        else:
            say(config.character.system_func.get("alarm", {}).get("remind", "叮——时间到捏"))

    def _repeat_alarm_text(self):
        if self._active_alarm_text:
            stop_speaking()
            say_temporary(self._active_alarm_text)

    def stop_alarm(self):
        """停止当前闹钟的隐藏音频与循环语音。"""
        active = bool(self._alarm_active or self._active_alarm_text or
                      self.music.alarm_active())
        self._alarm_active = False
        self._active_alarm_text = None
        self._alarm_text_timer.stop()
        if active:
            stop_speaking()
        self.music.stop_alarm()

    # ---------------- 窗口打开（单例复用） ----------------
    def _single(self, key, factory):
        if key not in self.windows or self.windows[key] is None:
            self.windows[key] = factory()
        w = self.windows[key]
        w.show()
        keep_on_top(w, bring_to_front=True, activate=True)
        return w

    def _keep_topmost(self):
        if self._foreground_belongs_to_other_app():
            self._release_app_topmost()
            return
        if self._popup_menu_open:
            return

        self._topmost_released = False
        active = QApplication.activeWindow()
        if not state.hidden and self.pet.isVisible():
            keep_on_top(self.pet)
        if self.scene is not None and self.scene.isVisible():
            keep_on_top(self.scene)
        for window in self.windows.values():
            if window is not None and window.isVisible():
                keep_on_top(window)
        if self.music.window is not None and self.music.window.isVisible():
            keep_on_top(self.music.window)
        if active is not None and active.isVisible():
            owned = active is self.pet or active is self.scene or active in self.windows.values()
            owned = owned or active is self.music.window
            if owned:
                keep_on_top(active, bring_to_front=True)

    def begin_popup_menu(self):
        self._popup_menu_open = True

    def end_popup_menu(self):
        self._popup_menu_open = False
        self._keep_topmost()

    def _release_app_topmost(self):
        if self._topmost_released:
            return
        if not state.hidden and self.pet.isVisible():
            release_topmost(self.pet)
        if self.scene is not None and self.scene.isVisible():
            release_topmost(self.scene)
        for window in self.windows.values():
            if window is not None and window.isVisible():
                release_topmost(window)
        if self.music.window is not None and self.music.window.isVisible():
            release_topmost(self.music.window)
        self._topmost_released = True

    def _foreground_belongs_to_other_app(self):
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            foreground = ctypes.windll.user32.GetForegroundWindow()
            if not foreground:
                return False
            own_handles = {int(w.winId()) for w in QApplication.topLevelWidgets() if w is not None}
            return foreground not in own_handles
        except Exception:  # noqa: BLE001
            return False

    def open_todo(self):
        self._single("todo", lambda: TodoWindow(self))

    def open_alarm(self):
        self._single("alarm", lambda: AlarmWindow(self))

    def open_timer(self):
        self._single("timer", lambda: TimerWindow(self))

    def open_settings(self):
        self._single("settings", lambda: SettingsWindow(self))

    def refresh_todo(self):
        window = self.windows.get("todo")
        if window is not None:
            window.refresh_external()

    def refresh_alarm(self):
        window = self.windows.get("alarm")
        if window is not None:
            window.refresh_external()

    def open_scene(self, kind, name):
        if self.scene is not None:
            self.scene.close()
        self.scene = None
        self.pet.clear_drink_state()
        self.pet.clear_scene_image()
        prep = (
            assets.get_work_prep(name) if kind == "work"
            else assets.get_home_prep(name)
        )
        self._scene_kind = kind
        self._scene_name = name
        self.pet.begin_preparation(prep[0], kind, name)
        self.scene = PreparationItemWindow(self, prep[1], self.check_scene_pair)
        screen = QApplication.primaryScreen().availableGeometry()
        gap = 96
        x = self.pet.x() + self.pet.width() + gap
        if x + self.scene.width() > screen.right():
            x = self.pet.x() - self.scene.width() - gap
        y = max(screen.top(), min(self.pet.y() + 24, screen.bottom() - self.scene.height()))
        self.scene.move(x, y)
        self.scene.show()
        keep_on_top(self.scene, bring_to_front=True)
        keep_on_top(self.pet)

    def check_scene_pair(self):
        if self.scene is None or not self.scene.isVisible():
            return
        # 防止拖拽移动事件高频重复触发（每次 mouseMove 都会调用本方法）
        if getattr(self, "_completing_scene", False):
            return
        pet_rect = self.pet.frameGeometry()
        item_rect = self.scene.frameGeometry()
        if pet_rect.intersects(item_rect):
            # 关键修复：本方法在「拖拽宠物」的 mouseMoveEvent 中调用。若同步执行
            # _complete_scene()，会立即 close() 场景窗、并重建宠物窗子控件——这些都发生在
            # 鼠标事件派发中途，导致 Qt 的 sendMouseEvent/notify 解引用已销毁的 widget，
            # 触发 SIGSEGV（KERN_INVALID_ADDRESS，崩溃栈落在 QApplication::notify）。
            # 故延迟到当前事件派发结束后的下一轮事件循环再执行。
            self._completing_scene = True
            QTimer.singleShot(0, self._complete_scene)

    def _complete_scene(self):
        if self.scene is None:
            self._completing_scene = False
            return
        # 延迟期间用户可能已主动关闭场景窗
        if not self.scene.isVisible():
            self.scene = None
            self._completing_scene = False
            return
        kind, name = self._scene_kind, self._scene_name
        final = assets.get_work_final(name) if kind == "work" else assets.get_home_final(name)
        item = self.scene
        self.scene = None
        item.close()
        self.pet.finish_preparation(final, kind, name)

        cfg = next((x for x in (
            config.character.work if kind == "work" else config.character.home
        ).get("itemList", []) if x["name"] == name), {})
        if kind == "work" and name == "歌手":
            self.music.start_singer_show()
        elif kind == "home" and name == "听歌":
            self.music.play_random(show_player=True)
        else:
            say(pick_line(cfg.get("lines", [])))
        self._scene_kind = None
        self._scene_name = None
        self._completing_scene = False

    def show_scene_image(self, path, kind, name):
        """将已触发的工作/居家结果同步到桌面宠物窗。"""
        self.pet.show_scene_image(path, kind, name)

    # ---------------- 隐身 / 退出 ----------------
    def hide_pet(self):
        self.pet.do_hide()
        self.tray.notify(tr_hide("隐身"), tr_hide("我已隐身，点击恢复显示"))

    def restore_pet(self):
        self.pet.do_show()

    def pet_hidden(self):
        return state.hidden

    def quit_app(self):
        if self._quitting:
            return
        self._quitting = True
        self._hide_windows_for_quit()
        self._stop_background_for_quit()
        line = config.character.system_func.get("exit", {}).get(
            "confirm", "要和你暂时告别捏"
        )
        if not self._quit_connected:
            on_spoken(QApplication.instance().quit)
            self._quit_connected = True
        say(line)

    def _hide_windows_for_quit(self):
        self.pet.hide()
        if self.scene is not None:
            self.scene.hide()
        for window in self.windows.values():
            if window is not None:
                window.hide()
        self.tray.hide()

    def _stop_background_for_quit(self):
        self._refresh_timer.stop()
        self._remind_timer.stop()
        self._cleanup_timer.stop()
        self.stop_alarm()
        self.music.close_player()
        stop_speaking()

    # ---------------- 设置应用 ----------------
    def apply_settings(self):
        apply_settings_to_voice()
        self.music.apply_settings()
        self.pet.refresh_image(force=True)
        self.tray.retranslate_ui()
        self.music.retranslate_ui()
        for window in self.windows.values():
            if window is not None and hasattr(window, "retranslate_ui"):
                window.retranslate_ui()
        if self.scene is not None and hasattr(self.scene, "retranslate_ui"):
            self.scene.retranslate_ui()
        from app.ui.install_window import set_autostart
        # 仅打包后（真实 exe/app）才写自启；源码模式下跳过
        if getattr(sys, "frozen", False):
            if sys.platform == "darwin":
                # macOS 自启需指向 .app 包，而非内部可执行文件
                app_path = os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
                set_autostart(config.settings.get("autostart", True), app_path)
            else:
                set_autostart(config.settings.get("autostart", True), sys.executable)


# i18n 便捷函数（避免循环，直接引用 core.i18n）
from app.core.i18n import tr as _tr


def tr_task(s): return _tr(s)
def tr_alarm(s): return _tr(s)
def tr_hide(s): return _tr(s)


def main():
    args = sys.argv[1:]
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    config.settings.set("volume", 50, save=True)
    config.settings.set("voiceEngine", "sapi", save=True)
    icon_path = assets.find_image("桌面图标")
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))
    apply_theme(app)

    if "--custom-uninstall" not in args and "--install" not in args and "--uninstall" not in args:
        if not acquire_single_instance(APP_INSTANCE_MUTEX):
            _wake_existing_main_window()
            return 0

    if "--custom-uninstall" in args:
        if not is_admin() and relaunch_as_admin(sys.argv[1:]):
            return 0
        if not acquire_single_instance("Local\\ATXiaoPPUninstaller"):
            show_running_warning(tr_hide("卸载正在进行捏~"))
            return 0
        if "--quiet" in args:
            schedule_inno_uninstall_cleanup()
            return 0
        init_voice()
        w = UninstallerWindow(run_inno_uninstaller=True)
        w.show()
        return app.exec()

    if "--install" in args:
        if not acquire_single_instance("Local\\ATXiaoPPInstaller"):
            show_running_warning(tr_hide("安装正在进行捏~"))
            return 0
        init_voice()
        w = InstallerWindow(inno_managed="--inno-managed" in args)
        w.show()
        return app.exec()
    if "--uninstall" in args:
        if not acquire_single_instance("Local\\ATXiaoPPUninstaller"):
            show_running_warning(tr_hide("卸载正在进行捏~"))
            return 0
        init_voice()
        w = UninstallerWindow(inno_managed="--inno-managed" in args)
        w.show()
        return app.exec()

    # 正常模式
    # 拖拽修复：正常模式运行时并不需要管理员权限。若本进程处于高完整性（例如安装
    # 向导「立即打开」或右键「以管理员身份运行」所拉起的实例），Windows UIPI 会
    # 拦截普通资源管理器的文件拖放（红圈禁止）。检测到后自动降权重启一次再退出；
    # 降权不可用（如整个 shell 均提权）时继续以当前权限运行，保证应用可用。
    if sys.platform == "win32" and getattr(sys, "frozen", False) and is_admin():
        if launch_detached_deelevated(sys.executable):
            return 0
    init_voice()
    controller = App()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
