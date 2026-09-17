"""音乐播放器：QMediaPlayer 后端，支持列表/搜索/上传/循环，以及两种触发模式。

- 歌手（工作）：随机播完整一首，不显示播放器，结束播报后自动关闭隐藏播放器。
- 听歌（居家）：打开播放器随机播放，切换状态则退出播放器。
上传按钮位于播放列表面板的搜索栏旁，用户自选音乐存入 data/music。
"""

import os
import random
import re
import shutil
import threading
import ctypes
from ctypes import wintypes

from PyQt6.QtCore import (
    QAbstractAnimation, QEasingCurve, QPoint, QPointF, QRect, QRectF, QUrl, QTimer, Qt, QSize, QThread, QObject,
    QPropertyAnimation, pyqtSignal, QEventLoop, QEvent,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QLabel, QPushButton, QScrollArea,
    QLineEdit, QHBoxLayout, QVBoxLayout, QFileDialog, QGraphicsDropShadowEffect, QMenu,
    QSizePolicy, QTextEdit, QPlainTextEdit, QComboBox, QAbstractSpinBox,
)
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygon
try:
    from PyQt6.QtSvg import QSvgRenderer
except ImportError:  # pragma: no cover
    QSvgRenderer = None

from app.core import assets, config, covers, lyrics, music_api
from app.core.voice import on_spoken, say
from app.core.i18n import tr
from app.ui.context_menu import MENU_QSS
from app.ui.common import keep_on_top


PLAYER_QSS = """
QWidget#playerCard {
    background: #fffaf5;
    border: 1px solid rgba(255,255,255,0.86);
    border-radius: 20px;
    font-family: 'Microsoft YaHei', 'PingFang SC', 'Segoe UI';
}
QLabel#trackTitle { color: #3d2b1f; font-size: 14px; font-weight: 800; }
QLabel#artist { color: #a08e7a; font-size: 11px; font-weight: 500; }
QLabel#lyricText { color: #f97510; font-size: 11px; font-weight: 500; }
QLabel#timeText, QLabel#durationText {
    color: #a08e7a;
    font-family: Consolas, 'Cascadia Code', monospace;
    font-size: 11px;
    font-weight: 700;
}
QPushButton#toolBtn {
    background: transparent;
    border: none;
    color: #6b5744;
    border-radius: 13px;
}
QPushButton#toolBtn:hover { background: rgba(249,117,16,0.10); color: #f97510; }
QPushButton#windowBtn, QPushButton#windowBtnClose {
    background: transparent;
    border: none;
    color: #a08e7a;
    border-radius: 8px;
}
QPushButton#windowBtn:hover { background: rgba(249,117,16,0.08); color: #f97510; }
QPushButton#windowBtnClose:hover { background: rgba(229,57,53,0.07); color: #e53935; }
QPushButton#playBtn {
    background: #f97510;
    border: none;
    border-radius: 25px;
    color: #fff;
}
QPushButton#playBtn:hover { background: #ffa940; }
QWidget#playlistPanel { border-top: 1px solid rgba(249,117,16,0.12); background: transparent; }
QLineEdit#searchInput {
    background: rgba(249,117,16,0.04);
    border: 1.5px solid rgba(249,117,16,0.12);
    border-radius: 8px;
    color: #3d2b1f;
    font-size: 12px;
    padding: 0 11px;
}
QLineEdit#searchInput:focus { background: #fff; border-color: #f97510; }
QLineEdit#searchInput::placeholder { color: rgba(160,142,122,0.35); }
QPushButton#uploadBtn {
    background: rgba(255,255,255,0.50);
    border: 1.5px solid rgba(249,117,16,0.12);
    border-radius: 8px;
    color: #6b5744;
    font-size: 15px;
}
QPushButton#uploadBtn:hover { background: rgba(249,117,16,0.10); border-color: rgba(249,117,16,0.25); color: #f97510; }
QScrollArea#playlist {
    background: transparent;
    border: none;
    outline: 0;
}
QWidget#playlistBody { background: transparent; }
QWidget#trackRow { background: transparent; border-radius: 8px; }
QWidget#trackRow:hover { background: rgba(249,117,16,0.10); }
QWidget#trackRow[playing="true"] { background: rgba(249,117,16,0.10); }
QLabel#trackNum { color: #a08e7a; font-family: Consolas, 'Cascadia Code', monospace; font-size: 12px; font-weight: 700; }
QLabel#trackName { color: #3d2b1f; font-size: 13px; font-weight: 500; }
QLabel#trackDuration { color: #000000; font-family: Consolas, 'Cascadia Code', monospace; font-size: 12px; font-weight: 600; }
QWidget#trackRow[playing="true"] QLabel#trackNum,
QWidget#trackRow[playing="true"] QLabel#trackName { color: #f97510; }
QScrollBar:vertical { width: 4px; background: transparent; margin: 4px 0; }
QScrollBar::handle:vertical { background: rgba(160,142,122,0.42); border-radius: 2px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

PLAYER_W = 336
PLAYER_H = 258
PLAYER_EXPANDED_H = 526
PLAYLIST_VISIBLE_ROWS = 5
TRACK_ROW_H = 36
REMOTE_PAGE_SIZE = 30
DEFAULT_MUSIC_VOLUME = 50
LYRIC_MARK = "♪  "

SEARCH_SVG = """<svg viewBox='0 0 1024 1024' xmlns='http://www.w3.org/2000/svg'>
<path d='M839.566222 774.826667l170.894222 170.922666a45.539556 45.539556 0 0 1 0 64.796445 46.136889 46.136889 0 0 1-32.398222 13.454222 46.136889 46.136889 0 0 1-32.398222-13.454222L774.826667 839.68a473.713778 473.713778 0 0 1-636.017778-30.833778A473.827556 473.827556 0 0 1 473.770667 0C735.402667 0 947.484444 212.110222 947.484444 473.799111c0 112.213333-39.594667 217.941333-107.946666 301.056zM473.770667 91.733333c-210.887111 0.341333-381.724444 171.207111-382.065778 382.094223 0 211.000889 171.064889 382.094222 382.065778 382.094222s382.037333-171.093333 382.037333-382.094222c0-211.029333-171.036444-382.094222-382.037333-382.094223z' fill='#606060'/>
</svg>"""

UPLOAD_SVG = """<svg viewBox='0 0 1024 1024' xmlns='http://www.w3.org/2000/svg'>
<path d='M924.444444 1024h-796.444444C73.016889 1024 28.444444 978.147556 28.444444 921.6v-117.020444c0-24.234667 19.114667-43.889778 42.666667-43.889778s42.666667 19.626667 42.666667 43.889778V921.6c0 8.078222 6.371556 14.620444 14.222222 14.620444h796.444444c7.850667 0 14.222222-6.542222 14.222223-14.620444v-117.020444c0-24.234667 19.114667-43.889778 42.666666-43.889778s42.666667 19.626667 42.666667 43.889778V921.6c0 56.547556-44.572444 102.4-99.555556 102.4z m-398.222222-948.821333c11.406222 0 22.357333 4.721778 30.378667 13.084444 8.021333 8.334222 12.430222 19.655111 12.288 31.402667v585.130666c0 24.234667-19.114667 43.889778-42.666667 43.889778s-42.666667-19.626667-42.666666-43.889778V119.665778c-0.142222-11.747556 4.266667-23.04 12.288-31.402667a42.097778 42.097778 0 0 1 30.378666-13.084444zM526.222222 0a42.382222 42.382222 0 0 1 30.151111 12.885333l284.444445 292.551111c8.049778 8.192 12.600889 19.342222 12.600889 31.004445 0 11.662222-4.551111 22.840889-12.600889 31.004444a42.097778 42.097778 0 0 1-60.302222 0l-284.444445-292.551111a44.231111 44.231111 0 0 1-12.600889-31.004444c0-11.662222 4.551111-22.812444 12.600889-31.004445A42.382222 42.382222 0 0 1 526.222222 0z m0 0a42.382222 42.382222 0 0 1 30.151111 12.885333c8.049778 8.192 12.600889 19.342222 12.600889 31.004445 0 11.662222-4.551111 22.812444-12.600889 31.004444l-284.444444 292.579556a42.097778 42.097778 0 0 1-60.302222 0 44.231111 44.231111 0 0 1-12.600889-31.004445c0-11.662222 4.551111-22.840889 12.600889-31.004444l284.444444-292.579556A42.382222 42.382222 0 0 1 526.222222 0z' fill='#606060'/>
</svg>"""


def _default_lyric() -> str:
    return tr("把这一句留在今天")


def _marked_lyric(text: str) -> str:
    text = (text or _default_lyric()).strip()
    return LYRIC_MARK + text.lstrip("♪ ")


def _split_track_artist(path: str) -> tuple[str, str]:
    cached = music_api.cache_info(path) if path else None
    if cached:
        title = (cached.get("name") or "").strip()
        artist = (cached.get("artist") or "").strip()
        if title:
            return title, artist
    stem = os.path.splitext(os.path.basename(path))[0].strip()
    stem = re.sub(r"\s*\[\d+\]$", "", stem)
    stem = " ".join(stem.split())
    for sep in (" - ", "－", "—", "–", "-"):
        if sep in stem:
            title, artist = stem.rsplit(sep, 1)
            title = " ".join(title.split()).strip()
            artist = " ".join(artist.split()).strip()
            if title and artist:
                return title, artist
    return stem, ""


def _track_title(path: str) -> str:
    return _split_track_artist(path)[0]


def _track_artist(path: str) -> str:
    return _split_track_artist(path)[1] or tr("用户音乐")


def _track_search_text(path: str) -> str:
    title, artist = _split_track_artist(path)
    cached = music_api.cache_info(path) if path else None
    album = cached.get("album", "") if cached else ""
    return f"{title} {artist} {album}".lower()


def _dedupe_text(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").lower())


def _track_dedupe_key(path: str) -> tuple[str, str]:
    title, artist = _split_track_artist(path)
    return _dedupe_text(title), _dedupe_text(artist)


def _remote_dedupe_key(item: dict) -> tuple[str, str]:
    return _dedupe_text(item.get("name", "")), _dedupe_text(item.get("artist", ""))


def _track_display_title(path: str) -> str:
    title, artist = _split_track_artist(path)
    label = title if not artist else f"{title} - {artist}"
    return f"{label} · 缓存" if music_api.is_cache_path(path) else label


def _remote_display_title(item: dict) -> str:
    title = item.get("name") or tr("未知歌曲")
    artist = item.get("artist") or tr("未知歌手")
    return f"{title} - {artist} · 在线"


def _duration_from_seconds(seconds: int | None) -> str:
    try:
        seconds = int(seconds or 0)
    except (TypeError, ValueError):
        seconds = 0
    return f"{seconds // 60:02d}:{seconds % 60:02d}" if seconds > 0 else "--:--"


def _track_lrclib_info(path: str) -> tuple[str, str | None]:
    title, artist = _split_track_artist(path)
    return title, artist or None


def _album_art_for(path: str) -> str or None:
    if not path:
        return assets.find_image("default_album")
    title, artist = _split_track_artist(path)
    cached = covers.existing_cover(title, artist or None)
    if cached:
        return cached
    folder = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    for name in (stem, "cover", "folder", "album"):
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            candidate = os.path.join(folder, name + ext)
            if os.path.exists(candidate):
                return candidate
    return assets.find_image("default_album")


def _parse_duration(path: str) -> str:
    try:
        if not os.path.exists(path):
            return "--:--"
        probe = QMediaPlayer()
        loop = QEventLoop()
        state = {"ms": 0}

        def on_dur(ms):
            state["ms"] = ms
            if ms > 0:
                loop.quit()

        probe.durationChanged.connect(on_dur)
        probe.setSource(QUrl.fromLocalFile(path))
        QTimer.singleShot(500, loop.quit)
        loop.exec()
        ms = state["ms"] or probe.duration()
        if ms > 0:
            s = ms // 1000
            return f"{s // 60:02d}:{s % 60:02d}"
    except Exception:  # noqa: BLE001
        pass
    return "--:--"


class CoverWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(54, 54)
        self._pixmap = QPixmap()
        self._path = None
        self._preview = None
        self.set_album_art(None)

    def set_album_art(self, path):
        self._path = path
        pix = QPixmap(path or "")
        if pix.isNull():
            pix = QPixmap(assets.find_image("default_album") or "")
        self._pixmap = pix
        self.update()

    def _preview_pos(self):
        return self.mapToGlobal(QPoint(-248, -244))

    def _source_rect(self):
        return QRect(self.mapToGlobal(QPoint(0, 0)), self.size())

    def sync_preview_position(self):
        if self._preview and self._preview.isVisible() and not self._preview.is_closing():
            self._preview.move_to_anchor(self._preview_pos(), self._source_rect())

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(0, 0, self.width(), self.height())
        if not self._pixmap.isNull():
            clip = QPainterPath()
            clip.addRoundedRect(r, 14, 14)
            p.setClipPath(clip)
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap((self.width() - scaled.width()) // 2,
                         (self.height() - scaled.height()) // 2,
                         scaled)
            p.setClipping(False)
            p.setPen(QPen(QColor(255, 255, 255, 180), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
            return
        grad_color = QColor("#f97510")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad_color)
        p.drawRoundedRect(r, 14, 14)

        p.setPen(QPen(QColor("#ffffff"), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(31, 16, 31, 35)
        p.drawLine(31, 16, 40, 19)
        p.drawLine(40, 19, 40, 25)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(20, 32, 12, 9))
        p.drawEllipse(QRectF(29, 38, 12, 9))

    def enterEvent(self, e):  # noqa: N802
        if self._path and os.path.exists(self._path):
            if self._preview is None:
                self._preview = CoverPreviewWindow()
            self._preview.show_cover(self._path, self._preview_pos(), self._source_rect())
            keep_on_top(self.window(), bring_to_front=True)
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        if self._preview:
            self._preview.hide_animated()
        super().leaveEvent(e)


class CoverPreviewWindow(QDialog):
    PREVIEW_SIZE = QSize(352, 358)

    def __init__(self):
        super().__init__()
        self._pixmap = QPixmap()
        self._carrot = QPixmap(assets.find_image("carrot_hover") or "")
        self._path = None
        self._shadow = QColor("#f97510")
        self._full_geometry = QRect()
        self._collapsed_geometry = QRect()
        self._closing = False
        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_animation_finished)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        if hasattr(Qt.WindowType, "WindowTransparentForInput"):
            self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.resize(self.PREVIEW_SIZE)

    def target_size(self):
        return QSize(self.PREVIEW_SIZE)

    def is_closing(self):
        return self._closing

    def show_cover(self, path, pos, source_rect=None):
        full_geometry = QRect(pos, self.PREVIEW_SIZE)
        if self.isVisible() and not self._closing and self._path == path and self._full_geometry == full_geometry:
            return
        pix = QPixmap(path)
        if pix.isNull():
            return
        self._closing = False
        self._anim.stop()
        self._fade.stop()
        self._path = path
        self._pixmap = pix
        self._shadow = _pixmap_theme_color(pix)
        self._full_geometry = full_geometry
        if source_rect is None:
            source_rect = QRect(pos.x() + 214, pos.y() + 240, 54, 54)
        self._collapsed_geometry = QRect(source_rect)
        self.setGeometry(self._collapsed_geometry)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._anim.setStartValue(self._collapsed_geometry)
        self._anim.setEndValue(self._full_geometry)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._anim.start()
        self._fade.start()
        self.update()

    def move_to_anchor(self, pos, source_rect=None):
        full_geometry = QRect(pos, self.PREVIEW_SIZE)
        if self._full_geometry == full_geometry:
            return
        self._full_geometry = full_geometry
        if source_rect is not None:
            self._collapsed_geometry = QRect(source_rect)
        if self._anim.state() == QAbstractAnimation.State.Running:
            self._anim.stop()
            self._fade.stop()
            self.setWindowOpacity(1.0)
        self.setGeometry(self._full_geometry)
        self.update()

    def hide_animated(self):
        if not self.isVisible():
            return
        self._closing = True
        self._anim.stop()
        self._fade.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(self._collapsed_geometry if not self._collapsed_geometry.isNull() else self.geometry())
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._anim.start()
        self._fade.start()

    def _on_animation_finished(self):
        if self._closing:
            self.hide()
            self._closing = False

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self._pixmap.isNull():
            return
        p.setPen(Qt.PenStyle.NoPen)

        blob = QPainterPath()
        blob.moveTo(43, 88)
        blob.cubicTo(28, 48, 73, 38, 113, 55)
        blob.cubicTo(151, 31, 205, 42, 224, 77)
        blob.cubicTo(273, 80, 287, 135, 244, 164)
        blob.cubicTo(256, 207, 208, 239, 169, 216)
        blob.cubicTo(129, 239, 81, 223, 80, 181)
        blob.cubicTo(34, 174, 16, 119, 43, 88)
        blob_grad = QLinearGradient(QPointF(28, 52), QPointF(256, 218))
        blob_grad.setColorAt(0.00, QColor(255, 170, 64, 130))
        blob_grad.setColorAt(0.36, QColor(255, 224, 142, 118))
        blob_grad.setColorAt(0.70, QColor(176, 231, 103, 124))
        blob_grad.setColorAt(1.00, QColor(249, 117, 16, 112))
        p.setBrush(blob_grad)
        p.drawPath(blob)

        glow = QColor(self._shadow)
        glow.setAlpha(38)
        p.setBrush(glow)
        p.drawEllipse(QRectF(46, 198, 126, 20))

        p.setPen(QPen(QColor(255, 255, 255, 178), 4.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(34, 62, 92, 42), 150 * 16, 74 * 16)
        p.drawArc(QRectF(141, 47, 76, 34), 36 * 16, 72 * 16)
        p.drawArc(QRectF(123, 225, 54, 110), 86 * 16, 72 * 16)
        p.drawArc(QRectF(92, 250, 58, 74), 112 * 16, 50 * 16)

        r = QRectF(64, 72, 148, 148)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(70, 52, 36, 54))
        p.drawRoundedRect(r.translated(0, 8), 6, 6)
        clip = QPainterPath()
        clip.addRoundedRect(r, 6, 6)
        p.setClipPath(clip)
        scaled = self._pixmap.scaled(
            int(r.width()), int(r.height()),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        p.drawPixmap(int(r.x() + (r.width() - scaled.width()) / 2),
                     int(r.y() + (r.height() - scaled.height()) / 2), scaled)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 185), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)

        if not self._carrot.isNull():
            p.save()
            p.translate(234, 210)
            p.rotate(-4)
            carrot = self._carrot.scaled(
                QSize(138, 102),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(-carrot.width() // 2, -carrot.height() // 2, carrot)
            p.restore()


def _pixmap_theme_color(pixmap: QPixmap) -> QColor:
    img = pixmap.toImage().scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
    totals = [0, 0, 0]
    count = 0
    for x in range(img.width()):
        for y in range(img.height()):
            c = QColor(img.pixel(x, y))
            if c.alpha() < 16:
                continue
            totals[0] += c.red()
            totals[1] += c.green()
            totals[2] += c.blue()
            count += 1
    if not count:
        return QColor("#f97510")
    color = QColor(totals[0] // count, totals[1] // count, totals[2] // count)
    h, s, v, a = color.getHsv()
    return QColor.fromHsv(h if h >= 0 else 28, max(130, s), min(255, max(170, v)), 255)


class SvgIconWidget(QWidget):
    def __init__(self, svg_text: str, color="#6b5744"):
        super().__init__()
        self._svg_text = svg_text
        self._color = color
        self.setFixedSize(22, 22)

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if QSvgRenderer is not None:
            svg = self._svg_text.replace("#606060", self._color).encode("utf-8")
            renderer = QSvgRenderer(svg)
            renderer.render(p, QRectF(0, 0, self.width(), self.height()))
            return
        p.setPen(QPen(QColor(self._color), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        c = self.rect().center()
        p.drawEllipse(c, 5, 5)


LOOP_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1024 1024'>
<path d='M798.647 767.059l-133.918-86.627c-7.937-5.14-16.02-7.755-24.045-7.755-17.984 0-36.196 14.7-36.196 42.768v38.652H392.366c-126.614 0-229.622-107.581-229.622-239.798 0-47.784 13.597-93.995 39.324-133.676 15.496-23.904 9.521-56.382-13.36-72.565-22.879-16.15-53.996-9.912-69.477 13.963C82.24 379.05 62.68 445.552 62.68 514.299c0 189.857 147.903 344.287 329.686 344.287h212.122v38.924c0 29.189 18.522 42.489 35.733 42.489 8.205 0 16.452-2.773 24.535-8.224l134.562-90.737c13.437-9.063 21.072-22.645 20.938-37.223-0.147-14.577-8.021-27.973-21.609-36.756zM631.646 165.405H419.529V126.486C419.529 97.3 401.003 84 383.791 84c-8.203 0-16.45 2.769-24.535 8.222l-134.56 90.74c-13.439 9.063-21.075 22.643-20.94 37.223 0.15 14.578 8.025 27.97 21.614 36.754l133.918 86.626c7.933 5.14 16.018 7.755 24.041 7.755 17.989 0 36.2-14.702 36.2-42.768V269.895h212.117c126.616 0 229.612 107.581 229.612 239.798 0 47.812-13.6 94.022-39.312 133.672-15.496 23.908-9.493 56.386 13.373 72.569 8.598 6.063 18.37 8.977 28.004 8.977 16.054 0 31.8-8.046 41.486-22.945 36.968-56.998 56.511-123.498 56.511-192.273 0-189.856-147.89-344.288-329.674-344.288z' fill='#606060'/>
<path d='M577.004 346.238v331.525h-54.321V411.694c-19.974 18.096-45.062 31.563-75.686 40.401v-53.867c14.859-3.723 30.624-10.23 47.361-19.488 16.704-10.23 30.624-20.912 41.793-32.502h40.853z' fill='#606060'/>
</svg>"""

SHUFFLE_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1024 1024'>
<path d='M753.564731 337.471035c-45.8697 0-160.259984 113.849978-243.789399 194.548928C383.134027 654.383848 263.508509 773.284865 167.764911 773.284865l-58.892295 0c-24.068162 0-43.581588-19.526729-43.581588-43.581588s19.513426-43.581588 43.581588-43.581588l58.892295 0c60.504002 0 183.002964-121.68134 281.432741-216.784348 119.79641-115.744117 223.254713-219.029482 304.368102-219.029482l56.209186 0-59.641355-57.828057c-17.033955-16.993023-17.060561-42.902112-0.057305-59.927881 17.002232-17.030885 44.596707-17.064654 61.631686-0.065492l134.207631 133.874033c8.192589 8.172123 12.794397 19.238157 12.794397 30.803563 0 11.564383-4.601808 22.604834-12.794397 30.776957L811.706943 461.72599c-8.505721 8.486278-19.646456 12.522198-30.78719 12.522198-11.166317 0-22.333658-4.676509-30.844495-13.199627-17.003256-17.025769-16.975627-45.432749 0.057305-62.425771l59.641355-61.151755L753.564731 337.471035zM811.706943 561.66105c-17.034978-16.999163-44.629453-16.972557-61.631686 0.058328-17.003256 17.024745-16.975627 46.257533 0.057305 63.250556l59.641355 61.150732-56.209186 0c-35.793204 0-95.590102-52.946886-154.87637-108.373243-17.576307-16.435321-45.161572-16.3422-61.594847 1.226944-16.444531 17.568121-15.523555 46.393633 2.053776 62.823837 90.322122 84.458577 151.246703 131.484613 214.417441 131.484613l56.209186 0-59.641355 57.824987c-17.033955 16.993023-17.060561 43.736107-0.057305 60.761875 8.511861 8.523117 19.678178 12.369725 30.844495 12.369725 11.140735 0 22.281469-4.453429 30.78719-12.939707L945.914574 757.311055c8.192589-8.173147 12.794397-19.315928 12.794397-30.881334 0-11.564383-4.601808-22.682605-12.794397-30.855752L811.706943 561.66105z' fill='#606060'/>
</svg>"""

VOL_1_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1024 1024'><path d='M594.089623 68.470441c-15.912411-6.580882-33.207309-2.719948-45.369304 9.460466L339.53095 288.667515 235.458663 288.667515c-23.49511 0-42.538839 18.643616-42.538839 42.142819L192.919824 693.241854c0 23.49818 19.043728 42.142819 42.538839 42.142819l104.072287 0 210.193233 210.736609c8.143471 8.154727 19.033495 12.588713 30.116925 12.588713 5.473665 0 8.993838-1.00284 14.249539-3.179412 15.908318-6.585999 24.273846-22.056342 24.273846-39.269375L618.364493 107.790982C618.36347 90.577948 609.997941 75.05644 594.089623 68.470441zM533.275559 813.425074 385.275807 662.97962c-7.982812-7.994068-16.805758-12.684904-28.102035-12.684904l-79.165014 0 0-276.538267 79.165014 0c11.295254 0 20.119223-4.690836 28.102035-12.684904l147.999752-150.445454L533.275559 813.425074zM759.790526 692.192965c-8.403391 9.379625-20.026102 14.153348-31.702026 14.153348-10.111289 0-20.2543-3.583618-28.377304-10.860349-17.501606-15.687284-18.972097-42.587957-3.292999-60.086493 109.297288-121.970936 4.517897-241.702877 0-246.741637-15.679098-17.499559-14.208607-44.400233 3.292999-60.081377 17.48728-15.691377 44.404326-14.21577 60.074214 3.287883C815.626205 394.174478 887.488907 549.679158 759.790526 692.192965z' fill='#606060'/></svg>"""
VOL_2_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1024 1024'><path d='M508.068458 68.448952c-15.960507-6.565533-33.750685-2.663666-45.892213 9.56382l-208.498638 210.654744L150.309354 288.667515c-23.503297 0-42.402739 18.642592-42.402739 42.141796L107.906615 693.241854c0 23.49818 18.899442 42.141796 42.402739 42.141796l103.369276 0 209.027687 210.654744c8.151657 8.206916 19.082614 12.671601 30.211069 12.671601 5.455245 0 9.903557-0.997724 15.151072-3.158946 15.939017-6.569626 25.281803-22.049179 25.281803-39.289841L533.350261 107.788935C533.351284 90.549296 524.007475 75.018577 508.068458 68.448952zM448.26235 813.019845 300.55424 663.061484c-7.990998-8.045233-17.817808-12.767791-29.15911-12.767791l-78.399581 0L192.995549 373.755426l78.399581 0c11.341303 0 21.168112-4.722558 29.15911-12.767791L448.26235 211.029274 448.26235 813.019845zM672.196539 692.103938c-8.410554 9.432837-20.074198 14.242376-31.79003 14.242376-10.07445 0-20.189831-3.553942-28.299533-10.783601-17.550725-15.639189-19.098987-42.534745-3.460822-60.07626 105.97666-118.880551 11.050684-234.291071-0.124843-247.058862-15.425318-17.629519-13.767562-44.48312 3.792373-59.987233 17.58654-15.510252 44.295855-13.963013 59.881832 3.505847C727.72011 394.229736 799.178605 549.661761 672.196539 692.103938zM800.394293 805.935496c-8.4126 9.431813-20.075221 14.242376-31.791054 14.242376-10.07445 0-20.189831-3.553942-28.299533-10.783601-17.550725-15.639189-19.097964-42.534745-3.459798-60.07626 208.05043-233.387491 8.526187-464.919728-0.067538-474.664673-15.523555-17.59268-13.912871-44.467771 3.641947-60.030212 17.567098-15.551184 44.3593-14.023388 59.977 3.490497C803.01191 221.048465 1059.402301 515.38612 800.394293 805.935496z' fill='#606060'/></svg>"""
VOL_3_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1024 1024'><path d='M431.207929 106.919125c-14.536065-5.991458-30.570249-2.454912-41.684378 8.683776L198.703551 308.032562l-94.77862 0c-21.468964 0-38.633902 17.024745-38.633902 38.486546l0 331.002716c0 21.460778 17.164938 38.485523 38.633902 38.485523l94.77862 0 191.521988 192.429661c7.446599 7.467065 17.411555 11.530614 27.557636 11.530614 4.992711 0 8.626471-0.915859 13.424754-2.89391 14.545274-6.005784 22.63144-20.143783 22.63144-35.874045L453.839369 142.839219C453.838346 127.108956 445.753203 112.924909 431.207929 106.919125zM376.128473 787.108708 241.016239 649.917116c-7.299243-7.320733-15.827477-11.618619-26.163893-11.618619l-71.852468 0L142.999878 385.742435l71.852468 0c10.336416 0 18.86465-4.297886 26.163893-11.618619l135.112234-137.191592L376.128473 787.108708zM581.9 676.526147c-7.67889 8.590656-18.318204 12.96529-29.000498 12.96529-9.221012 0-18.47477-3.25923-25.891693-9.886161-16.011672-14.302751-17.388019-38.870286-3.080152-54.870702 97.04729-108.533902 10.117428-213.893508-0.113587-225.548966-14.113439-16.081257-12.632715-40.605813 3.388167-54.78986 16.020882-14.189164 40.431851-12.817933 54.697763 3.1262C632.777761 404.416749 698.252984 546.403554 581.9 676.526147zM699.338712 780.485871c-7.677866 8.591679-18.318204 12.96529-29.000498 12.96529-9.219989 0-18.478863-3.25923-25.891693-9.885138-16.010649-14.302751-17.388019-38.871309-3.079128-54.871725 191.540408-214.210733 7.91118-424.49811 0-433.345616-14.307867-16.000416-12.93152-40.568974 3.079128-54.871725 15.997346-14.302751 40.575114-12.927427 54.892191 3.079128C701.739389 246.240217 936.651606 515.090385 699.338712 780.485871zM821.955354 858.351286c-7.67889 8.590656-18.318204 12.96529-29.000498 12.96529-9.221012 0-18.47477-3.25923-25.891693-9.886161-16.011672-14.302751-17.388019-38.870286-3.080152-54.870702 109.224634-122.153084 142.595672-257.939677 99.177813-403.597081-32.952506-110.559025-98.518804-184.728258-99.177813-185.468109-14.307867-16.000416-12.93152-40.564881 3.080152-54.871725 15.992229-14.306844 40.568974-12.930497 54.892191 3.079128C825.049832 169.162748 1128.098893 515.981684 821.955354 858.351286z' fill='#606060'/></svg>"""
MUTE_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1024 1024'><path d='M452.676893 78.69327c-15.654538-6.361895-34.744315-2.402723-46.544059 9.712199L205.211778 293.863864l-98.367355 0c-22.948665 0-41.554418 18.20871-41.554418 41.160445l0 353.999476c0 22.951735 18.605753 41.160445 41.554418 41.160445l98.367355 0L405.009244 935.642626c7.978718 8.198729 18.783809 12.670577 29.786397 12.670577 5.259794 0 12.812817-0.948605 17.881253-3.00852 15.663748-6.367011 28.157293-21.542642 28.157293-38.452777L480.834186 117.196189C480.834186 100.286054 468.340641 85.060281 452.676893 78.69327zM397.72535 804.584732 254.775614 659.84114c-7.822153-8.037047-20.807908-12.765745-32.024367-12.765745l-74.353428 0L148.397818 376.972701l74.353428 0c11.215436 0 24.201192-4.728698 32.024367-12.765745l142.949736-144.743592L397.72535 804.584732zM946.930717 636.423801c16.008602 16.447601 15.653515 42.762943-0.785899 58.774615-8.080026 7.864108-18.540262 11.780301-28.984125 11.780301-10.824533 0-21.635763-4.200672-29.78128-12.567223L767.838829 571.611679 648.299269 694.411493c-8.146541 8.365528-18.960841 12.567223-29.78128 12.567223-10.44898 0-20.904099-3.916193-28.984125-11.780301-16.439414-16.011672-16.795525-42.327014-0.785899-58.774615l121.091916-124.397195L588.746942 387.630435c-16.008602-16.447601-15.653515-42.762943 0.785899-58.774615 16.45988-16.011672 42.761919-15.646352 58.765405 0.785899l119.53956 122.800837 119.540583-122.800837c16.013719-16.45374 42.314735-16.793478 58.765405-0.785899 16.440437 16.011672 16.795525 42.327014 0.785899 58.774615L825.837778 512.026606 946.930717 636.423801z' fill='#606060'/></svg>"""

VOLUME_SVGS = {
    "volume": VOL_2_SVG,
    "volume_1": VOL_1_SVG,
    "volume_2": VOL_2_SVG,
    "volume_3": VOL_3_SVG,
    "muted": MUTE_SVG,
}


class LoopIcon(QWidget):
    def __init__(self, mode=0):
        super().__init__()
        self.mode = mode
        self.setFixedSize(24, 24)

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#f97510") if self.mode else QColor("#6b5744")
        p.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        c = self.rect().center()
        if self.mode == 0:
            p.drawArc(c.x() - 8, c.y() - 8, 11, 11, 45 * 16, 180 * 16)
            p.drawArc(c.x() - 3, c.y() - 3, 11, 11, -135 * 16, 180 * 16)
            p.drawLine(c.x() + 2, c.y() - 8, c.x() + 7, c.y() - 8)
            p.drawLine(c.x() + 7, c.y() - 8, c.x() + 5, c.y() - 10)
            p.drawLine(c.x() + 7, c.y() - 8, c.x() + 5, c.y() - 6)
        elif self.mode == 1:
            p.drawArc(c.x() - 8, c.y() - 8, 11, 11, 45 * 16, 180 * 16)
            p.drawArc(c.x() - 3, c.y() - 3, 11, 11, -135 * 16, 180 * 16)
            p.drawLine(c.x() + 2, c.y() - 8, c.x() + 7, c.y() - 8)
            p.drawLine(c.x() + 7, c.y() - 8, c.x() + 5, c.y() - 10)
            p.drawLine(c.x() + 7, c.y() - 8, c.x() + 5, c.y() - 6)
            p.setPen(QPen(QColor("#f97510"), 1.2))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "1")
        else:
            pts = [QPoint(-7, -3), QPoint(-2, -8), QPoint(7, -1), QPoint(3, 3), QPoint(-2, -2), QPoint(-7, 3)]
            p.drawPolyline(QPolygon([c + pt for pt in pts]))
            p.drawLine(c.x() + 3, c.y() + 3, c.x() + 7, c.y() + 7)
            p.drawLine(c.x() + 7, c.y() + 3, c.x() + 3, c.y() + 7)


class VolumeIcon(QWidget):
    def __init__(self):
        super().__init__()
        self.mode = "volume_3"
        self.setFixedSize(24, 24)

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#f97510") if self.mode == "muted" else QColor("#6b5744")
        if self.mode != "muted":
            color = QColor("#f97510") if self.underMouse() else QColor("#6b5744")
        p.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        c = self.rect().center()
        p.drawPolygon(QPolygon([c + QPoint(-8, -4), c + QPoint(-4, -4), c + QPoint(1, -8), c + QPoint(1, 8), c + QPoint(-4, 4), c + QPoint(-8, 4)]))
        if self.mode == "muted":
            p.drawLine(c.x() + 5, c.y() - 5, c.x() + 12, c.y() + 5)
            p.drawLine(c.x() + 12, c.y() - 5, c.x() + 5, c.y() + 5)
        elif self.mode in {"volume_1", "volume_2", "volume_3"}:
            if self.mode in {"volume_1", "volume_2", "volume_3"}:
                p.drawArc(c.x() + 2, c.y() - 5, 7, 10, -45 * 16, 90 * 16)
            if self.mode in {"volume_2", "volume_3"}:
                p.drawArc(c.x(), c.y() - 8, 12, 16, -42 * 16, 84 * 16)
            if self.mode == "volume_3":
                p.drawArc(c.x() - 2, c.y() - 11, 17, 22, -40 * 16, 80 * 16)


class IconButton(QPushButton):
    def __init__(self, kind, size=38):
        super().__init__()
        self.kind = kind
        if kind in {"back", "min", "close"}:
            self.setObjectName("windowBtnClose" if kind == "close" else "windowBtn")
        else:
            self.setObjectName("playBtn" if kind == "play" else "toolBtn")
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):  # noqa: N802
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        active_kinds = {"loop_one", "shuffle", "muted"}
        plain_overlay = bool(self.property("plainOverlay"))
        if plain_overlay:
            color = QColor("#f97510")
        elif self.kind == "play":
            color = QColor("#ffffff")
        elif self.kind == "close" and self.underMouse():
            color = QColor("#e53935")
        elif self.kind in active_kinds:
            color = QColor("#f97510")
        elif self.underMouse():
            color = QColor("#f97510")
        else:
            color = QColor("#a08e7a" if self.kind in {"back", "min", "close"} else "#6b5744")
        p.setPen(QPen(color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(color)
        c = self.rect().center()
        if self.kind == "play":
            p.drawPolygon(QPolygon([c + QPoint(-4, -10), c + QPoint(-4, 10), c + QPoint(11, 0)]))
        elif self.kind == "pause":
            p.drawRect(c.x() - 6, c.y() - 8, 4, 16)
            p.drawRect(c.x() + 3, c.y() - 8, 4, 16)
        elif self.kind == "prev":
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(c.x() - 8, c.y() - 7, 2, 14)
            p.drawPolygon(QPolygon([c + QPoint(-4, 0), c + QPoint(8, -8), c + QPoint(8, 8)]))
        elif self.kind == "next":
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(QPolygon([c + QPoint(4, 0), c + QPoint(-8, -8), c + QPoint(-8, 8)]))
            p.drawRect(c.x() + 6, c.y() - 7, 2, 14)
        elif self.kind == "list":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(color, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            for y in (-6, 0, 6):
                p.drawPoint(c.x() - 8, c.y() + y)
                p.drawLine(c.x() - 3, c.y() + y, c.x() + 9, c.y() + y)
        elif self.kind == "loop":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(color, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawLine(c.x() - 8, c.y() - 5, c.x() + 7, c.y() - 5)
            p.drawLine(c.x() + 7, c.y() - 5, c.x() + 3, c.y() - 9)
            p.drawLine(c.x() + 7, c.y() - 5, c.x() + 3, c.y() - 1)
            p.drawLine(c.x() + 8, c.y() + 5, c.x() - 7, c.y() + 5)
            p.drawLine(c.x() - 7, c.y() + 5, c.x() - 3, c.y() + 1)
            p.drawLine(c.x() - 7, c.y() + 5, c.x() - 3, c.y() + 9)
        elif self.kind == "loop_one":
            self._paint_svg(p, LOOP_SVG, color)
        elif self.kind == "shuffle":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawLine(c.x() - 8, c.y() - 6, c.x() - 3, c.y() - 6)
            p.drawLine(c.x() - 3, c.y() - 6, c.x() + 7, c.y() + 5)
            p.drawLine(c.x() + 7, c.y() + 5, c.x() + 3, c.y() + 1)
            p.drawLine(c.x() + 7, c.y() + 5, c.x() + 3, c.y() + 9)
            p.drawLine(c.x() - 8, c.y() + 6, c.x() - 3, c.y() + 6)
            p.drawLine(c.x() - 3, c.y() + 6, c.x() + 7, c.y() - 5)
            p.drawLine(c.x() + 7, c.y() - 5, c.x() + 3, c.y() - 9)
            p.drawLine(c.x() + 7, c.y() - 5, c.x() + 3, c.y() - 1)
        elif self.kind in {"volume", "volume_1", "volume_2", "volume_3", "muted"}:
            self._paint_svg(p, VOLUME_SVGS[self.kind], color, pad=1)
        elif self.kind == "upload":
            self._paint_svg(p, UPLOAD_SVG, color, pad=9)
        elif self.kind == "search":
            self._paint_svg(p, SEARCH_SVG, color, pad=9)
        elif self.kind == "back":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(c.x() - 6, c.y() + 2, c.x() + 6, c.y() + 2)
        elif self.kind == "min":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(c.x() - 5, c.y() + 2, c.x() + 5, c.y() + 2)
        elif self.kind == "close":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(c.x() - 4, c.y() - 4, c.x() + 4, c.y() + 4)
            p.drawLine(c.x() + 4, c.y() - 4, c.x() - 4, c.y() + 4)
        elif self.kind == "palette":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawEllipse(QRectF(c.x() - 8, c.y() - 7, 16, 14))
            p.setBrush(color)
            for dx, dy in ((-4, -2), (0, -4), (4, -1), (-1, 3)):
                p.drawEllipse(QRectF(c.x() + dx - 1.2, c.y() + dy - 1.2, 2.4, 2.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(c.x() + 1, c.y() + 2, 7, 6, 210 * 16, 115 * 16)

    def _paint_svg(self, painter, svg_text, color, pad=2):
        if QSvgRenderer is None:
            return
        painter.save()
        svg = svg_text.replace("#606060", color.name()).encode("utf-8")
        renderer = QSvgRenderer(svg)
        renderer.render(painter, QRectF(pad, pad, self.width() - pad * 2, self.height() - pad * 2))
        painter.restore()


class SlimSlider(QWidget):
    valueChanged = pyqtSignal(int)
    sliderReleased = pyqtSignal()
    clicked = pyqtSignal(int)

    def __init__(self, fill="#f97510", track=None):
        super().__init__()
        self._min = 0
        self._max = 100
        self._value = 0
        self._fill = QColor(fill)
        self._track = track or QColor(249, 117, 16, 26)
        self._dragging = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(16)

    def setRange(self, min_v, max_v):  # noqa: N802
        self._min = min_v
        self._max = max_v
        self._value = max(self._min, min(self._max, self._value))
        self.update()

    def setValue(self, value):  # noqa: N802
        value = max(self._min, min(self._max, int(value)))
        if value != self._value:
            self._value = value
            self.update()

    def value(self):
        return self._value

    def _ratio(self):
        span = max(1, self._max - self._min)
        return (self._value - self._min) / span

    def _set_from_x(self, x):
        usable = max(1, self.width() - 12)
        ratio = max(0.0, min(1.0, (x - 6) / usable))
        value = int(self._min + ratio * (self._max - self._min))
        if value != self._value:
            self._value = value
            self.valueChanged.emit(value)
            self.update()

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._set_from_x(e.position().x())
            self.clicked.emit(self._value)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._dragging:
            self._set_from_x(e.position().x())
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self._dragging:
            self._dragging = False
            self.sliderReleased.emit()
            self.update()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def enterEvent(self, e):  # noqa: N802
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = self.height() / 2 - 2.5
        track = QRectF(6, y, max(1, self.width() - 12), 5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._track)
        p.drawRoundedRect(track, 2.5, 2.5)
        fill = QRectF(track.left(), track.top(), track.width() * self._ratio(), track.height())
        p.setBrush(self._fill)
        p.drawRoundedRect(fill, 2.5, 2.5)
        if self.underMouse() or self._dragging:
            cx = track.left() + track.width() * self._ratio()
            p.setBrush(QColor("#ffffff"))
            p.setPen(QPen(self._fill, 2))
            p.drawEllipse(QPointF(cx, self.height() / 2), 5.5, 5.5)


class TrackItemWidget(QWidget):
    clicked = pyqtSignal(object)
    deleteRequested = pyqtSignal(int)
    downloadRequested = pyqtSignal(object, str)
    addRemoteRequested = pyqtSignal(object)
    saveAsRequested = pyqtSignal(int)

    def __init__(self, number, title, duration, index, playing=False, source="local", payload=None):
        super().__init__()
        self.index = index
        self.source = source
        self.payload = payload
        self.setObjectName("trackRow")
        self.setProperty("playing", "true" if playing else "false")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(TRACK_ROW_H)
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 0, 4, 0)
        row.setSpacing(7)

        num = QLabel(number)
        num.setObjectName("trackNum")
        num.setFixedWidth(16)
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label = MarqueeLabel(title)
        name = self.name_label
        name.setObjectName("trackName")
        name.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        name.setMinimumWidth(0)
        name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        duration_l = QLabel(duration)
        duration_l.setObjectName("trackDuration")
        duration_l.setFixedWidth(50)
        duration_l.setMinimumWidth(50)
        duration_l.setMaximumWidth(50)
        duration_l.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        duration_l.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        row.addWidget(num)
        row.addWidget(name, 1)
        row.addWidget(duration_l)

    def sizeHint(self):  # noqa: N802
        return QSize(0, TRACK_ROW_H)

    def minimumSizeHint(self):  # noqa: N802
        return QSize(0, TRACK_ROW_H)

    def enterEvent(self, e):  # noqa: N802
        self.name_label.start_marquee()
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self.name_label.stop_marquee()
        super().leaveEvent(e)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.payload if self.source == "remote" else self.index)
            e.accept()
            return
        super().mousePressEvent(e)

    def _add_download_menu(self, menu, payload):
        download_menu = menu.addMenu(tr("下载"))
        download_menu.setStyleSheet(menu.styleSheet())
        download_menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        download_menu.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        for br in music_api.quality_options(payload):
            action = download_menu.addAction(br)
            action.setData(("download", payload, br))
        return download_menu

    def contextMenuEvent(self, e):  # noqa: N802
        if self.source == "status":
            e.accept()
            return
        player_window = self.window()
        ctx = getattr(getattr(player_window, "music", None), "ctx", None)
        if ctx is not None and hasattr(ctx, "begin_popup_menu"):
            ctx.begin_popup_menu()
        menu = QMenu()
        try:
            menu.setStyleSheet(MENU_QSS + """
QMenu { min-width: 82px; padding: 5px; }
QMenu::item {
    min-width: 56px;
    padding: 7px 12px;
    font-size: 13px;
}
""")
            menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
            menu.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            delete = None
            save_as = None
            add_remote = None
            if self.source == "remote":
                self._add_download_menu(menu, self.payload or {})
                add_remote = menu.addAction(tr("添加到播放列表"))
            elif self.source == "cache":
                self._add_download_menu(menu, self.payload or {})
                delete = menu.addAction(tr("移除缓存"))
            else:
                save_as = menu.addAction(tr("另存为"))
                delete = menu.addAction(tr("删除"))
            action = menu.exec(e.globalPos())
            data = action.data() if action is not None else None
            if isinstance(data, tuple) and data[0] == "download":
                self.downloadRequested.emit(data[1], data[2])
            elif action == add_remote:
                self.addRemoteRequested.emit(self.payload or {})
            elif action == save_as:
                self.saveAsRequested.emit(self.index)
            elif action == delete:
                index = self.index
                QTimer.singleShot(80, lambda: self.deleteRequested.emit(index))
        finally:
            menu.deleteLater()
            if ctx is not None and hasattr(ctx, "end_popup_menu"):
                QTimer.singleShot(120, ctx.end_popup_menu)
        e.accept()


class PlayerCard(QWidget):
    def __init__(self):
        super().__init__()
        self.expanded = False
        self.bubu = QPixmap(assets.find_image("bubu_cutout") or "")

    def set_expanded(self, expanded):
        self.expanded = expanded
        self.update()

    def paintEvent(self, e):  # noqa: N802
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 20, 20)
        p.setClipPath(clip)
        p.setOpacity(0.70)
        if self.expanded:
            self._paint_bubu_peek(p, mouth_pos=QPointF(self.width() - 18, self.height() - 28), scale=1.14)
        else:
            self._paint_bubu_peek(p, mouth_pos=QPointF(self.width() - 18, self.height() - 22), scale=1.25)

    def _paint_bubu_peek(self, p, mouth_pos, scale):
        if self.bubu.isNull():
            return
        mouth_in_source = QPointF(self.bubu.width() * 0.52, self.bubu.height() * 0.62)
        p.save()
        p.translate(mouth_pos)
        p.rotate(-45)
        p.scale(scale, scale)
        p.drawPixmap(QPointF(-mouth_in_source.x(), -mouth_in_source.y()), self.bubu)
        p.restore()


class DuplicateTrackError(RuntimeError):
    pass


class MusicPlayerSignals(QObject):
    singerTrackReady = pyqtSignal(object, object)
    singerOutroFinished = pyqtSignal()


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


LRESULT = ctypes.c_ssize_t
LPARAM = ctypes.c_ssize_t
ULONG_PTR = wintypes.WPARAM


INPUT_WIDGET_TYPES = (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QAbstractSpinBox)


def _is_input_widget(widget):
    while widget is not None:
        if isinstance(widget, INPUT_WIDGET_TYPES):
            return True
        widget = widget.parentWidget() if hasattr(widget, "parentWidget") else None
    return False


class GlobalMusicSpaceFilter(QObject):
    toggleRequested = pyqtSignal()

    def __init__(self, music):
        super().__init__()
        self.music = music
        self._hook = None
        self._hook_proc = None
        self._hook_thread = None
        self._hook_error = 0
        self._space_is_down = False
        self._uia = None
        self._last_global_space_ms = 0
        self._space_enabled = False
        self.toggleRequested.connect(self._toggle_from_main_thread)
        self.music.player.playbackStateChanged.connect(lambda _state: self._sync_space_enabled())
        self.music.player.sourceChanged.connect(lambda _source: self._sync_space_enabled())
        self._sync_space_enabled()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        if os.name == "nt":
            self._start_windows_space_hook()

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() != QEvent.Type.KeyPress:
            return False
        if event.key() != Qt.Key.Key_Space or event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        if event.isAutoRepeat():
            return True
        if _is_input_widget(QApplication.focusWidget()) or _is_input_widget(obj):
            return False
        if self.music.player.source().isEmpty():
            return False
        self.music.toggle_play()
        event.accept()
        return True

    def _toggle_from_main_thread(self):
        self._sync_space_enabled()
        if self.music.player.source().isEmpty():
            return
        self.music.toggle_play()

    def _sync_space_enabled(self):
        self._space_enabled = not self.music.player.source().isEmpty()

    def _start_windows_space_hook(self):
        if self._hook_thread is not None:
            return
        self._hook_thread = threading.Thread(target=self._run_windows_space_hook, daemon=True)
        self._hook_thread.start()

    def _run_windows_space_hook(self):
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:  # noqa: BLE001
            pass
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        WH_KEYBOARD_LL = 13
        WM_KEYDOWN = 0x0100
        WM_SYSKEYDOWN = 0x0104
        WM_KEYUP = 0x0101
        WM_SYSKEYUP = 0x0105
        VK_SPACE = 0x20

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, LPARAM)
        user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, LPARAM)
        user32.CallNextHookEx.restype = LRESULT
        user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
        user32.GetMessageW.restype = wintypes.BOOL

        def call_next(n_code, w_param, l_param):
            try:
                return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
            except Exception:  # noqa: BLE001
                return 0

        def proc(n_code, w_param, l_param):
            try:
                if n_code == 0 and w_param in (WM_KEYUP, WM_SYSKEYUP):
                    event = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    if event.vkCode == VK_SPACE:
                        self._space_is_down = False
                elif n_code == 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    event = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    if event.vkCode == VK_SPACE:
                        if self._space_is_down:
                            return call_next(n_code, w_param, l_param)
                        self._space_is_down = True
                        if self._should_handle_global_space(event.time):
                            self._last_global_space_ms = int(event.time)
                            self.toggleRequested.emit()
                            return 1
            except Exception:  # noqa: BLE001
                return call_next(n_code, w_param, l_param)
            return call_next(n_code, w_param, l_param)

        self._hook_proc = HOOKPROC(proc)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._hook_proc, None, 0)
        if not self._hook:
            self._hook_error = kernel32.GetLastError()
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _should_handle_global_space(self, event_time_ms):
        if not self._space_enabled:
            return False
        if int(event_time_ms) - self._last_global_space_ms < 180:
            return False
        if self._modifier_pressed():
            return False
        if self._foreground_looks_like_input():
            return False
        return True

    def _modifier_pressed(self):
        try:
            user32 = ctypes.windll.user32
            for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C):  # Shift, Ctrl, Alt, left/right Win
                if user32.GetAsyncKeyState(vk) & 0x8000:
                    return True
        except Exception:  # noqa: BLE001
            return False
        return False

    def _foreground_looks_like_input(self):
        try:
            user32 = ctypes.windll.user32
            foreground = user32.GetForegroundWindow()
            if not foreground:
                return False
            uia_input = self._uia_focused_looks_like_input()
            if uia_input is True:
                return True
            thread_id = user32.GetWindowThreadProcessId(foreground, None)
            info = GUITHREADINFO()
            info.cbSize = ctypes.sizeof(GUITHREADINFO)
            if user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
                if info.hwndCaret:
                    return True
                focus = info.hwndFocus or foreground
            else:
                focus = foreground
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(focus, class_name, 256)
            lowered = class_name.value.lower()
            if any(token in lowered for token in (
                "edit", "richedit", "textbox", "input", "ime", "notepad", "scintilla",
            )):
                return True
            if uia_input is None:
                window_class = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(foreground, window_class, 256)
                foreground_class = window_class.value.lower()
                cautious_tokens = (
                    "chrome_widgetwin", "mozilla", "internet explorer_server", "applicationframewindow",
                    "notepad", "notepad++", "wechat", "txguifoundation", "qt", "electron",
                    "xlmain", "opusapp", "pptframeclass", "wndclass_desked_gsk",
                )
                return any(token in foreground_class or token in lowered for token in cautious_tokens)
            return False
        except Exception:  # noqa: BLE001
            return False

    def _uia_focused_looks_like_input(self):
        try:
            if self._uia is None:
                import comtypes.client
                self._uia = comtypes.client.CreateObject("UIAutomationClient.CUIAutomation")
            element = self._uia.GetFocusedElement()
            if element is None:
                return None
            control_type = int(element.CurrentControlType)
            if control_type in (50003, 50004, 50030, 50034, 50036):  # ComboBox, Edit, Document, DataGrid, Spinner
                return True
            class_name = (element.CurrentClassName or "").lower()
            if any(token in class_name for token in (
                "edit", "richedit", "textbox", "input", "document", "scintilla", "chrome_renderwidgethosthwnd",
            )):
                return True
            return False
        except Exception:  # noqa: BLE001
            self._uia = None
            return None


class MarqueeLabel(QLabel):
    def __init__(self, text=""):
        super().__init__(text)
        self._offset = 0
        self._hovering = False
        self._pause_ticks = 0
        self._timer = QTimer(self)
        self._timer.setInterval(32)
        self._timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setContentsMargins(0, 0, 0, 0)

    def sizeHint(self):  # noqa: N802
        return QSize(24, max(TRACK_ROW_H, self.fontMetrics().height() + 4))

    def minimumSizeHint(self):  # noqa: N802
        return QSize(0, max(1, self.fontMetrics().height()))

    def start_marquee(self):
        self._hovering = True
        self._offset = 0
        self._pause_ticks = 18
        if self._is_overflowing():
            self._timer.start()
        self.update()

    def stop_marquee(self):
        self._hovering = False
        self._timer.stop()
        self._offset = 0
        self._pause_ticks = 0
        self.update()

    def _is_overflowing(self):
        metrics = self.fontMetrics()
        return metrics.horizontalAdvance(self.text()) > self._available_text_width()

    def _available_text_width(self):
        margins = self.contentsMargins()
        return max(0, self.width() - margins.left() - margins.right() - 1)

    def _tick(self):
        if not self._hovering or not self._is_overflowing():
            self.stop_marquee()
            return
        if self._pause_ticks > 0:
            self._pause_ticks -= 1
            return
        metrics = self.fontMetrics()
        overflow = metrics.horizontalAdvance(self.text()) - self._available_text_width()
        self._offset += 1
        if self._offset > overflow + 28:
            self._offset = 0
            self._pause_ticks = 18
        self.update()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if not self._is_overflowing():
            self._offset = 0
            self._timer.stop()
        elif self._hovering and not self._timer.isActive():
            self._timer.start()

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        row = self.parentWidget()
        playing = row.property("playing") == "true" if row is not None else False
        p.setPen(QColor("#f97510") if playing else QColor("#3d2b1f"))
        margins = self.contentsMargins()
        rect = self.rect().adjusted(margins.left(), 0, -margins.right() - 1, 0)
        p.setClipRect(rect)
        metrics = p.fontMetrics()
        text = self.text()
        if self._hovering and self._is_overflowing():
            text_width = metrics.horizontalAdvance(text) + 4
            text_rect = QRectF(rect.left() - self._offset, rect.top(), text_width, rect.height())
            p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        else:
            clipped = metrics.elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
            p.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, clipped)


class ClickableLyricLabel(QLabel):
    clicked = pyqtSignal()

    def __init__(self, text=""):
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            e.accept()
            return
        super().mousePressEvent(e)


class GradientLyricLabel(QWidget):
    def __init__(self):
        super().__init__()
        self._text = _marked_lyric(_default_lyric())
        self._progress = 0.0
        self._font_size = 24
        self._accent = QColor(config.settings.get("lyricAccent", "#f97510"))
        self.setMinimumSize(480, 46)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            if window is not None:
                window.activateWindow()
                window.setFocus(Qt.FocusReason.MouseFocusReason)
            self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(e)

    def keyPressEvent(self, e):  # noqa: N802
        window = self.window()
        if window is not None and hasattr(window, "handle_overlay_key") and window.handle_overlay_key(e):
            return
        super().keyPressEvent(e)

    def set_text(self, text, progress=0.0):
        self._text = _marked_lyric(text)
        self._progress = max(0.0, min(1.0, float(progress)))
        self.update()

    def set_font_size(self, size):
        self._font_size = max(16, min(46, int(size)))
        self.update()

    def font_size(self):
        return self._font_size

    def set_accent(self, color):
        if color.isValid():
            self._accent = QColor(color)
            self.update()

    def accent(self):
        return QColor(self._accent)

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        text = self._text.strip() or _marked_lyric(_default_lyric())
        font = QFont("Microsoft YaHei", self._font_size)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        metrics = p.fontMetrics()
        max_width = max(20, self.width() - 24)
        text_width = max(1, metrics.horizontalAdvance(text))
        left = (self.width() - max_width) / 2
        if text_width <= max_width:
            x = (self.width() - text_width) / 2
            offset = 0.0
        else:
            highlight_width = text_width * self._progress
            offset = max(0.0, highlight_width - max_width)
            offset = min(offset, text_width - max_width)
            x = left - offset
        y = (self.height() + metrics.ascent() - metrics.descent()) / 2
        visible_rect = QRectF(left, 0, max_width, self.height())
        text_path = QPainterPath()
        text_path.addText(QPointF(x, y), font, text)
        p.save()
        p.setClipRect(visible_rect)
        p.setPen(QPen(QColor(0, 0, 0, 90), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(text_path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawPath(text_path)
        if self._progress <= 0:
            p.restore()
            return
        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0.0, self._accent)
        grad.setColorAt(0.68, QColor("#ffb25a"))
        grad.setColorAt(1.0, QColor("#ffffff"))
        p.setClipRect(visible_rect.intersected(QRectF(x, 0, text_width * self._progress, self.height())))
        p.setBrush(grad)
        p.drawPath(text_path)
        p.restore()


class LyricOverlayWindow(QDialog):
    BASE_W = 650
    BASE_H = 94

    def __init__(self, music):
        super().__init__()
        self.music = music
        self._drag_pos = None
        self._scale = float(config.settings.get("lyricOverlayScale", 1.0))
        self._scale = max(0.72, min(1.55, self._scale))
        self._icon_buttons = []
        self._font_buttons = []
        self._swatches = []
        self._control_slots = []
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._build()
        self._apply_scale()
        music.player.positionChanged.connect(self.sync)
        music.player.playbackStateChanged.connect(self.sync)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(0)
        controls.addStretch(1)
        self.loop_b = IconButton("loop", 30)
        self.prev_b = IconButton("prev", 30)
        self.play_b = IconButton("play", 30)
        self.next_b = IconButton("next", 30)
        self.font_up_b = QPushButton("A+")
        self.font_down_b = QPushButton("A-")
        self.color_b = IconButton("palette", 30)
        self._icon_buttons = [self.loop_b, self.prev_b, self.play_b, self.next_b, self.color_b]
        for b in (self.loop_b, self.prev_b, self.play_b, self.next_b, self.color_b):
            b.setProperty("plainOverlay", True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet("QPushButton { background: transparent; border: none; } QPushButton:hover { background: transparent; border: none; }")
        for b in (self.font_up_b, self.font_down_b):
            b.setObjectName("toolBtn")
            b.setFixedSize(48, 26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet("""
QPushButton#toolBtn {
    background: transparent;
    border: none;
    color: #f97510;
    font-family: 'Microsoft YaHei', 'Segoe UI';
    font-size: 16px;
    font-weight: 800;
    padding: 0;
}
QPushButton#toolBtn:hover { color: #ff9a3d; }
""")
        self._font_buttons = [self.font_up_b, self.font_down_b]
        self.loop_b.setToolTip(tr("循环模式"))
        self.prev_b.setToolTip(tr("上一首"))
        self.play_b.setToolTip(tr("播放/暂停"))
        self.next_b.setToolTip(tr("下一首"))
        self.color_b.setToolTip(tr("歌词颜色"))
        self.loop_b.clicked.connect(self.music.cycle_loop)
        self.prev_b.clicked.connect(self.music.prev)
        self.play_b.clicked.connect(self.music.toggle_play)
        self.next_b.clicked.connect(self.music.next)
        self.font_up_b.clicked.connect(lambda: self.lyric.set_font_size(self.lyric.font_size() + 2))
        self.font_down_b.clicked.connect(lambda: self.lyric.set_font_size(self.lyric.font_size() - 2))
        self.color_b.clicked.connect(self._toggle_palette)
        for b in (self.loop_b, self.prev_b, self.play_b, self.next_b, self.font_up_b, self.font_down_b, self.color_b):
            controls.addWidget(self._control_slot(b))
        controls.addStretch(1)
        root.addLayout(controls)

        self.palette = QWidget()
        palette_row = QHBoxLayout(self.palette)
        palette_row.setContentsMargins(0, 0, 0, 0)
        palette_row.setSpacing(8)
        palette_row.addStretch(1)
        for color in ("#f97510", "#4d96ff", "#ff5f8f", "#7bd88f", "#b990ff"):
            swatch = QPushButton()
            swatch.setFixedSize(18, 18)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            swatch.setStyleSheet(f"""
QPushButton {{ background: {color}; border: 1px solid rgba(255,255,255,0.72); border-radius: 9px; }}
QPushButton:hover {{ border: 2px solid #ffffff; }}
""")
            swatch.clicked.connect(lambda checked=False, c=color: self._set_color(c))
            palette_row.addWidget(swatch)
            self._swatches.append(swatch)
        palette_row.addStretch(1)
        self.palette.hide()
        root.addWidget(self.palette)

        self.lyric = GradientLyricLabel()
        root.addWidget(self.lyric)

    def _control_slot(self, button):
        slot = QWidget()
        layout = QHBoxLayout(slot)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        layout.addWidget(button)
        layout.addStretch(1)
        self._control_slots.append(slot)
        return slot

    def _apply_scale(self):
        s = self._scale
        self.setFixedSize(int(self.BASE_W * s), int(self.BASE_H * s))
        slot_w = int(58 * s)
        for slot in self._control_slots:
            slot.setFixedWidth(slot_w)
            slot.setFixedHeight(int(28 * s))
        for b in self._icon_buttons:
            base = 30
            b.setFixedSize(int(base * s), int(base * s))
        for b in self._font_buttons:
            b.setFixedSize(int(48 * s), int(28 * s))
            b.setStyleSheet(f"""
QPushButton#toolBtn {{
    background: transparent;
    border: none;
    color: #f97510;
    font-family: 'Microsoft YaHei', 'Segoe UI';
    font-size: {max(12, int(16 * s))}px;
    font-weight: 800;
    padding: 0;
}}
QPushButton#toolBtn:hover {{ color: #ff9a3d; }}
""")
        for swatch in self._swatches:
            swatch.setFixedSize(int(18 * s), int(18 * s))
        self.lyric.setMinimumSize(int(480 * s), int(46 * s))
        self.lyric.set_font_size(int(25 * s))
        self._dock_bottom_center()

    def _set_scale(self, scale):
        self._scale = max(0.72, min(1.55, float(scale)))
        self._apply_scale()
        config.settings.set("lyricOverlayScale", self._scale, save=True)

    def _set_color(self, color):
        self.lyric.set_accent(QColor(color))
        config.settings.set("lyricAccent", color, save=True)

    def _toggle_palette(self):
        self.palette.setVisible(not self.palette.isVisible())
        self._dock_bottom_center()

    def _screen_geometry(self):
        screen = self.screen()
        if screen is None and self.music.window:
            screen = self.music.window.screen()
        if screen is None and self.music.ctx and hasattr(self.music.ctx, "pet"):
            screen = self.music.ctx.pet.screen()
        return screen.availableGeometry() if screen is not None else None

    def _dock_bottom_center(self):
        geo = self._screen_geometry()
        if geo is None:
            return
        self.move(geo.x() + (geo.width() - self.width()) // 2,
                  geo.y() + geo.height() - self.height())

    def show_near_player(self):
        self._dock_bottom_center()
        self.show()
        self.raise_()
        self.sync()

    def sync(self, *args):
        self.loop_b.kind = ["loop", "loop_one", "shuffle"][self.music.loop]
        self.loop_b.update()
        self.play_b.kind = "pause" if self.music.player.isPlaying() else "play"
        self.play_b.update()
        text, progress = self.music.lyric_display(self.music.player.position())
        self.lyric.set_text(text, progress)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.activateWindow()
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._drag_pos = e.globalPosition().toPoint() - self.pos()
            e.accept()
            return
        super().mousePressEvent(e)

    def handle_overlay_key(self, e):
        if e.key() == Qt.Key.Key_Space and not (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.music.toggle_play()
            e.accept()
            return True
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if e.key() == Qt.Key.Key_Up:
                self.lyric.set_font_size(self.lyric.font_size() + 2)
                e.accept()
                return True
            if e.key() == Qt.Key.Key_Down:
                self.lyric.set_font_size(self.lyric.font_size() - 2)
                e.accept()
                return True
            if e.key() == Qt.Key.Key_Left:
                self.music.prev()
                e.accept()
                return True
            if e.key() == Qt.Key.Key_Right:
                self.music.next()
                e.accept()
                return True
        return False

    def keyPressEvent(self, e):  # noqa: N802
        if self.handle_overlay_key(e):
            return
        super().keyPressEvent(e)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(e)

    def wheelEvent(self, e):  # noqa: N802
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = e.angleDelta().y()
            if delta:
                self._set_scale(self._scale + (0.05 if delta > 0 else -0.05))
                e.accept()
                return
        super().wheelEvent(e)

    def retranslate_ui(self):
        self.loop_b.setToolTip(tr("循环模式"))
        self.prev_b.setToolTip(tr("上一首"))
        self.play_b.setToolTip(tr("播放/暂停"))
        self.next_b.setToolTip(tr("下一首"))
        self.color_b.setToolTip(tr("歌词颜色"))
        self.sync()


class PlayerWindow(QDialog):
    remoteSearchDone = pyqtSignal(str, object, object)
    remotePlayReady = pyqtSignal(object, object)
    remoteDownloadReady = pyqtSignal(object, object)

    def __init__(self, music):
        super().__init__()
        self.music = music
        self._drag_pos = None
        self._auto_dock_enabled = True
        self._expanded = False
        self._search_query = ""
        self._remote_query = ""
        self._remote_results = []
        self._remote_page = -1
        self._remote_has_more = False
        self._remote_loading = False
        self._remote_token = 0
        self._remote_error = ""
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(PLAYER_W, PLAYER_H)
        self._build()
        self._disable_default_buttons()
        self.installEventFilter(self)
        self.remoteSearchDone.connect(self._on_remote_search_done)
        self.remotePlayReady.connect(self._on_remote_play_ready)
        self.remoteDownloadReady.connect(self._on_remote_download_ready)
        music.player.positionChanged.connect(self._on_pos)
        music.player.durationChanged.connect(self._on_dur)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.card = PlayerCard()
        self.card.setObjectName("playerCard")
        self.card.setStyleSheet(PLAYER_QSS)
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(180, 120, 50, 30))
        self.card.setGraphicsEffect(shadow)
        root.addWidget(self.card)

        body = QVBoxLayout(self.card)
        body.setContentsMargins(18, 18, 18, 0)
        body.setSpacing(0)

        win_row = QHBoxLayout()
        win_row.setContentsMargins(0, 0, 0, 0)
        win_row.addStretch(1)
        win_row.setSpacing(6)
        self.back_b = IconButton("back", 22)
        self.close_b = IconButton("close", 22)
        self.back_b.setToolTip(tr("返回"))
        self.close_b.setToolTip(tr("退出播放器"))
        self.back_b.clicked.connect(self.showMinimized)
        self.close_b.clicked.connect(self.music.close_player)
        win_row.addWidget(self.back_b)
        win_row.addWidget(self.close_b)
        body.addLayout(win_row)
        body.addSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(12)
        self.cover = CoverWidget()
        meta = QVBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(2)
        self.title = QLabel(tr("未在播放"))
        self.title.setObjectName("trackTitle")
        self.title.setMinimumWidth(0)
        self.artist = QLabel(tr("用户音乐"))
        self.artist.setObjectName("artist")
        self.artist.setMinimumWidth(0)
        self.lyric = ClickableLyricLabel(_marked_lyric(tr("今天也想和你听完这一句")))
        self.lyric.setObjectName("lyricText")
        self.lyric.setMinimumWidth(0)
        self.lyric.clicked.connect(self.music.toggle_lyric_overlay)
        meta.addWidget(self.title)
        meta.addWidget(self.artist)
        meta.addWidget(self.lyric)
        top.addWidget(self.cover)
        top.addLayout(meta)
        top.addStretch(1)
        body.addLayout(top)
        body.addSpacing(14)

        self.prog = SlimSlider("#f97510")
        self.prog.setRange(0, 1000)
        self.prog.clicked.connect(self._seek_to_value)
        self.prog.sliderReleased.connect(self._seek)
        body.addWidget(self.prog)
        body.addSpacing(4)
        self.time_row = QHBoxLayout()
        self.time_row.setContentsMargins(0, 0, 0, 0)
        self.cur_t = QLabel("00:00")
        self.dur_t = QLabel("00:00")
        self.cur_t.setObjectName("timeText")
        self.dur_t.setObjectName("durationText")
        self.time_row.addWidget(self.cur_t)
        self.time_row.addStretch(1)
        self.time_row.addWidget(self.dur_t)
        body.addLayout(self.time_row)
        body.addSpacing(13)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(18)
        ctrl.addStretch(1)
        self.prev_b = IconButton("prev", 38)
        self.play_b = IconButton("play", 50)
        self.next_b = IconButton("next", 38)
        self.prev_b.clicked.connect(self.music.prev)
        self.play_b.clicked.connect(self.music.toggle_play)
        self.next_b.clicked.connect(self.music.next)
        ctrl.addWidget(self.prev_b)
        ctrl.addWidget(self.play_b)
        ctrl.addWidget(self.next_b)
        ctrl.addStretch(1)
        body.addLayout(ctrl)
        body.addSpacing(13)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.loop_b = IconButton("loop", 27)
        self.vol_icon = IconButton("volume", 22)
        self.vol = SlimSlider("#a08e7a")
        self.vol.setObjectName("volume")
        self.vol.setRange(0, 100)
        self.vol.setValue(self.music._volume)
        self.vol.valueChanged.connect(self._on_volume_changed)
        self.loop_b.clicked.connect(self.music.cycle_loop)
        self.vol_icon.clicked.connect(self.music.toggle_mute)
        self.list_b = IconButton("list", 27)
        self.list_b.clicked.connect(self.toggle_playlist)
        bottom.addWidget(self.loop_b)
        bottom.addWidget(self.vol_icon)
        bottom.addWidget(self.vol, 1)
        bottom.addWidget(self.list_b)
        body.addLayout(bottom)
        body.addSpacing(17)

        self.playlist_panel = QWidget()
        self.playlist_panel.setObjectName("playlistPanel")
        panel = QVBoxLayout(self.playlist_panel)
        panel.setContentsMargins(0, 11, 0, 0)
        panel.setSpacing(9)
        self.search = QLineEdit()
        self.search.setObjectName("searchInput")
        self.search.setPlaceholderText(tr("搜索歌曲..."))
        self.search.setFixedHeight(36)
        self.search.returnPressed.connect(self.perform_search)
        self.search.textChanged.connect(self._on_search_changed)
        self.search_b = IconButton("search", 36)
        self.search_b.setObjectName("uploadBtn")
        self.search_b.setToolTip(tr("搜索歌曲"))
        self.search_b.clicked.connect(self.perform_search)
        self.upload_b = IconButton("upload", 36)
        self.upload_b.setObjectName("uploadBtn")
        self.upload_b.setToolTip(tr("上传音乐"))
        self.upload_b.clicked.connect(self.music.upload)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(7)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.search_b)
        search_row.addWidget(self.upload_b)
        panel.addLayout(search_row)
        self.list = QScrollArea()
        self.list.setObjectName("playlist")
        self.list.setWidgetResizable(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setFixedHeight(TRACK_ROW_H * PLAYLIST_VISIBLE_ROWS)
        self.list.verticalScrollBar().valueChanged.connect(self._maybe_load_more_remote)
        self.playlist_body = QWidget()
        self.playlist_body.setObjectName("playlistBody")
        self.playlist_layout = QVBoxLayout(self.playlist_body)
        self.playlist_layout.setContentsMargins(0, 0, 0, 18)
        self.playlist_layout.setSpacing(0)
        self.list.setWidget(self.playlist_body)
        panel.addWidget(self.list)
        self.playlist_panel.hide()
        body.addWidget(self.playlist_panel)
        self._filter("")

    def _disable_default_buttons(self):
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _search_has_focus(self):
        return self.search.hasFocus()

    def _is_search_child(self, widget):
        while widget is not None:
            if widget is self.search:
                return True
            widget = widget.parentWidget()
        return False

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self and event.type() == QEvent.Type.KeyPress:
            return self._handle_player_key(event)
        return super().eventFilter(obj, event)

    def begin_open_session(self):
        self._auto_dock_enabled = True
        if self._expanded:
            self._expanded = False
            self.playlist_panel.hide()
            self.card.set_expanded(False)
            self._filter(self._search_query)
        self.setFixedSize(PLAYER_W, PLAYER_H)
        self._dock_to_work_area_bottom(align_right=True)

    def mousePressEvent(self, e):  # noqa: N802
        child = self.childAt(e.position().toPoint())
        if not self._is_search_child(child):
            self.search.clearFocus()
            self.setFocus(Qt.FocusReason.MouseFocusReason)
        interactive = (SlimSlider, QPushButton, QScrollArea, QLineEdit, TrackItemWidget, ClickableLyricLabel)
        if e.button() == Qt.MouseButton.LeftButton and not isinstance(child, interactive):
            self._drag_pos = e.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag_pos is not None:
            self._auto_dock_enabled = False
            self.move(e.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(e)

    def moveEvent(self, e):  # noqa: N802
        if hasattr(self, "cover"):
            self.cover.sync_preview_position()
        super().moveEvent(e)

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):  # noqa: N802
        if self._handle_player_key(e):
            return
        super().keyPressEvent(e)

    def _handle_player_key(self, e):
        key = e.key()
        ctrl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        in_search = self._search_has_focus()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if in_search:
                self.perform_search()
                e.accept()
                return True
        if in_search:
            return False
        if key == Qt.Key.Key_Space:
            if e.isAutoRepeat():
                e.accept()
                return True
            self.music.toggle_play()
            e.accept()
            return True
        if ctrl and key == Qt.Key.Key_Left:
            self.music.seek_relative(-2000)
            e.accept()
            return True
        if ctrl and key == Qt.Key.Key_Right:
            self.music.seek_relative(2000)
            e.accept()
            return True
        if ctrl and key == Qt.Key.Key_Up:
            self.set_volume_from_keyboard(10)
            e.accept()
            return True
        if ctrl and key == Qt.Key.Key_Down:
            self.set_volume_from_keyboard(-10)
            e.accept()
            return True
        return False

    def _available_geometry(self):
        screen = self.screen()
        if screen is None:
            center = self.frameGeometry().center()
            screen = QApplication.screenAt(center)
        if screen is None and self.music.ctx and hasattr(self.music.ctx, "pet"):
            screen = self.music.ctx.pet.screen()
        return screen.availableGeometry() if screen is not None else None

    def _dock_to_work_area_bottom(self, align_right=False):
        geo = self._available_geometry()
        if geo is None:
            return
        if align_right:
            x = geo.right() - self.width() - 24 + 1
        else:
            x = min(max(self.x(), geo.left()), geo.right() - self.width() + 1)
        y = geo.bottom() - self.height() + 1
        y = max(geo.top(), y)
        self.move(x, y)

    def toggle_playlist(self):
        self._expanded = not self._expanded
        self.music.refresh_tracks()
        self.playlist_panel.setVisible(self._expanded)
        self.card.set_expanded(self._expanded)
        self.setFixedSize(PLAYER_W, PLAYER_EXPANDED_H if self._expanded else PLAYER_H)
        if self._auto_dock_enabled:
            self._dock_to_work_area_bottom()
        self._filter(self._search_query)

    def perform_search(self):
        query = " ".join(self.search.text().split())
        self._search_query = query
        self._remote_query = ""
        self._remote_results = []
        self._remote_page = -1
        self._remote_has_more = False
        self._remote_error = ""
        self._filter(query)
        if query:
            self._search_remote(query, reset=True)

    def _on_search_changed(self, text):
        """搜索框只监听清空状态；实际搜索由搜索按钮触发。"""
        query = " ".join(text.split())
        if query:
            return
        self._search_query = ""
        self._remote_query = ""
        self._remote_results = []
        self._remote_page = -1
        self._remote_has_more = False
        self._remote_loading = False
        self._remote_error = ""
        self._filter("")
        if not self._expanded:
            # 清空即展示完整歌曲列表：若播放列表面板处于隐藏状态则自动展开
            self.toggle_playlist()

    def _search_remote(self, query, reset=False):
        if self._remote_loading and not reset:
            return
        if not reset and (query != self._remote_query or not self._remote_has_more):
            return
        page = 0 if reset else self._remote_page + 1
        self._remote_token += 1
        token = self._remote_token
        self._remote_query = query
        self._remote_loading = True
        self._remote_error = ""
        if reset:
            self._remote_results = []
            self._remote_page = -1
            self._remote_has_more = False
            self._filter(query, refresh=False)

        def worker():
            try:
                results = music_api.search_full(query, page=page, size=REMOTE_PAGE_SIZE, candidates=REMOTE_PAGE_SIZE)
                self.remoteSearchDone.emit(query, {"page": page, "results": results, "token": token}, None)
            except Exception as exc:  # noqa: BLE001
                self.remoteSearchDone.emit(query, {"page": page, "results": [], "token": token}, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_remote_search_done(self, query, payload, error):
        if query != self._remote_query:
            return
        bar = self.list.verticalScrollBar()
        old_scroll = bar.value()
        if isinstance(payload, dict):
            if int(payload.get("token") or 0) != self._remote_token:
                return
            page = int(payload.get("page") or 0)
            results = list(payload.get("results") or [])
        else:
            page = 0
            results = list(payload or [])
        self._remote_loading = False
        if page == 0:
            self._remote_results = results
        else:
            self._remote_results.extend(results)
        self._remote_page = max(self._remote_page, page)
        self._remote_has_more = len(results) >= REMOTE_PAGE_SIZE
        self._remote_error = error or ""
        self._filter(query, refresh=False)
        if page > 0:
            QTimer.singleShot(0, lambda value=old_scroll: self.list.verticalScrollBar().setValue(value))

    def _maybe_load_more_remote(self, *_args):
        if not self._search_query or self._remote_loading or not self._remote_has_more:
            return
        bar = self.list.verticalScrollBar()
        if bar.maximum() > 0 and bar.value() >= bar.maximum() - TRACK_ROW_H:
            self._search_remote(self._search_query, reset=False)

    def _on_remote_play_ready(self, payload, error):
        if error:
            say(tr("这首歌暂时没有完整版资源"))
            return
        self.music.play_cached(payload)

    def _on_remote_download_ready(self, payload, error):
        if error:
            if error == "歌曲已存在":
                say(tr("歌曲已存在"))
                return
            say(tr("这首歌暂时没有完整版资源"))
            return
        remove_cache_path = (payload or {}).get("remove_cache_path")
        if remove_cache_path:
            self.music.delete_track_path(remove_cache_path, remove_sidecars=False)
        self.music.refresh_tracks()
        self.sync()
        say(tr("下载完成"))

    def _filter(self, text, refresh=True):
        if refresh:
            self.music.refresh_tracks()
        while self.playlist_layout.count():
            item = self.playlist_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        matches = 0
        local_keys: set[tuple[str, str]] = set()
        remote_keys: set[tuple[str, str]] = set()
        query = text.lower().strip()
        for i, p in enumerate(self.music.tracks):
            if not query or query in _track_search_text(p):
                local_keys.add(_track_dedupe_key(p))
                title = _track_display_title(p)
                mark = "♪" if i == self.music.index else f"{i + 1:02d}"
                duration = self.music.duration_text(p)
                source = "cache" if music_api.is_cache_path(p) else "local"
                payload = music_api.cache_info(p) if source == "cache" else None
                if payload is not None:
                    payload = {**payload, "cache_path": p, "minfo": payload.get("minfo", "")}
                row = TrackItemWidget(mark, title, duration, i, i == self.music.index, source=source, payload=payload)
                row.clicked.connect(self.music.play_index)
                row.deleteRequested.connect(self.music.delete_track)
                row.downloadRequested.connect(self.music.download_remote)
                row.saveAsRequested.connect(self.music.save_as_track)
                self.playlist_layout.addWidget(row)
                matches += 1
        if query:
            if self._remote_loading:
                self.playlist_layout.addWidget(TrackItemWidget("", tr("搜索中..."), "", -1, source="status"))
            elif self._remote_error:
                self.playlist_layout.addWidget(TrackItemWidget("", tr("网络搜索失败"), "", -1, source="status"))
            elif self._remote_query == text:
                for i, item in enumerate(self._remote_results):
                    key = _remote_dedupe_key(item)
                    if key[0] and (key in local_keys or key in remote_keys):
                        continue
                    remote_keys.add(key)
                    row = TrackItemWidget(
                        f"{i + 1:02d}",
                        _remote_display_title(item),
                        _duration_from_seconds(item.get("duration")),
                        i,
                        False,
                        source="remote",
                        payload=item,
                    )
                    row.clicked.connect(self.music.play_remote)
                    row.downloadRequested.connect(self.music.download_remote)
                    row.addRemoteRequested.connect(self.music.cache_remote)
                    self.playlist_layout.addWidget(row)
                    matches += 1
                if not self._remote_results and matches == 0:
                    self.playlist_layout.addWidget(TrackItemWidget("", tr("没有搜到结果"), "", -1, source="status"))
        self.playlist_layout.addStretch(1)
        return matches

    def _on_pos(self, ms):
        d = self.music.player.duration() or 1
        self.prog.setValue(int(ms / d * 1000))
        self.cur_t.setText(self._fmt(ms))
        self.lyric.setText(self.music.lyric_text(ms))

    def _on_dur(self, ms):
        self.dur_t.setText(self._fmt(ms))

    def _seek(self):
        self._seek_to_value(self.prog.value())

    def _seek_to_value(self, value):
        d = self.music.player.duration() or 1
        self.music.player.setPosition(int(value / 1000.0 * d))

    def _on_volume_changed(self, value):
        if value > 0:
            self.music._muted = False
        config.settings.set("volume", int(value), save=True)
        self.music.set_volume(value)
        self._sync_volume_icon(value)

    def set_volume_from_keyboard(self, delta):
        value = max(0, min(100, self.vol.value() + int(delta)))
        self.vol.setValue(value)
        self._on_volume_changed(value)

    def _sync_volume_icon(self, value=None):
        value = self.vol.value() if value is None else value
        if self.music._muted or value <= 0:
            self.vol_icon.kind = "muted"
        elif value < 34:
            self.vol_icon.kind = "volume_1"
        elif value < 67:
            self.vol_icon.kind = "volume_2"
        else:
            self.vol_icon.kind = "volume_3"
        self.vol_icon.update()

    @staticmethod
    def _fmt(ms):
        s = ms // 1000
        return f"{s // 60:02d}:{s % 60:02d}"

    def sync(self):
        self.music.refresh_tracks()
        if self.music.tracks:
            self.music.index = max(0, min(self.music.index, len(self.music.tracks) - 1))
            track = self.music.tracks[self.music.index]
            self.title.setText(_track_title(track))
            self.artist.setText(_track_artist(track))
            self.lyric.setText(self.music.lyric_text(self.music.player.position()))
            self.cover.set_album_art(_album_art_for(track))
            self.cur_t.setText(self._fmt(self.music.player.position()))
            self.dur_t.setText(self.music.duration_text(track))
            self.prog.setValue(int(self.music.player.position() / (self.music.player.duration() or 1) * 1000))
            self.play_b.kind = "pause" if self.music.player.isPlaying() else "play"
            self.play_b.update()
            self.loop_b.kind = ["loop", "loop_one", "shuffle"][self.music.loop]
            self.loop_b.update()
            self._sync_volume_icon(self.vol.value())
        else:
            self.title.setText(tr("未在播放"))
            self.artist.setText(tr("用户音乐"))
            self.lyric.setText(_marked_lyric(_default_lyric()))
            self.cover.set_album_art(None)
            self.cur_t.setText("00:00")
            self.dur_t.setText("00:00")
            self.prog.setValue(0)
        self._filter(self._search_query, refresh=False)
        self.vol.setValue(self.music._volume)
        self._sync_volume_icon(self.music._volume)

    def retranslate_ui(self):
        self.back_b.setToolTip(tr("返回"))
        self.close_b.setToolTip(tr("退出播放器"))
        self.search.setPlaceholderText(tr("搜索歌曲..."))
        self.search_b.setToolTip(tr("搜索歌曲"))
        self.upload_b.setToolTip(tr("上传音乐"))
        self.sync()


class MusicPlayer:
    def __init__(self, ctx):
        self.ctx = ctx
        self.player = QMediaPlayer()
        self._media_devices = QMediaDevices()
        self.audio = QAudioOutput()
        self._apply_default_audio_output()
        self._media_devices.audioOutputsChanged.connect(self._apply_default_audio_output)
        self.player.setAudioOutput(self.audio)
        self.tracks = []
        self.index = 0
        self.loop = 0  # 0 列表循环 / 1 单曲循环 / 2 随机
        self._muted = False
        self._volume = DEFAULT_MUSIC_VOLUME
        self._duration_cache = {}
        self._lyric_cache = {}
        self._kuwo_lyric_requested = set()
        self._alarm_mode = False
        self._singer_show_active = False
        self._singer_show_started_visible = False
        self._signals = MusicPlayerSignals()
        self._signals.singerTrackReady.connect(self._on_singer_track_ready)
        self._signals.singerOutroFinished.connect(self._close_after_singer_outro)
        self._global_space_filter = GlobalMusicSpaceFilter(self)
        self._singer_timer = QTimer()
        self._singer_timer.setSingleShot(True)
        self._singer_timer.timeout.connect(self._stop_singer)
        self.player.mediaStatusChanged.connect(self._on_status)
        self._apply_player_loops()
        self.set_volume(config.settings.get("volume", DEFAULT_MUSIC_VOLUME))
        self.refresh_tracks()
        self.window = None
        self.lyric_overlay = None

    def _apply_default_audio_output(self):
        device = QMediaDevices.defaultAudioOutput()
        if hasattr(device, "isNull") and device.isNull():
            return
        if self.audio.device() != device:
            self.audio.setDevice(device)
        self.audio.setVolume(0 if getattr(self, "_muted", False) else getattr(self, "_volume", DEFAULT_MUSIC_VOLUME) / 100.0)

    def _apply_player_loops(self):
        loops = QMediaPlayer.Loops.Infinite if self._alarm_mode or self.loop == 1 else QMediaPlayer.Loops.Once
        self.player.setLoops(loops)

    def _replay_current_source(self):
        if self.player.source().isEmpty():
            return
        self._apply_player_loops()
        self.player.stop()
        self.player.setPosition(0)
        self._apply_default_audio_output()
        self.player.play()
        if self.window:
            self.window.sync()
        self.sync_lyric_overlay()

    def ensure_window(self):
        if self.window is None:
            self.window = PlayerWindow(self)
        return self.window

    def ensure_lyric_overlay(self):
        if self.lyric_overlay is None:
            self.lyric_overlay = LyricOverlayWindow(self)
        return self.lyric_overlay

    def toggle_lyric_overlay(self):
        overlay = self.ensure_lyric_overlay()
        if overlay.isVisible():
            overlay.hide()
        else:
            overlay.show_near_player()

    def sync_lyric_overlay(self):
        if self.lyric_overlay and self.lyric_overlay.isVisible():
            self.lyric_overlay.sync()

    def refresh_tracks(self):
        current = self.player.source().toLocalFile()
        old_index_path = self.tracks[self.index] if 0 <= self.index < len(self.tracks) else ""
        music_api.cleanup_cache()
        local_tracks = assets.list_music_files()
        cache_tracks = music_api.list_cached_files()
        local_keys = {_track_dedupe_key(path) for path in local_tracks if _track_dedupe_key(path)[0]}
        cache_keys: set[tuple[str, str]] = set()
        for path in list(cache_tracks):
            key = _track_dedupe_key(path)
            if key[0] and key in local_keys:
                self.delete_track_path(path, remove_sidecars=False)
                continue
            if key[0] and key in cache_keys:
                self.delete_track_path(path, remove_sidecars=False)
                continue
            if key[0]:
                cache_keys.add(key)
        self.tracks = self._deduped_track_paths(assets.list_music_files() + music_api.list_cached_files())
        live = set(self.tracks)
        self._duration_cache = {p: d for p, d in self._duration_cache.items() if p in live}
        for p in self.tracks:
            self._duration_cache.setdefault(p, _parse_duration(p))
            lyrics.ensure_lyrics_async(p, self._duration_cache.get(p))
            self._ensure_cover(p)
        if not self.tracks:
            self.index = 0
        elif current in live:
            self.index = self.tracks.index(current)
        elif old_index_path in live:
            self.index = self.tracks.index(old_index_path)
        else:
            self.index = max(0, min(self.index, len(self.tracks) - 1))

    def _deduped_track_paths(self, paths):
        seen: set[tuple[str, str]] = set()
        out = []
        for path in paths:
            key = _track_dedupe_key(path)
            if key[0] and key in seen:
                continue
            if key[0]:
                seen.add(key)
            out.append(path)
        return out

    def _ensure_cover(self, path):
        title, artist = _split_track_artist(path)
        covers.ensure_cover_async(title, artist or None, lambda _p: QTimer.singleShot(0, self._cover_ready))

    def _cover_ready(self):
        if self.window:
            self.window.sync()

    def duration_text(self, path):
        if not path:
            return "--:--"
        cached = music_api.cache_info(path)
        if cached and cached.get("duration"):
            return _duration_from_seconds(cached.get("duration"))
        if path not in self._duration_cache:
            self._duration_cache[path] = _parse_duration(path)
        return self._duration_cache[path]

    def lyric_text(self, position_ms=None):
        text, _ = self.lyric_display(position_ms)
        return _marked_lyric(text)

    def lyric_display(self, position_ms=None):
        if not self.tracks:
            return _default_lyric(), 0.0
        track = self.tracks[max(0, min(self.index, len(self.tracks) - 1))]
        if not lyrics.has_lyrics(track):
            self._ensure_remote_lyrics(track)
            lyrics.ensure_lyrics_async(track, self.duration_text(track))
            return _default_lyric(), 0.0
        lyrics.simplify_existing_lyrics(track)
        file_path = lyrics.existing_lyric_file(track) or lyrics.lyric_path(track)
        try:
            mtime = os.path.getmtime(file_path)
        except OSError:
            return _default_lyric(), 0.0
        cached = self._lyric_cache.get(track)
        if cached is None or cached[0] != mtime:
            cached = (mtime, lyrics.load_lrc(track))
            self._lyric_cache[track] = cached
        lines = cached[1]
        if not lines:
            return _default_lyric(), 0.0
        pos = self.player.position() if position_ms is None else position_ms
        current_i = -1
        for i, (start_ms, _text) in enumerate(lines):
            if start_ms > pos:
                break
            current_i = i
        if current_i < 0:
            return _default_lyric(), 0.0
        start_ms, line = lines[current_i]
        end_ms = lines[current_i + 1][0] if current_i + 1 < len(lines) else max(start_ms + 2400, self.player.duration())
        progress = (pos - start_ms) / max(1, end_ms - start_ms)
        return lyrics.display_text(line), max(0.0, min(1.0, progress))

    def _ensure_remote_lyrics(self, path):
        info = music_api.cache_info(path)
        rid = (info or {}).get("rid")
        if not rid:
            return
        key = os.path.normcase(os.path.abspath(path))
        if key in self._kuwo_lyric_requested:
            return
        self._kuwo_lyric_requested.add(key)
        out_path = lyrics.lyric_path(path)
        if lyrics.existing_lyric_file(path):
            lyrics.simplify_existing_lyrics(path)
            return

        def worker():
            text = music_api.get_lrc(rid, (info or {}).get("source"), (info or {}).get("api"))
            if not text:
                return
            try:
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(lyrics.simplified_text(text))
            except OSError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _download_remote_to(self, item, br, folder, cache=False):
        existing = self._find_existing_track(item)
        cache_path = (item or {}).get("cache_path")
        moving_cache_to_library = (
            not cache and cache_path and existing and
            os.path.abspath(existing) == os.path.abspath(cache_path)
        )
        if existing and not moving_cache_to_library:
            raise DuplicateTrackError("歌曲已存在")
        info = music_api.full_url(item, br) if br else music_api.best_url(item, full_only=True)
        if not info or not info.get("url"):
            raise RuntimeError("无法获取完整版直链")
        ext = info.get("format") or "mp3"
        out_path = music_api.target_path(item, folder, ext, include_rid=cache)
        music_api.download(info["url"], out_path)
        lrc = music_api.get_lrc(item.get("rid", ""), item.get("source"), item.get("api"))
        if lrc:
            lyric_target = lyrics.lyric_path(out_path)
            os.makedirs(os.path.dirname(lyric_target), exist_ok=True)
            with open(lyric_target, "w", encoding="utf-8") as f:
                f.write(lyrics.simplified_text(lrc))
        music_api.remember_track(out_path, item, info)
        payload = {"path": out_path, "item": item, "quality": info}
        if not cache and cache_path and music_api.is_cache_path(cache_path):
            payload["remove_cache_path"] = cache_path
        return payload

    def _find_existing_track(self, item):
        key = _remote_dedupe_key(item or {})
        if not key[0]:
            return ""
        for path in assets.list_music_files() + music_api.list_cached_files():
            if _track_dedupe_key(path) == key:
                return path
        return ""

    def _has_any_track(self, item):
        return bool(self._find_existing_track(item))

    def _has_local_track(self, item):
        key = _remote_dedupe_key(item or {})
        if not key[0]:
            return False
        for path in assets.list_music_files():
            if _track_dedupe_key(path) == key:
                return True
        return False

    def play_remote(self, item):
        if not item or not self.window:
            return
        existing = self._find_existing_track(item)
        if existing:
            self.refresh_tracks()
            if existing in self.tracks:
                self.index = self.tracks.index(existing)
                self.play(existing)
                self.window.sync()
                return
        buffering_done = threading.Event()
        QTimer.singleShot(15000, lambda: None if buffering_done.is_set() else say(tr("正在缓冲捏")))

        def worker():
            try:
                payload = self._download_remote_to(item, None, music_api.cache_dir(), cache=True)
                self.window.remotePlayReady.emit(payload, None)
            except Exception as exc:  # noqa: BLE001
                self.window.remotePlayReady.emit(None, str(exc))
            finally:
                buffering_done.set()

        threading.Thread(target=worker, daemon=True).start()

    def cache_remote(self, item):
        if not item or not self.window:
            return
        if self._has_any_track(item):
            say(tr("歌曲已存在"))
            return
        say(tr("正在添加到播放列表"))

        def worker():
            try:
                payload = self._download_remote_to(item, None, music_api.cache_dir(), cache=True)
                self.window.remoteDownloadReady.emit(payload, None)
            except Exception as exc:  # noqa: BLE001
                self.window.remoteDownloadReady.emit(None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def download_remote(self, item, br):
        if not item or not self.window:
            return
        if self._has_local_track(item):
            say(tr("歌曲已存在"))
            return
        say(tr("开始下载"))

        def worker():
            try:
                payload = self._download_remote_to(item, br, assets.get_music_folder(), cache=False)
                self.window.remoteDownloadReady.emit(payload, None)
            except DuplicateTrackError as exc:
                self.window.remoteDownloadReady.emit(None, str(exc))
            except Exception as exc:  # noqa: BLE001
                self.window.remoteDownloadReady.emit(None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def play_cached(self, payload):
        path = (payload or {}).get("path")
        self.refresh_tracks()
        if path in self.tracks:
            self.index = self.tracks.index(path)
        self.play(path)
        if self.window:
            self.window.sync()

    def save_as_track(self, i):
        self.refresh_tracks()
        if not (0 <= i < len(self.tracks)):
            return
        src = self.tracks[i]
        title = _track_display_title(src).replace(" · 缓存", "")
        ext = os.path.splitext(src)[1] or ".mp3"
        target, _ = QFileDialog.getSaveFileName(None, tr("另存为"), f"{title}{ext}", "音频文件 (*.*)")
        if not target:
            return
        try:
            shutil.copy2(src, target)
            say(tr("保存完成"))
        except OSError:
            say(tr("保存失败，请稍后再试"))

    def delete_track(self, i):
        self.refresh_tracks()
        if not (0 <= i < len(self.tracks)):
            if self.window:
                self.window.sync()
            return
        path = self.tracks[i]
        if not self.delete_track_path(path, remove_sidecars=True):
            if self.window:
                self.window.sync()
            return
        if i <= self.index and self.index > 0:
            self.index -= 1
        self.refresh_tracks()
        if self.window:
            self.window.sync()

    def delete_track_path(self, path, remove_sidecars=True):
        if not path:
            return True
        cached_info = music_api.cache_info(path) or {}
        current = self.player.source().toLocalFile()
        if os.path.abspath(current) == os.path.abspath(path):
            self.player.stop()
            self.player.setSource(QUrl())
            for _ in range(6):
                QApplication.processEvents()
                QThread.msleep(35)
        ok = self._delete_audio_file(path)
        if not ok:
            return False
        self._duration_cache.pop(path, None)
        self._lyric_cache.pop(path, None)
        if remove_sidecars:
            self._delete_track_sidecars(path, cached_info)
        music_api.forget_cache(path)
        return True

    def _delete_audio_file(self, path):
        for _ in range(10):
            try:
                if os.path.exists(path):
                    os.remove(path)
                return True
            except OSError:
                QApplication.processEvents()
                QThread.msleep(50)
        return not os.path.exists(path)

    def _delete_track_sidecars(self, path, cached_info=None):
        cached_info = cached_info or {}
        title, artist = _split_track_artist(path)
        identities = {(title, artist or None)}
        meta_title = " ".join(str(cached_info.get("name") or "").split()).strip()
        meta_artist = " ".join(str(cached_info.get("artist") or "").split()).strip()
        if meta_title:
            identities.add((meta_title, meta_artist or None))

        folder = os.path.dirname(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        sidecars = {
            lyrics.lyric_path(path),
            lyrics.plain_lyric_path(path),
            os.path.join(folder, stem + ".lrc"),
            os.path.join(folder, stem + ".txt"),
        }
        for item_title, item_artist in identities:
            sidecars.add(covers.cover_path(item_title, item_artist))
            lyric_key = lyrics.safe_filename(f"{item_title} - {item_artist}" if item_artist else item_title)
            sidecars.add(os.path.join(lyrics.lyrics_dir(), lyric_key + ".lrc"))
            sidecars.add(os.path.join(lyrics.lyrics_dir(), lyric_key + ".txt"))
            cover_key = covers.cover_key(item_title, item_artist)
            sidecars.add(os.path.join(covers.covers_dir(), cover_key + ".jpg"))
        for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            sidecars.add(os.path.join(folder, stem + ext))
        for sidecar in sidecars:
            try:
                if sidecar and os.path.exists(sidecar):
                    os.remove(sidecar)
            except OSError:
                pass

    def set_volume(self, v):
        self._volume = max(0, min(100, int(v)))
        if not self._muted:
            self.audio.setVolume(self._volume / 100.0)

    def reset_player_volume(self):
        self._muted = False
        self.set_volume(config.settings.get("volume", DEFAULT_MUSIC_VOLUME))
        if self.window:
            self.window.vol.setValue(self._volume)
            self.window._sync_volume_icon(self._volume)

    def apply_settings(self):
        self.set_volume(config.settings.get("volume", DEFAULT_MUSIC_VOLUME))
        if self.window:
            self.window.vol.setValue(self._volume)
            self.window._sync_volume_icon(self._volume)

    def toggle_mute(self):
        self._muted = not self._muted
        self.audio.setVolume(0 if self._muted else self._volume / 100.0)
        if self.window:
            self.window.sync()

    def play(self, path):
        if not path or not os.path.exists(path):
            return
        self._alarm_mode = False
        self._apply_player_loops()
        self.player.setSource(QUrl.fromLocalFile(path))
        self._apply_player_loops()
        self._apply_default_audio_output()
        self.player.play()
        if self.window:
            self.window.sync()

    def play_alarm(self, path):
        """隐藏播放器播放闹钟铃声，并在单曲结束后自动循环。"""
        if not path or not os.path.exists(path):
            return
        if self.window:
            self.window.hide()
        self._alarm_mode = True
        self._apply_player_loops()
        self.player.setSource(QUrl.fromLocalFile(path))
        self._apply_player_loops()
        self._apply_default_audio_output()
        self.player.play()

    def toggle_play(self):
        if self.player.isPlaying():
            self.player.pause()
        else:
            if self.player.source().isEmpty() and self.tracks:
                self.play(self.tracks[self.index])
            else:
                self._apply_default_audio_output()
                self.player.play()
        if self.window:
            self.window.sync()

    def seek_relative(self, delta_ms):
        if self.player.source().isEmpty():
            return
        duration = self.player.duration()
        current = self.player.position()
        target = max(0, current + int(delta_ms))
        if duration > 0:
            target = min(duration, target)
        self.player.setPosition(target)
        if self.window:
            self.window.sync()
        self.sync_lyric_overlay()

    def play_index(self, i):
        if 0 <= i < len(self.tracks):
            self.index = i
            self.play(self.tracks[i])
            if self.window:
                self.window.sync()

    def _pick_random_index(self):
        if not self.tracks:
            return 0
        if len(self.tracks) == 1:
            return 0
        choices = [i for i in range(len(self.tracks)) if i != self.index]
        return random.choice(choices)

    def next(self):
        if not self.tracks:
            return
        if self.loop == 1:
            self.play(self.tracks[self.index])
        elif self.loop == 2:
            self.index = self._pick_random_index()
            self.play(self.tracks[self.index])
        else:
            self.index = (self.index + 1) % len(self.tracks)
            self.play(self.tracks[self.index])
        if self.window:
            self.window.sync()

    def prev(self):
        if not self.tracks:
            return
        if self.loop == 1:
            self.play(self.tracks[self.index])
        elif self.loop == 2:
            self.index = self._pick_random_index()
            self.play(self.tracks[self.index])
        else:
            self.index = (self.index - 1) % len(self.tracks)
            self.play(self.tracks[self.index])
        if self.window:
            self.window.sync()

    def cycle_loop(self):
        self.loop = (self.loop + 1) % 3
        self._apply_player_loops()
        if self.window:
            self.window.sync()
        self.sync_lyric_overlay()

    def _on_status(self, status):
        from PyQt6.QtMultimedia import QMediaPlayer
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self._singer_show_active:
                self._singer_show_active = False
                self.player.stop()
                QTimer.singleShot(180, self._speak_singer_outro)
                return
            if self._alarm_mode or self.loop == 1:
                QTimer.singleShot(0, self._replay_current_source)
                return
            else:
                self.next()

    def start_singer_show(self):
        self.refresh_tracks()
        self._singer_timer.stop()
        self._alarm_mode = False
        local_tracks = assets.list_music_files()
        if local_tracks:
            self._start_singer_track(random.choice(local_tracks))
            return

        def worker():
            try:
                item = self._find_kaitianchuang_item()
                if not item:
                    raise RuntimeError("无法找到开天窗")
                existing = self._find_existing_track(item)
                if existing:
                    self._signals.singerTrackReady.emit(existing, None)
                    return
                payload = self._download_remote_to(item, None, music_api.cache_dir(), cache=True)
                self._signals.singerTrackReady.emit(payload.get("path"), None)
            except Exception as exc:  # noqa: BLE001
                self._signals.singerTrackReady.emit(None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _find_kaitianchuang_item(self):
        for query in ("开天窗 五月天", "五月天 开天窗"):
            for item in music_api.search_full(query, page=0, size=8, candidates=16):
                title = _dedupe_text(item.get("name"))
                artist = _dedupe_text(item.get("artist"))
                if "开天窗" in title and "五月天" in artist:
                    return item
        return None

    def _on_singer_track_ready(self, path, error):
        if error or not path:
            say(tr("当前没有可播放的音乐，请先上传"))
            return
        self._start_singer_track(path)

    def _start_singer_track(self, path):
        if not path or not os.path.exists(path):
            say(tr("当前没有可播放的音乐，请先上传"))
            return
        self._singer_show_started_visible = bool(self.window and self.window.isVisible())
        say(tr("歌手小PP登场捏~"))
        self._singer_show_active = True
        self.play(path)
        self.player.setLoops(QMediaPlayer.Loops.Once)

    def _speak_singer_outro(self):
        spoken = on_spoken(self._signals.singerOutroFinished.emit)
        if not say(tr("还想听吗？那就快去听听歌吧！")):
            self._close_after_singer_outro()
        elif not spoken:
            QTimer.singleShot(2600, self._close_after_singer_outro)

    def _close_after_singer_outro(self):
        self._singer_timer.stop()
        self._singer_show_active = False
        self._alarm_mode = False
        self._apply_player_loops()
        self.player.stop()
        self.player.setSource(QUrl())
        if self.window:
            if not self._singer_show_started_visible:
                self.window.hide()
            self.window.sync()
        if self.lyric_overlay and not self._singer_show_started_visible:
            self.lyric_overlay.hide()
        self._singer_show_started_visible = False

    def play_random(self, duration=None, show_player=True):
        self.refresh_tracks()
        if show_player:
            self.reset_player_volume()
            w = self.ensure_window()
            new_open_session = not w.isVisible() and not w.isMinimized()
            if new_open_session:
                w.begin_open_session()
            w.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            if w.isMinimized():
                w.showNormal()
            else:
                w.show()
            if new_open_session:
                w._dock_to_work_area_bottom()
            w.raise_()
            w.activateWindow()
            w.sync()
        if not self.tracks:
            say(tr("当前没有可播放的音乐，请先上传"))
            return
        self.index = self._pick_random_index()
        self.play(self.tracks[self.index])
        if show_player and self.window:
            self.window.sync()
        else:
            self._singer_timer.start(duration or 30000)

    def _stop_singer(self):
        self._singer_show_active = False
        self.player.stop()
        self.player.setSource(QUrl())

    def stop(self):
        self._singer_timer.stop()
        self._singer_show_active = False
        self._alarm_mode = False
        self._apply_player_loops()
        self.player.stop()
        self.player.setSource(QUrl())

    def stop_alarm(self):
        if self._alarm_mode:
            self.stop()

    def alarm_active(self):
        return self._alarm_mode

    def close_player(self):
        self.stop()
        if self.window:
            self.window.hide()
        if self.lyric_overlay:
            self.lyric_overlay.hide()

    def retranslate_ui(self):
        if self.window:
            self.window.retranslate_ui()
        if self.lyric_overlay:
            self.lyric_overlay.retranslate_ui()

    def leave_activity(self):
        """退出角色状态时停止隐藏短播，保留已打开的播放器窗口。"""
        self._singer_timer.stop()
        if self.window is None or not self.window.isVisible():
            self.stop()

    def upload(self):
        files, _ = QFileDialog.getOpenFileNames(
            None, tr("上传音乐"), "",
            "音频文件 (*.mp3 *.wav *.ogg *.flac *.m4a)"
        )
        if files:
            self.add_files(files)
            if self.window:
                self.window.sync()

    def add_files(self, paths):
        """把给定路径的音频文件复制到用户音乐目录（供拖拽上传调用）。

        仅复制音频文件；返回实际导入的文件列表。
        """
        if not paths:
            return []
        dest = assets.get_music_folder()
        imported = []
        for f in paths:
            if not f or not os.path.exists(f):
                continue
            if not assets.is_audio_file(f):
                continue
            try:
                import shutil
                src = os.path.abspath(f)
                target = os.path.abspath(os.path.join(dest, os.path.basename(f)))
                if self._track_exists_by_path(src):
                    say(tr("歌曲已存在"))
                    continue
                if src == target:
                    imported.append(target)
                    continue
                base, ext = os.path.splitext(target)
                candidate = target
                n = 1
                while os.path.exists(candidate):
                    candidate = f"{base} ({n}){ext}"
                    n += 1
                shutil.copy2(src, candidate)
                imported.append(candidate)
            except Exception:  # noqa: BLE001
                pass
        if imported:
            self.refresh_tracks()
            if self.window:
                self.window.sync()
        return imported

    def _track_exists_by_path(self, path):
        key = _track_dedupe_key(path)
        if not key[0]:
            return False
        for existing in assets.list_music_files() + music_api.list_cached_files():
            if os.path.abspath(existing) == os.path.abspath(path):
                continue
            if _track_dedupe_key(existing) == key:
                return True
        return False
