"""工作 / 居家 场景窗：先显示准备图（人物 + 物品），拖拽拼合后触发最终图 + 语音。

- 工作·歌手：随机完整播放一首，不显示播放器。
- 居家·听歌：打开播放器随机播放；切换状态时播放器退出（on_close 停止）。
"""

import os
import math
import random

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout

from app.core import config, assets
from app.core.speech import pick_line
from app.core.voice import say
from app.core.i18n import tr
from app.ui.common import GlassWindow


def _random_point_around(center_x, center_y, radius_min, radius_max, max_x, max_y, width, height):
    for _ in range(16):
        angle = random.uniform(0, math.tau)
        radius = random.uniform(radius_min, radius_max)
        x = int(center_x + math.cos(angle) * radius - width / 2)
        y = int(center_y + math.sin(angle) * radius - height / 2)
        if 0 <= x <= max_x - width and 0 <= y <= max_y - height:
            return x, y
    return max(0, min(max_x - width, int(center_x + radius_min - width / 2))), max(0, min(max_y - height, int(center_y - height / 2)))


class PreparationItemWindow(QWidget):
    """桌面上的准备物品，独立于宠物窗拖动。"""

    def __init__(self, ctx, path, on_moved):
        super().__init__()
        self.ctx = ctx
        self._drag_pos = None
        self._on_moved = on_moved
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.image = QLabel(self)
        self.image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if path and os.path.exists(path):
            pix = QPixmap(path).scaled(
                180, 180, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            pix = QPixmap(180, 180)
            pix.fill(Qt.GlobalColor.transparent)
        self.image.setPixmap(pix)
        self.image.setFixedSize(pix.size())
        self.setFixedSize(pix.size())
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            self._on_moved()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._drag_pos = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._on_moved()
        super().mouseReleaseEvent(e)


class MovableLabel(QLabel):
    def __init__(self, path, parent, on_moved=None):
        super().__init__(parent)
        self._drag = None
        self._on_moved = on_moved
        if path and os.path.exists(path):
            pix = QPixmap(path).scaled(
                130, 130, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            pix = QPixmap(130, 130)
            pix.fill(Qt.GlobalColor.transparent)
        self.setPixmap(pix)
        self.setFixedSize(pix.size())
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag is not None:
            self.move(self.pos() + (e.pos() - self._drag))
            if self._on_moved:
                self._on_moved()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if self._on_moved:
            self._on_moved()
        super().mouseReleaseEvent(e)


class SceneWindow(GlassWindow):
    def __init__(self, ctx, kind, name):
        super().__init__(ctx, f"{tr(kind)} · {tr(name)}", 460, 400)
        self.kind = kind
        self.name = name
        self.triggered = False
        self._build()
        self.on_close = self._on_close

    def _build(self):
        root = QVBoxLayout()
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        self.body_layout.addLayout(root)

        self.canvas = QWidget()
        self.canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.canvas.setMinimumHeight(240)
        self.canvas.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,#fef3e2,#f9d9aa);"
            "border-radius:16px;"
        )
        root.addWidget(self.canvas, 1)

        self.hint = QLabel(tr("把『人物』拖到『物品』上，凑到一起就能触发捏～"))
        self.hint.setStyleSheet("font-size:12px;color:#a08e7a;text-align:center;")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.hint)

        person_path, item_path = (
            assets.get_work_prep(self.name) if self.kind == "work"
            else assets.get_home_prep(self.name)
        )
        self.person = MovableLabel(person_path, self.canvas, self.ctx.check_scene_pair)
        self.item = MovableLabel(item_path, self.canvas, self.ctx.check_scene_pair)
        self._place_prepare_items(randomize_item=True)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if hasattr(self, "person"):
            if not self.triggered:
                self._place_prepare_items(randomize_item=False)

    def _place_prepare_items(self, randomize_item):
        cw = max(1, self.canvas.width())
        ch = max(1, self.canvas.height())
        px = max(10, min(cw - self.person.width() - 10, cw // 2 - self.person.width() // 2))
        py = max(10, min(ch - self.person.height() - 10, ch // 2 - self.person.height() // 2))
        self.person.move(px, py)
        if randomize_item or not hasattr(self, "_item_offset"):
            pcx = px + self.person.width() / 2
            pcy = py + self.person.height() / 2
            ix, iy = _random_point_around(
                pcx, pcy, 95, 150, cw, ch, self.item.width(), self.item.height()
            )
            self._item_offset = ix - pcx, iy - pcy
        ox, oy = self._item_offset
        pcx = px + self.person.width() / 2
        pcy = py + self.person.height() / 2
        ix = max(0, min(cw - self.item.width(), int(pcx + ox)))
        iy = max(0, min(ch - self.item.height(), int(pcy + oy)))
        self.item.move(ix, iy)

    def _trigger(self):
        if self.triggered:
            return
        self.triggered = True
        self.person.hide()
        self.item.hide()

        final = (
            assets.get_work_final(self.name) if self.kind == "work"
            else assets.get_home_final(self.name)
        )
        big = QLabel(self.canvas)
        if final and os.path.exists(final):
            pix = QPixmap(final).scaled(
                200, 200, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            pix = QPixmap(200, 200)
            pix.fill(Qt.GlobalColor.transparent)
        big.setPixmap(pix)
        big.setFixedSize(pix.size())
        big.move((self.canvas.width() - pix.width()) // 2,
                 (self.canvas.height() - pix.height()) // 2)
        big.show()
        self.ctx.show_scene_image(final, self.kind, self.name)
        self.hint.setText(tr("触发成功捏！"))

        # 台词
        cfg = next((x for x in (
            config.character.work if self.kind == "work" else config.character.home
        ).get("itemList", []) if x["name"] == self.name), {})
        if not (self.kind == "work" and self.name == "歌手"):
            say(pick_line(cfg.get("lines", [])))

        # 音乐触发
        if self.kind == "work" and self.name == "歌手":
            self.ctx.music.start_singer_show()
        elif self.kind == "home" and self.name == "听歌":
            self.ctx.music.play_random(show_player=True)

    def _on_close(self):
        # 听歌 / 歌手 退出时停止音乐
        if (self.kind == "home" and self.name == "听歌") or \
           (self.kind == "work" and self.name == "歌手"):
            self.ctx.music.close_player()
