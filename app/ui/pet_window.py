"""主宠物窗：透明无边框、可拖拽、右键菜单、上下文图片切换、悬浮表情包。

图片显示优先级（依据开发需求文档）：
1. 闲置超过 15 分钟 -> 随机睡觉/左休息/右休息图（播报『累了捏』）
2. 处于设置的工作时间段且用户未手动切换 -> 工作图（当前职业）
3. 其余 -> 用户选择的服装图（默认衬衫）
点击人物 -> 回到服装图（覆盖工作图），刷新交互时间。
"""

import os
import random
import math
from datetime import datetime

from PyQt6.QtCore import Qt, QPoint, QPointF, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget, QLabel, QApplication

from app.core import config, pathutil
from app.core.state import state
from app.core import assets
from app.core.speech import pick_line
from app.core.voice import say, say_wav, on_spoken
from app.core.i18n import tr
from app.ui.status_panel import StatusPanel
from app.ui.context_menu import build_menu
from app.ui.common import UploadPrompt

EMOJIS = [
    "😎", "🥰", "🤩", "🎤", "✨", "🌟", "🫧", "💤", "🍓", "🎵", "🔥", "☀️",
    "😊", "😋", "😌", "😉", "😴", "🤭", "😚", "🥳", "😇", "😆", "🤔", "💗",
    "💖", "💫", "⭐", "🍊", "🍵", "☕", "🍹", "🎧", "🎶", "🏠", "💼",
]
BASE_IMG = 200
STATUS_W = 366
STATUS_H = 215
PET_WAKE_MESSAGE = 0x8001


class EmojiBubble(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = "😎"
        self.setFixedSize(62, 50)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def setText(self, text):  # noqa: N802
        self._text = text
        self.update()

    def paintEvent(self, e):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bubble = QRectF(3, 1, 52, 38)

        path = QPainterPath()
        path.addRoundedRect(bubble, 16, 16)
        tail = QPainterPath()
        tail.moveTo(16, 35)
        tail.lineTo(25, 47)
        tail.lineTo(31, 35)
        tail.closeSubpath()
        path = path.united(tail)

        painter.setPen(QPen(QColor(249, 117, 16, 36), 1.2))
        painter.setBrush(QColor("#ffffff"))
        painter.drawPath(path)

        font = painter.font()
        font.setPixelSize(26)
        painter.setFont(font)
        painter.drawText(bubble, Qt.AlignmentFlag.AlignCenter, self._text)


class PetWindow(QWidget):
    _upload_voice_done = pyqtSignal(int, object)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._drag_pos = None
        self._press_pos = None
        self._moved = False
        self.mode = "costume"
        self.user_override = False
        self.current_work = "调酒师"
        self._drink_path = None
        self._scene_path = None
        self._prep_path = None
        self._prep_kind = None
        self._prep_name = None
        self._last_path = None
        self._idle_kind = None
        self._idle_path = None
        self._hover_keepalive = QTimer(self)
        self._hover_keepalive.setInterval(15000)
        self._hover_keepalive.timeout.connect(self._keep_hover_alive)
        self._emoji_timer = QTimer(self)
        self._emoji_timer.setInterval(80)
        self._emoji_timer.timeout.connect(self._float_emoji)
        self._emoji_phase = 0
        self._emoji_base = None

        # 拖拽上传状态
        self._forced_image = None          # 强制显示的人物图（上传交互期间覆盖正常状态）
        self._upload_active = False        # 是否处于上传交互中（避免重复触发）
        self._upload_candidate = None      # 当前被拖入的文件路径
        self._upload_stage = None          # "confirm" / "info"
        self._upload_prompt = None         # 上传确认对话框
        self._upload_voice_token = 0
        self._revert_timer = QTimer(self)
        self._revert_timer.setSingleShot(True)
        self._revert_timer.timeout.connect(self._dismiss_upload)
        self._upload_voice_done.connect(self._handle_upload_voice_done)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # SubWindow 在 Windows 上经常不会被资源管理器识别为文件投放目标。
        # 使用原生 WM_DROPFILES 兜底，保证透明桌宠也能接收外部文件。
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setObjectName("PetWindow")
        self.setWindowTitle(config.character.app_name)

        self._build()
        self._enable_native_file_drop()
        self.setMouseTracking(True)
        state.outfitChanged.connect(lambda _=None: self.refresh_image())
        self._enter_random_outfit()

    # ---------------- 构建 ----------------
    def _build(self):
        self.img_label = QLabel(self)
        self.img_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status = StatusPanel(self)
        # 状态面板只负责展示，不能拦截拖到人物窗口的文件事件。
        self.status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.status.setMouseTracking(True)
        self.emoji = EmojiBubble(self)
        self.emoji.hide()
        self.setAcceptDrops(True)
        self._relayout()

    def _relayout(self):
        scale = config.settings.get("sizeScale", 100) / 100.0
        size = int(BASE_IMG * scale)
        self._img_size = size
        idle_mode = self.mode in {"sleep", "left_rest", "right_rest"}
        window_w = size if idle_mode else max(STATUS_W, size)
        self.img_label.setGeometry(0, 0, window_w, size)
        show_status = self.mode == "drink"
        self.status.setVisible(show_status)
        if show_status:
            self.status.setGeometry((window_w - self.status.width()) // 2, size + 6, self.status.width(), STATUS_H)
            self.setFixedSize(max(window_w, self.status.width()), size + 6 + STATUS_H)
        else:
            self.setFixedSize(window_w, size)
        self._draw(self._last_path)

    # ---------------- 图片 ----------------
    def _load_pixmap(self, path: str):
        if not path or not os.path.exists(path):
            # 兜底：橙色占位
            img = QImage(STATUS_W, self._img_size, QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.transparent)
            return QPixmap.fromImage(img)
        pix = QPixmap(path)
        return pix.scaled(
            self._img_size, self._img_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _draw(self, path):
        self._last_path = path
        if self._idle_kind == "left_rest":
            self.img_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        elif self._idle_kind == "right_rest":
            self.img_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        else:
            self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setPixmap(self._load_pixmap(path))

    def _resolve(self):
        """根据上下文决定要显示的图片路径与模式。"""
        if self._forced_image is not None:
            return self._forced_image, "upload"
        if not state.hidden and state.is_idle(15 * 60):
            if self._idle_path is None:
                self._idle_kind, self._idle_path = self._pick_idle_image()
            return self._idle_path, self._idle_kind
        if self._drink_path and self.mode == "drink":
            return self._drink_path, "drink"
        if self._prep_path:
            return self._prep_path, "preparing"
        if self._scene_path:
            return self._scene_path, self.mode
        if self._in_work_hours() and not self.user_override:
            return assets.get_work_final(self.current_work), "work"
        if state.current_outfit_image:
            return state.current_outfit_image, "costume"
        return random.choice(assets.get_costume_images(state.current_outfit) or [""]), "costume"

    def _pick_idle_image(self):
        kind = random.choice(["sleep", "left_rest", "right_rest"])
        if kind == "sleep":
            return kind, assets.get_home_final("睡觉")
        side = "left" if kind == "left_rest" else "right"
        choices = assets.get_idle_rest_images(side)
        if choices:
            return kind, random.choice(choices)
        return "sleep", assets.get_home_final("睡觉")

    def _clear_idle_image(self):
        self._idle_kind = None
        self._idle_path = None

    def _position_idle_window(self):
        if self._idle_kind not in {"left_rest", "right_rest"}:
            return
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        rect = screen.availableGeometry()
        y = max(rect.top(), min(self.y(), rect.bottom() - self.height()))
        if self._idle_kind == "left_rest":
            self.move(rect.left(), y)
        else:
            self.move(rect.right() - self.width() + 1, y)

    def refresh_image(self, force=False):
        path, mode = self._resolve()
        prev = self.mode
        self.mode = mode
        # 先绘制/布局以确定最新尺寸，再对 left/right_rest 做贴边定位。
        # 若先定位后 relayout，right_rest 会按旧宽度计算，导致窗口未贴右边缘，
        # 下一次刷新才闪现到正确位置。
        if force or path != self._last_path:
            self._draw(path)
        self._relayout()
        self._position_idle_window()
        if mode == "sleep" and prev != "sleep":
            line = config.character.home.get("idleTimeoutLine", "累了捏")
            say(line)
        elif mode in {"left_rest", "right_rest"} and prev not in {"left_rest", "right_rest"}:
            line = config.character.home.get("idleTimeoutLine", "累了捏")
            say(line)
        self.update()

    def _enter_random_outfit(self):
        items = config.character.costume.get("itemList", [])
        if items:
            state.current_outfit = random.choice(items).get("name", state.current_outfit)
            state.current_outfit_image = state._pick_outfit_image(state.current_outfit)
        self.mode = "costume"
        self.user_override = True
        self._drink_path = None
        self._scene_path = None
        self._prep_path = None
        self.refresh_image(force=True)

    def _in_work_hours(self) -> bool:
        wt = config.settings.get("workTime", {})
        now = datetime.now().time()
        for key in ("morning", "afternoon"):
            rng = (config.settings.get("workTime") or {}).get(key)
            if not rng or len(rng) < 2:
                continue
            try:
                start = datetime.strptime(rng[0], "%H:%M").time()
                end = datetime.strptime(rng[1], "%H:%M").time()
            except Exception:  # noqa: BLE001
                continue
            if start <= now <= end:
                return True
        return False

    # ---------------- 交互 ----------------
    def mousePressEvent(self, e):
        self._clear_idle_image()
        state.mark_interaction()
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint()
            self._press_pos = e.globalPosition().toPoint()
            self._moved = False
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        self._clear_idle_image()
        if self.underMouse():
            state.mark_interaction()
        if self._drag_pos is not None:
            delta = e.globalPosition().toPoint() - self._drag_pos
            if delta.manhattanLength() > 4:
                self._moved = True
            self.move(self.pos() + delta)
            self._drag_pos = e.globalPosition().toPoint()
            if self._prep_path:
                self.ctx.check_scene_pair()
            if self._upload_prompt is not None and self._upload_prompt.isVisible():
                self._upload_prompt.move(self._prompt_pos())
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            if not self._moved:
                self._on_click()
            elif self._prep_path:
                self.ctx.check_scene_pair()
            self._drag_pos = None
            self._press_pos = None
        super().mouseReleaseEvent(e)

    def _on_click(self):
        self.ctx.stop_alarm()
        state.mark_interaction()
        self._clear_idle_image()
        self._scene_path = None
        if self.mode != "costume" and self.mode != "drink":
            self.user_override = True
            self.mode = "costume"
            self.refresh_image()
        # 状态面板常驻，点击即刷新数值

    # ---------------- 拖拽上传 ----------------
    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            # Windows 文件管理器通常给 QWidget 提议 MoveAction；桌宠上传应明确
            # 告知系统这是复制导入，否则光标会一直显示“禁止放置”。
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()
        else:
            e.ignore()

    def dragMoveEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()
        else:
            e.ignore()

    def dropEvent(self, e):  # noqa: N802
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path and os.path.exists(path):
                self.on_file_dropped(path)
        e.setDropAction(Qt.DropAction.CopyAction)
        e.accept()

    def _enable_native_file_drop(self):
        """注册 Windows 文件拖放；Qt OLE 拖放失效时仍可收到 WM_DROPFILES。"""
        if os.name != "nt":
            return
        try:
            import ctypes
            ctypes.windll.shell32.DragAcceptFiles(int(self.winId()), True)
        except Exception:  # noqa: BLE001
            pass

    def nativeEvent(self, event_type, message):  # noqa: N802
        """处理 Windows 资源管理器投放的文件列表。"""
        if os.name != "nt":
            return False, 0
        try:
            import ctypes
            from ctypes import wintypes

            if isinstance(event_type, bytes):
                is_windows = event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG")
            else:
                is_windows = str(event_type) in ("windows_generic_MSG", "windows_dispatcher_MSG")
            if not is_windows:
                return False, 0

            msg = wintypes.MSG.from_address(int(message))
            if msg.message == PET_WAKE_MESSAGE:
                self.do_show()
                return True, 0
            if msg.message != 0x0233:  # WM_DROPFILES
                return False, 0

            hdrop = wintypes.HANDLE(msg.wParam)
            shell32 = ctypes.windll.shell32
            count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
            for index in range(count):
                length = shell32.DragQueryFileW(hdrop, index, None, 0)
                buf = ctypes.create_unicode_buffer(length + 1)
                shell32.DragQueryFileW(hdrop, index, buf, length + 1)
                path = buf.value
                if path and os.path.exists(path):
                    self.on_file_dropped(path)
                    break
            shell32.DragFinish(hdrop)
            return True, 0
        except Exception:  # noqa: BLE001
            return False, 0

    def closeEvent(self, e):  # noqa: N802
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.shell32.DragAcceptFiles(int(self.winId()), False)
            except Exception:  # noqa: BLE001
                pass
        super().closeEvent(e)

    def on_file_dropped(self, path: str):
        """用户把文件拖到人物身上：进入上传检测流程（任何状态下都可触发）。"""
        if self._upload_active:
            return
        self._upload_active = True
        self._upload_candidate = path
        state.mark_interaction()
        if assets.is_audio_file(path):
            self._begin_upload_confirm()
        else:
            self._begin_upload_reject()

    def _ensure_prompt(self):
        if self._upload_prompt is None:
            self._upload_prompt = UploadPrompt(None)
            self._upload_prompt.accepted.connect(self._on_prompt_yes)
            self._upload_prompt.rejected.connect(self._on_prompt_no)

    def _prompt_pos(self):
        w = self._upload_prompt.width()
        x = self.x() + (self.width() - w) // 2
        y = self.y() + self.height() + 6
        return QPoint(x, y)

    def _set_forced_image(self, path):
        """强制显示某张人物图（覆盖正常运行状态）。"""
        self._forced_image = path
        self.refresh_image(force=True)

    def _begin_upload_confirm(self):
        self._upload_stage = "confirm"
        self._set_forced_image(assets.get_home_final("是否上传"))
        self._ensure_prompt()
        self._upload_prompt.configure_confirm(tr("是否上传该歌曲"), tr("是"), tr("否"))
        self._set_prompt_buttons_enabled(False)
        self._upload_prompt.show_near(self._prompt_pos())
        self._speak_upload_line("是否添加该歌曲？", self._enable_prompt_after_voice)

    def _begin_upload_reject(self):
        self._upload_stage = "info"
        self._set_forced_image(assets.get_home_final("拒绝上传"))
        self._ensure_prompt()
        self._upload_prompt.configure_info(tr("我暂时不支持上传这种文件捏~"), tr("好嘟"))
        self._set_prompt_buttons_enabled(False)
        self._upload_prompt.show_near(self._prompt_pos())
        self._speak_upload_line("不好意思上传失败捏~", self._enable_prompt_after_voice)

    def _do_upload_success(self):
        path = self._upload_candidate
        imported = self.ctx.music.add_files([path]) if path else []
        self._upload_stage = "info"
        if imported:
            self._set_forced_image(assets.get_home_final("上传成功"))
            self._upload_prompt.configure_info(tr("上传成功！"), tr("好嘟"))
            self._set_prompt_buttons_enabled(True)
        else:
            self._set_forced_image(assets.get_home_final("拒绝上传"))
            self._upload_prompt.configure_info(tr("上传失败，请稍后再试"), tr("好嘟"))
            self._set_prompt_buttons_enabled(False)
            self._speak_upload_line("不好意思上传失败捏~", self._enable_prompt_after_voice)

    def _on_prompt_yes(self):
        if self._upload_stage == "confirm":
            self._set_prompt_buttons_enabled(False)
            self._do_upload_success()
        else:
            self._set_prompt_buttons_enabled(False)
            self._dismiss_upload()
            self._play_upload_ok_detached()

    def _on_prompt_no(self):
        if self._upload_stage == "confirm":
            self._dismiss_upload()

    def _upload_voice_path(self, filename: str) -> str:
        user_path = pathutil.data_file("voice", "Upload Voice Media", filename)
        if os.path.exists(user_path):
            return user_path
        bundled = os.path.join(pathutil.get_bundled_data_dir(), "voice", "Upload Voice Media", filename)
        if os.path.exists(bundled):
            return bundled
        source_path = os.path.join(pathutil.APP_DIR, "data", "voice", "Upload Voice Media", filename)
        if os.path.exists(source_path):
            return source_path
        return user_path

    def _speak_upload_line(self, text: str, callback=None):
        self._upload_voice_token += 1
        token = self._upload_voice_token

        def _done():
            self._upload_voice_done.emit(token, callback)

        if not on_spoken(_done):
            QTimer.singleShot(0, lambda: self._handle_upload_voice_done(token, callback))
            return
        if not say(text):
            self._handle_upload_voice_done(token, callback)

    def _speak_upload_ok(self, callback=None):
        self._upload_voice_token += 1
        token = self._upload_voice_token

        def _done():
            self._upload_voice_done.emit(token, callback)

        if not on_spoken(_done):
            QTimer.singleShot(0, lambda: self._handle_upload_voice_done(token, callback))
            return
        path = self._upload_voice_path("upload_ok.wav")
        if os.path.exists(path):
            if not say_wav(path):
                self._handle_upload_voice_done(token, callback)
        else:
            if not say("好嘟"):
                self._handle_upload_voice_done(token, callback)

    def _play_upload_ok_detached(self):
        path = self._upload_voice_path("upload_ok.wav")
        if os.path.exists(path):
            say_wav(path)
        else:
            say("好嘟")

    def _handle_upload_voice_done(self, token: int, callback):
        if token == self._upload_voice_token and self._upload_active and callback:
            callback()

    def _set_prompt_buttons_enabled(self, enabled: bool):
        if self._upload_prompt is None:
            return
        self._upload_prompt.yes_b.setEnabled(enabled)
        self._upload_prompt.no_b.setEnabled(enabled)

    def _enable_prompt_after_voice(self):
        self._set_prompt_buttons_enabled(True)

    def _schedule_revert(self, ms: int):
        self._revert_timer.start(ms)

    def _dismiss_upload(self):
        """收起对话框并恢复人物原本状态（人物图与对话框同步消失）。"""
        self._revert_timer.stop()
        if self._upload_prompt is not None:
            self._upload_prompt.hide()
        self._forced_image = None
        self._upload_active = False
        self._upload_candidate = None
        self._upload_stage = None
        self._clear_idle_image()
        self.refresh_image(force=True)

    def enterEvent(self, e):  # noqa: N802
        self._hover_keepalive.start()
        was_idle = self.mode in {"sleep", "left_rest", "right_rest"}
        self._clear_idle_image()
        state.mark_interaction()
        if was_idle:
            self.refresh_image(force=True)
        if self._emoji_enabled_for_mode():
            self._show_emoji()
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._hover_keepalive.stop()
        super().leaveEvent(e)

    def _keep_hover_alive(self):
        if self.underMouse():
            state.mark_interaction()

    def _emoji_enabled_for_mode(self):
        return self.mode in {"costume", "drink", "sleep", "work", "home"}

    def _show_emoji(self):
        self.emoji.setText(random.choice(EMOJIS))
        image_left = (self.width() - self._img_size) // 2
        x = image_left + self._img_size - self.emoji.width() - 4
        self._emoji_base = QPointF(max(0, x), 2)
        self._emoji_phase = 0
        self.emoji.move(int(self._emoji_base.x()), int(self._emoji_base.y()))
        self.emoji.show()
        self._emoji_timer.start()
        QTimer.singleShot(2500, self._hide_emoji)

    def _float_emoji(self):
        if self._emoji_base is None or not self.emoji.isVisible():
            return
        self._emoji_phase += 1
        y = self._emoji_base.y() + math.sin(self._emoji_phase / 7.0) * 4
        self.emoji.move(int(self._emoji_base.x()), int(y))

    def _hide_emoji(self):
        self.emoji.hide()
        self._emoji_timer.stop()

    def contextMenuEvent(self, e):  # noqa: N802
        if self._upload_active:
            e.ignore()
            return
        if hasattr(self.ctx, "begin_popup_menu"):
            self.ctx.begin_popup_menu()
        try:
            menu = build_menu(self)
            action = menu.exec(e.globalPos())
        finally:
            if hasattr(self.ctx, "end_popup_menu"):
                self.ctx.end_popup_menu()
        if action is not None:
            self._handle_menu(action.data())

    # ---------------- 菜单处理 ----------------
    def _handle_menu(self, data: dict):
        if not data:
            return
        state.mark_interaction()
        kind = data.get("kind")
        if kind == "drink":
            self._do_drink(data["category"], data["item"])
        elif kind == "outfit":
            self.clear_drink_state()
            self._do_outfit(data["name"])
        elif kind == "work":
            self.clear_drink_state()
            self.ctx.music.leave_activity()
            self.current_work = data["name"]
            self.user_override = False
            self.ctx.open_scene("work", data["name"])
        elif kind == "home":
            self.clear_drink_state()
            self.ctx.music.leave_activity()
            self.ctx.open_scene("home", data["name"])
        elif kind == "todo":
            self.clear_drink_state()
            self.ctx.music.leave_activity()
            self.ctx.open_todo()
        elif kind == "alarm":
            self.clear_drink_state()
            self.ctx.music.leave_activity()
            self.ctx.open_alarm()
        elif kind == "timer":
            self.clear_drink_state()
            self.ctx.music.leave_activity()
            self.ctx.open_timer()
        elif kind == "hide":
            self.clear_drink_state()
            self.ctx.hide_pet()
        elif kind == "settings":
            self.clear_drink_state()
            self.ctx.music.leave_activity()
            self.ctx.open_settings()
        elif kind == "exit":
            self.clear_drink_state()
            self.ctx.quit_app()

    def _do_drink(self, category, item):
        self._scene_path = None
        self.ctx.music.leave_activity()
        state.drink(item)
        path = assets.get_drink_image(category, item["name"])
        self._drink_path = path
        self.mode = "drink"
        self.user_override = True
        self._draw(path)
        self._relayout()
        say(pick_line(item.get("lines", [])) or config.character.drinks.get("drinkCommonReply", ""))

    def _do_outfit(self, name):
        self._scene_path = None
        self.ctx.music.leave_activity()
        state.set_outfit(name)
        self.mode = "costume"
        self.user_override = True
        self.refresh_image(force=True)
        cfg = next((c for c in config.character.costume.get("itemList", [])
                    if c["name"] == name), {})
        say(pick_line(cfg.get("lines", [])))

    def show_scene_image(self, path, kind, name):
        self._drink_path = None
        self._scene_path = path
        self.mode = kind
        self.user_override = True
        state.mark_interaction()
        self._clear_idle_image()
        self._draw(path)
        self._relayout()

    def begin_preparation(self, path, kind, name):
        self._hide_emoji()
        self._prep_path = path
        self._prep_kind = kind
        self._prep_name = name
        self._scene_path = None
        self.mode = "preparing"
        self.user_override = True
        self._clear_idle_image()
        self._draw(path)
        self._relayout()

    def finish_preparation(self, path, kind, name):
        self._prep_path = None
        self._prep_kind = None
        self._prep_name = None
        self.show_scene_image(path, kind, name)

    def clear_scene_image(self):
        self._scene_path = None
        self._prep_path = None
        self._prep_kind = None
        self._prep_name = None
        self._clear_idle_image()
        self.refresh_image(force=True)

    def clear_drink_state(self):
        self._drink_path = None
        self._scene_path = None
        self._prep_path = None
        self._prep_kind = None
        self._prep_name = None
        self._clear_idle_image()
        if self.mode == "drink":
            self.mode = "costume"
        self.status.hide()
        self.refresh_image(force=True)

    # ---------------- 隐身 ----------------
    def do_hide(self):
        self._drag_pos = None
        self._press_pos = None
        self._moved = False
        self._hover_keepalive.stop()
        self._clear_idle_image()
        state.mark_interaction()
        state.set_hidden(True)
        self.hide()

    def do_show(self):
        self._clear_idle_image()
        state.mark_interaction()
        state.set_hidden(False)
        self.refresh_image(force=True)
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
