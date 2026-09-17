"""音乐播放器：支持本地/缓存/在线歌曲的播放、搜索和上传。

音频后端走 app/core/audio_backend 抽象：
- macOS 用系统原生 AVFoundation (AVAudioPlayer)，绕开 QtMultimedia 打包后无声的坑；
- 其它平台沿用 PyQt6.QtMultimedia.QMediaPlayer。
业务层（进度条/歌词/播放列表）无需感知差异。"""

import os
import random
import re
import shutil
import sys
import threading
import ctypes
from ctypes import wintypes

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:  # pragma: no cover
    Style = None
    lazy_pinyin = None

from PyQt6.QtCore import (
    QAbstractAnimation, QEasingCurve, QPoint, QPointF, QRect, QRectF, QUrl, QTimer, Qt, QSize, QThread, QObject,
    QPropertyAnimation, pyqtSignal, QEventLoop, QEvent, QStandardPaths,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QLabel, QPushButton, QScrollArea,
    QLineEdit, QHBoxLayout, QVBoxLayout, QFileDialog, QGraphicsDropShadowEffect, QMenu,
    QSizePolicy, QTextEdit, QPlainTextEdit, QComboBox, QAbstractSpinBox,
)
from PyQt6.QtGui import QBitmap, QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygon, QRegion
try:
    from PyQt6.QtSvg import QSvgRenderer
except ImportError:  # pragma: no cover
    QSvgRenderer = None

from app.core import assets, config, covers, lyrics, music_api
from app.core import audio_meta
from app.core.audio_backend import create_audio_backend
from app.ui.style import UI_FONT_STACK, PRIMARY_FONT  # 平台相关字体栈（macOS 用 PingFang SC，避开缺失的 Microsoft YaHei）

# macOS 使用系统原生 AVFoundation 后端（见 app/core/audio_backend.py），
# 彻底绕开 PyQt6.QtMultimedia 在打包 .app 中后端插件 @rpath 解析失败的坑；
# 其它平台继续用 QMediaPlayer（行为不变）。
IS_MAC = sys.platform == "darwin"
if IS_MAC:
    # 仅 macOS 下才存在这两个符号（audio_backend 模块内定义于 if IS_MAC 块），
    # 避免 Windows 端 import 本模块时因找不到符号而 ImportError。
    from app.core.audio_backend import AVAudioBackend, _MacAudioShim
from app.core.voice import say
from app.core.i18n import tr
from app.ui.context_menu import MENU_QSS


PLAYER_QSS = ("""
QWidget#playerCard {
    background: #fffaf5;
    border: 1px solid rgba(255,255,255,0.86);
    border-radius: 20px;
    font-family: {ui_font};
}
QLabel#trackTitle { color: #3d2b1f; font-size: 14px; font-weight: 800; }
QLabel#artist { color: #a08e7a; font-size: 11px; font-weight: 500; }
QLabel#lyricText { color: #f97510; font-size: 11px; font-weight: 500; }
QLabel#noticeText {
    color: rgba(95, 95, 95, 0.58);
    font-size: 11px;
    font-weight: 500;
}
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
QWidget#dropOverlay {
    background: #fffaf5;
    border-radius: 20px;
    font-family: {ui_font};
}
QLabel#dropMessage { color: #3d2b1f; font-size: 15px; font-weight: 800; }
QPushButton#dropPrimary, QPushButton#dropSecondary {
    border-radius: 10px;
    font-size: 13px;
    font-weight: 700;
    min-height: 34px;
    padding: 0 20px;
}
QPushButton#dropPrimary { background: #f97510; border: none; color: #fff; }
QPushButton#dropPrimary:hover { background: #ff8a2a; }
QPushButton#dropSecondary { background: rgba(160,142,122,0.10); border: none; color: #6b5744; }
QPushButton#dropSecondary:hover { background: rgba(160,142,122,0.18); }
QScrollArea#playlist {
    background: transparent;
    border: none;
    outline: 0;
}
/* 不透明窗口合成下，viewport 与行内 QLabel 默认 QPalette::Window 是不透明色（黑色/系统色），
   会遮住 PlayerCard 的米白 + bubu 玩偶。显式 transparent，让父级像素透出。 */
QScrollArea#playlist > QWidget,
QLabel#trackNum, QLabel#trackDuration, QLabel#trackName { background: transparent; }
QWidget#playlistBody { background: transparent; }
QWidget#trackRow { background: transparent; border-radius: 8px; }
QWidget#trackRow:hover { background: rgba(249,117,16,0.10); }
QWidget#trackRow[playing="true"] { background: rgba(249,117,16,0.10); }
QLabel#trackNum { color: #a08e7a; font-family: Consolas, 'Cascadia Code', monospace; font-size: 12px; font-weight: 700; }
QLabel#trackName { color: #3d2b1f; font-size: 13px; font-weight: 500; }
QLabel#trackDuration { color: #000000; font-family: Consolas, 'Cascadia Code', monospace; font-size: 12px; font-weight: 600; }
QWidget#trackRow[playing="true"] QLabel#trackNum,
QWidget#trackRow[playing="true"] QLabel#trackName { color: #f97510; }
QPushButton#rowDel { background: transparent; border: none; color: #b9a892; font-size: 15px; font-weight: 700; border-radius: 6px; padding: 0; }
QPushButton#rowDel:hover { background: rgba(229,57,53,0.12); color: #e53935; }
QPushButton#rowFav { background: transparent; border: none; color: #c9b8a6; font-size: 14px; border-radius: 6px; padding: 0; }
QPushButton#rowFav[faved="true"] { color: #f97510; }
QPushButton#rowFav:hover { background: rgba(249,117,16,0.12); color: #f97510; }
QScrollBar:vertical { width: 4px; background: transparent; margin: 4px 0; }
QScrollBar::handle:vertical { background: rgba(160,142,122,0.42); border-radius: 2px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
""").replace("{ui_font}", UI_FONT_STACK)

PLAYER_W = 336
PLAYER_H = 280
PLAYER_EXPANDED_H = 548
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

HEART_SVG = """<svg viewBox='0 0 1024 1024' xmlns='http://www.w3.org/2000/svg'>
<path d='M881.664 132.096c-69.632-69.632-167.936-97.28-263.168-75.776-22.528 5.12-35.84 26.624-30.72 49.152s26.624 35.84 49.152 30.72c67.584-15.36 137.216 4.096 186.368 53.248C926.72 292.864 926.72 460.8 823.296 563.2L512 875.52 199.68 564.224c-102.4-103.424-102.4-271.36 0-373.76 77.824-77.824 204.8-77.824 282.624 0l69.632 69.632c8.192 8.192 77.824 76.8 150.528 76.8h5.12c30.72-1.024 57.344-15.36 77.824-39.936 14.336-17.408 11.264-43.008-6.144-57.344-17.408-14.336-43.008-11.264-57.344 6.144-6.144 8.192-12.288 9.216-17.408 10.24-26.624 2.048-70.656-29.696-93.184-53.248L541.696 133.12c-109.568-109.568-288.768-109.568-399.36 0C7.168 268.288 7.168 487.424 142.336 622.592L483.328 962.56c8.192 8.192 18.432 12.288 28.672 12.288 10.24 0 20.48-4.096 28.672-12.288l340.992-340.992c65.536-65.536 101.376-152.576 101.376-244.736 0-92.16-35.84-179.2-101.376-244.736z' fill='#606060'/>
<path d='M240.64 233.472c-33.792 30.72-50.176 76.8-50.176 136.192 0 22.528 18.432 40.96 40.96 40.96s40.96-18.432 40.96-40.96c0-34.816 8.192-60.416 23.552-74.752 18.432-17.408 44.032-16.384 46.08-16.384 22.528 2.048 41.984-15.36 44.032-37.888 2.048-22.528-15.36-41.984-37.888-44.032-7.168-1.024-63.488-4.096-107.52 36.864z' fill='#606060'/>
</svg>"""


def _default_lyric() -> str:
    return tr("把这一句留在今天")


def _marked_lyric(text: str) -> str:
    text = (text or _default_lyric()).strip()
    return LYRIC_MARK + text.lstrip("♪ ")


def _rounded_pixmap(path: str, size: QSize, radius: int = 18) -> QPixmap:
    src = QPixmap(path or "")
    if src.isNull() or size.width() <= 0 or size.height() <= 0:
        return QPixmap()
    scaled = src.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    x = max(0, (scaled.width() - size.width()) // 2)
    y = max(0, (scaled.height() - size.height()) // 2)
    cropped = scaled.copy(x, y, size.width(), size.height())
    out = QPixmap(size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path_clip = QPainterPath()
    path_clip.addRoundedRect(QRectF(out.rect()), radius, radius)
    painter.setClipPath(path_clip)
    painter.drawPixmap(0, 0, cropped)
    painter.end()
    return out


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


def _pinyin_words(value: str) -> list[str]:
    value = " ".join(str(value or "").split()).strip()
    if not value:
        return []
    if lazy_pinyin is None:
        return [value.lower()]
    return [word.lower() for word in lazy_pinyin(value, errors="default") if word]


def _sort_text_key(value: str) -> tuple[int, str, str, str]:
    raw = " ".join(str(value or "").split()).strip()
    if not raw:
        return 1, "", "", ""
    if lazy_pinyin is not None and Style is not None:
        initial_words = lazy_pinyin(raw[0], style=Style.FIRST_LETTER, errors="default")
        initial = (initial_words[0] if initial_words else raw[0]).lower()
    else:
        initial = raw[0].lower()
    full = "".join(_pinyin_words(raw)) or _dedupe_text(raw)
    return 0, initial[:1], full, raw.lower()


def _invert_text(value: str) -> tuple[int, ...]:
    return tuple(-ord(ch) for ch in value)


def _sort_text_key_desc(value: str) -> tuple[int, tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    empty, initial, full, raw = _sort_text_key(value)
    return empty, _invert_text(initial), _invert_text(full), _invert_text(raw)


def _track_sort_title(path: str) -> str:
    return _track_title(path)


def _track_sort_artist(path: str) -> str:
    return _split_track_artist(path)[1]


PLAYLIST_SORT_MODES = {"title_asc", "title_desc", "artist_asc", "artist_desc", "added", "plays"}


def _playlist_sort_mode() -> str:
    mode = config.settings.get("playlistSort", "title_asc")
    return mode if mode in PLAYLIST_SORT_MODES else "title_asc"


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
    # 原先每首歌都新建 QMediaPlayer + 阻塞式 QEventLoop 探测时长（最长 500ms/首且冻结主线程），
    # 曲库较大或每次 refresh 时会造成明显卡顿、列表滑动掉帧。
    # 改用 app/core/audio_meta.py 的文件头解析：不解码音频、不依赖 Qt、带磁盘缓存，
    # 可在主线程安全调用；本函数只做格式化，返回字符串与原实现一致。
    try:
        if path and os.path.exists(path):
            secs = audio_meta.get_duration(path)
            if secs:
                s = int(secs)
                return f"{s // 60:02d}:{s % 60:02d}"
    except Exception:  # noqa: BLE001
        pass
    # 回退：audio_meta 未覆盖的格式（如 ogg / ape 等）探测一次。
    # macOS 用原生 AVAudioPlayer（duration 在加载后即可同步拿到，无需事件循环）；
    # 其它平台沿用 QMediaPlayer 探测。仅这类个别文件有开销，不影响整体流畅度。
    try:
        if not os.path.exists(path):
            return "--:--"
        if IS_MAC:
            probe = AVAudioBackend()
            probe.setSource(QUrl.fromLocalFile(path))
            ms = probe.duration()
        else:
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
        if ms and ms > 0:
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
        # 固定 hover 位置：让胡萝卜尖精确落在小专辑图左上角。
        # 计算依据（assets/carrot_hover.png 652x570）：
        #   - 按 QSize(138,102) + KeepAspectRatio 缩放后实际约 138x120.6；
        #   - 最低点（底部尖）在原始图中约 (559.5, 569)，缩放后约 (118.4, 120.4)；
        #   - 预览窗中萝卜以 (234,210) 为中心、旋转 -4° 绘制；
        #   - 综合后萝卜尖在预览窗本地坐标约 (279, 273)。
        # 叠加手感微调：再往左 11px、往下合计 23px。
        # 因此预览窗左上角 = 小专辑图左上角 - (290, 250)。
        pos = self.mapToGlobal(QPoint(-290, -250))
        screen = QApplication.screenAt(self.mapToGlobal(self.rect().center())) or self.screen() or QApplication.primaryScreen()
        if screen is None:
            return pos
        geo = screen.availableGeometry()
        preview_w, preview_h = 352, 358
        x = max(geo.left() + 8, min(pos.x(), geo.right() - preview_w - 8 + 1))
        y = max(geo.top() + 8, min(pos.y(), geo.bottom() - preview_h - 8 + 1))
        return QPoint(x, y)

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
        if not self._pixmap.isNull():
            if self._preview is None:
                self._preview = CoverPreviewWindow()
            self._preview.show_cover_pixmap(self._pixmap, self._preview_pos(), self._source_rect())
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
        self._pixmap_key = 0
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
        pix = QPixmap(path)
        if pix.isNull():
            return
        self.show_cover_pixmap(pix, pos, source_rect)

    def show_cover_pixmap(self, pix, pos, source_rect=None):
        full_geometry = QRect(pos, self.PREVIEW_SIZE)
        pix_key = pix.cacheKey() if hasattr(pix, "cacheKey") else 0
        if self.isVisible() and not self._closing and self._pixmap_key == pix_key and self._full_geometry == full_geometry:
            return
        self._closing = False
        self._anim.stop()
        self._fade.stop()
        self._path = ""
        self._pixmap = QPixmap(pix)
        self._pixmap_key = pix_key
        self._shadow = _pixmap_theme_color(pix)
        self._full_geometry = full_geometry
        # hover 固定出现在最终位置，不做从小专辑图展开的位移动画，
        # 只保留透明度渐变，避免视觉上“滑动”。
        self._collapsed_geometry = full_geometry
        self.setGeometry(self._full_geometry)
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
        active_kinds = {"loop_one", "shuffle", "muted", "heart_filled"}
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
        elif self.kind in {"heart", "heart_filled"}:
            self._paint_svg(p, HEART_SVG, color, pad=8)
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
        svg = (
            svg_text
            .replace("#606060", color.name())
            .replace("#333C4F", color.name())
            .replace("#000000", color.name())
        ).encode("utf-8")
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


class NoticeLabel(QLabel):
    def __init__(self):
        super().__init__()
        self._raw_text = ""
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_notice_text(self, text: str):
        self._raw_text = text or ""
        self.setToolTip(self._raw_text)
        self._update_elided()

    def resizeEvent(self, e):  # noqa: N802
        self._update_elided()
        super().resizeEvent(e)

    def _update_elided(self):
        if not self._raw_text:
            super().setText("")
            return
        width = max(1, self.width() - 8)
        super().setText(self.fontMetrics().elidedText(self._raw_text, Qt.TextElideMode.ElideRight, width))


class TrackItemWidget(QWidget):
    clicked = pyqtSignal(object)
    deleteRequested = pyqtSignal(str)
    favoriteRequested = pyqtSignal(str, object, object)  # (source, path, payload)
    downloadRequested = pyqtSignal(object, str)
    addRemoteRequested = pyqtSignal(object)
    saveAsRequested = pyqtSignal(int)

    def __init__(self, number, title, duration, index, playing=False, source="local", payload=None, favorited=False):
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
        self.fav_btn = QPushButton("♡")
        self.fav_btn.setObjectName("rowFav")
        self.fav_btn.setFixedSize(20, 20)
        self.fav_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fav_btn.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, True)
        self.fav_btn.clicked.connect(self._on_fav_clicked)
        self.fav_btn.hide()
        row.addWidget(self.fav_btn)
        self.del_btn = QPushButton("×")
        self.del_btn.setObjectName("rowDel")
        self.del_btn.setFixedSize(20, 20)
        self.del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.del_btn.setToolTip(tr("删除"))
        self.del_btn.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, True)
        self.del_btn.clicked.connect(self._on_del_clicked)
        self.del_btn.hide()
        row.addWidget(self.del_btn)
        self._set_faved(favorited)
        self._press_timer = QTimer(self)
        self._press_timer.setSingleShot(True)
        self._press_timer.timeout.connect(self._emit_click)
        self._press_payload = self.payload if self.source == "remote" else self.index

    def sizeHint(self):  # noqa: N802
        return QSize(0, TRACK_ROW_H)

    def minimumSizeHint(self):  # noqa: N802
        return QSize(0, TRACK_ROW_H)

    def enterEvent(self, e):  # noqa: N802
        self.name_label.start_marquee()
        self.fav_btn.show()
        if self.source in ("local", "cache"):
            self.del_btn.show()
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self.name_label.stop_marquee()
        self.fav_btn.hide()
        self.del_btn.hide()
        super().leaveEvent(e)

    def _row_path(self):
        if isinstance(self.payload, dict):
            return self.payload.get("cache_path") or self.payload.get("path")
        if isinstance(self.payload, str):
            return self.payload
        return None

    def _set_faved(self, faved):
        self._faved = bool(faved)
        self.fav_btn.setText("♥" if self._faved else "♡")
        self.fav_btn.setProperty("faved", "true" if self._faved else "false")
        self.fav_btn.setToolTip(tr("已添加到我喜欢") if self._faved else tr("添加到我喜欢"))
        self.fav_btn.style().unpolish(self.fav_btn)
        self.fav_btn.style().polish(self.fav_btn)

    def _on_fav_clicked(self):
        self.favoriteRequested.emit(self.source, self._row_path(), self.payload)

    def _on_del_clicked(self):
        path = self._row_path()
        if path:
            self.deleteRequested.emit(path)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_timer.start(QApplication.doubleClickInterval())
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            if self._press_timer.isActive():
                self._press_timer.stop()
            self._emit_click()
            e.accept()
            return
        super().mouseDoubleClickEvent(e)

    def _emit_click(self):
        self.clicked.emit(self._press_payload)

    def _add_download_menu(self, menu, payload):
        download_menu = menu.addMenu(tr("下载"))
        download_menu.setStyleSheet(menu.styleSheet())
        download_menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        download_menu.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        for br in music_api.quality_options(payload):
            action = download_menu.addAction(br)
            action.setData(("download", payload, br))
        return download_menu

    def _add_sort_menu(self, menu):
        sort_menu = menu.addMenu(tr("排序"))
        sort_options = (
            ("title_asc", "歌名（A-Z）"),
            ("title_desc", "歌名（Z-A）"),
            ("artist_asc", "歌手（A-Z）"),
            ("artist_desc", "歌手（Z-A）"),
            ("added", "添加时间"),
            ("plays", "播放次数"),
        )
        current_sort = _playlist_sort_mode()
        for sort_key, label_key in sort_options:
            sort_action = sort_menu.addAction(tr(label_key))
            sort_action.setCheckable(True)
            sort_action.setChecked(current_sort == sort_key)
            sort_action.setData(("sort", sort_key))
        return sort_menu

    def contextMenuEvent(self, e):  # noqa: N802
        if self.source == "status":
            e.accept()
            return
        player_window = self.window()
        music = getattr(player_window, "music", None)
        row_index = self.index
        row_payload = dict(self.payload or {}) if isinstance(self.payload, dict) else self.payload
        row_source = self.source
        row_path = None
        if isinstance(row_payload, dict):
            row_path = row_payload.get("cache_path") or row_payload.get("path")
        elif isinstance(row_payload, str):
            row_path = row_payload
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
            add_favorite = None
            if self.source == "remote":
                self._add_download_menu(menu, self.payload or {})
                self._add_sort_menu(menu)
                add_favorite = menu.addAction(tr("添加到我喜欢"))
                add_remote = menu.addAction(tr("添加到播放列表"))
            elif self.source == "cache":
                self._add_download_menu(menu, self.payload or {})
                self._add_sort_menu(menu)
                delete = menu.addAction(tr("删除"))
                add_favorite = menu.addAction(tr("添加到我喜欢"))
            else:
                save_as = menu.addAction(tr("另存为"))
                self._add_sort_menu(menu)
                delete = menu.addAction(tr("删除"))
                add_favorite = menu.addAction(tr("添加到我喜欢"))
            action = menu.exec(e.globalPos())
            data = action.data() if action is not None else None
            if isinstance(data, tuple) and data[0] == "download":
                if music is not None:
                    music.download_remote(dict(data[1] or {}), data[2])
            elif isinstance(data, tuple) and data[0] == "sort":
                if player_window is not None and hasattr(player_window, "set_playlist_sort"):
                    player_window.set_playlist_sort(data[1])
            elif action == add_remote:
                if music is not None and row_source == "remote":
                    music.cache_remote(dict(row_payload or {}))
            elif action == add_favorite:
                if music is not None:
                    if row_source == "remote":
                        music.favorite_remote(dict(row_payload or {}))
                    elif row_source == "cache" and row_path:
                        music.favorite_cached(row_path)
                    elif row_path:
                        music.add_favorite_track(row_path)
            elif action == save_as:
                if music is not None and row_path:
                    music.save_as_track_path(row_path)
            elif action == delete:
                if music is not None and row_path:
                    if getattr(music, "favorite_mode", False):
                        QTimer.singleShot(0, lambda m=music, p=row_path: m.remove_favorite_track(p))
                    else:
                        QTimer.singleShot(0, lambda m=music, p=row_path: m.delete_track_path_and_sync(p, remove_sidecars=True))
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
        self._fill_color = QColor("#fffaf5")

    def set_expanded(self, expanded):
        self.expanded = expanded
        self.update()

    def paintEvent(self, e):  # noqa: N802
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 20, 20)
        p.fillPath(clip, self._fill_color)
        p.setClipPath(clip)
        p.setOpacity(0.62)
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
        self._self_pid = os.getpid()
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
        # 仅在 AT小PP 自己的窗口处于前台时才响应全局空格，
        # 避免用户在其它软件（如聊天、办公、浏览器输入框）打字时被误触发。
        if not self._foreground_is_self():
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

    def _foreground_is_self(self):
        """判断当前前台窗口是否属于本应用进程。"""
        try:
            user32 = ctypes.windll.user32
            foreground = user32.GetForegroundWindow()
            if not foreground:
                return False
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(foreground, ctypes.byref(pid))
            return pid.value == self._self_pid
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
        # 用户明确要求列表区完全透明，让 PlayerCard 的米白 + bubu 完整透出
        # （包括歌名区下方的橙身/眼睛）。因此 MarqueeLabel 不再 fillRect 清底——
        # 代价是跑马灯长标题时仍可能闪现灰色乱码堆（这是用户接受的取舍）。
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
        text = _marked_lyric(text)
        progress = max(0.0, min(1.0, float(progress)))
        if text == self._text and progress == self._progress:
            # 内容未变不重绘：sync() 每 250ms 被调用一次，暂停/歌词未推进时
            # 减少半透明窗口的无谓重绘（每次重绘都是一次残影风险窗口）
            return
        self._text = text
        self._progress = progress
        # repaint() 同步立即重绘；macOS 半透明 layer-backed 窗口上 update() 的
        # 异步脏区合并可能让中间帧/旧帧参与合成，同步绘制更确定
        self.repaint()
        self._repaint_host_window()

    def set_font_size(self, size):
        size = max(16, min(46, int(size)))
        if size == self._font_size:
            return
        self._font_size = size
        self.repaint()
        self._repaint_host_window()

    def _repaint_host_window(self):
        """强制整个顶层窗口重绘。

        macOS 半透明（WA_TranslucentBackground）窗口在「局部 update」时可能保留
        上一帧像素 → 调整字体大小后出现新旧文字叠加的重影。整窗重绘可彻底清底。
        """
        win = self.window()
        if win is not None:
            win.update()

    def font_size(self):
        return self._font_size

    def set_accent(self, color):
        if color.isValid() and QColor(color) != self._accent:
            self._accent = QColor(color)
            self.repaint()

    def accent(self):
        return QColor(self._accent)

    def paintEvent(self, e):  # noqa: N802
        # 离屏整帧渲染：先画到一张全新的 QImage（绝无旧帧），再用 Source 合成模式
        # 整体替换本控件区域像素。背景（run#10 修复）：macOS Qt6 layer-backed +
        # WA_TranslucentBackground 半透明窗口上，「Clear 擦底 + SourceOver 画字」
        # 擦不净 backing store 残留，调歌词(L+/L-)/调字号后旧帧文字与新字叠加成重影。
        # CompositionMode_Source 的 drawImage 不与旧帧做 SourceOver 叠加，而是逐像素
        # 替换（含透明像素），上一帧像素根本不参与本帧合成——重影失去存在前提。
        text = self._text.strip() or _marked_lyric(_default_lyric())
        font = QFont(PRIMARY_FONT, self._font_size)
        font.setWeight(QFont.Weight.DemiBold)
        img = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
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
        if self._progress > 0:
            grad = QLinearGradient(0, 0, self.width(), 0)
            grad.setColorAt(0.0, self._accent)
            grad.setColorAt(0.68, QColor("#ffb25a"))
            grad.setColorAt(1.0, QColor("#ffffff"))
            p.setClipRect(visible_rect.intersected(QRectF(x, 0, text_width * self._progress, self.height())))
            p.setBrush(grad)
            p.drawPath(text_path)
        p.restore()
        p.end()
        out = QPainter(self)
        # Source 模式整体替换本区域像素（透明像素同样替换），不与旧帧叠加
        out.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        out.drawImage(0, 0, img)
        out.end()


class LyricOverlayWindow(QDialog):
    BASE_W = 730
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

    def paintEvent(self, e):  # noqa: N802
        # 第二重保险：半透明悬浮窗每帧先丢弃上一帧整帧像素，防止 macOS
        # layer-backed 窗口局部更新时旧帧从歌词/按钮区域外透出（残影）。
        # 本窗口背景即透明（全局 QSS QDialog{background:transparent}），
        # 清空后不补画背景，与原视觉完全一致。
        super().paintEvent(e)
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.end()

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
        self.lyric_plus_b = QPushButton("L+")
        self.lyric_minus_b = QPushButton("L-")
        self.color_b = IconButton("palette", 30)
        self._icon_buttons = [self.loop_b, self.prev_b, self.play_b, self.next_b, self.color_b]
        for b in (self.loop_b, self.prev_b, self.play_b, self.next_b, self.color_b):
            b.setProperty("plainOverlay", True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet("QPushButton { background: transparent; border: none; } QPushButton:hover { background: transparent; border: none; }")
        for b in (self.font_up_b, self.font_down_b, self.lyric_plus_b, self.lyric_minus_b):
            b.setObjectName("toolBtn")
            b.setFixedSize(48, 26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet("""
QPushButton#toolBtn {
    background: transparent;
    border: none;
    color: #f97510;
    font-family: {ui_font};
    font-size: 16px;
    font-weight: 800;
    padding: 0;
}
QPushButton#toolBtn:hover { color: #ff9a3d; }
""".replace("{ui_font}", UI_FONT_STACK))
        self._font_buttons = [self.font_up_b, self.font_down_b, self.lyric_plus_b, self.lyric_minus_b]
        self.loop_b.setToolTip(tr("循环模式"))
        self.prev_b.setToolTip(tr("上一首"))
        self.play_b.setToolTip(tr("播放/暂停"))
        self.next_b.setToolTip(tr("下一首"))
        self.color_b.setToolTip(tr("歌词颜色"))
        self.lyric_plus_b.setToolTip(tr("歌词前进 0.5 秒"))
        self.lyric_minus_b.setToolTip(tr("歌词后退 0.5 秒"))
        self.loop_b.clicked.connect(self.music.cycle_loop)
        self.prev_b.clicked.connect(self.music.prev)
        self.play_b.clicked.connect(self.music.toggle_play)
        self.next_b.clicked.connect(self.music.next)
        self.font_up_b.clicked.connect(lambda: self.lyric.set_font_size(self.lyric.font_size() + 2))
        self.font_down_b.clicked.connect(lambda: self.lyric.set_font_size(self.lyric.font_size() - 2))
        self.lyric_plus_b.clicked.connect(lambda: self._shift_current_lyric(500))
        self.lyric_minus_b.clicked.connect(lambda: self._shift_current_lyric(-500))
        self.color_b.clicked.connect(self._toggle_palette)
        for b in (self.loop_b, self.prev_b, self.play_b, self.next_b, self.font_up_b, self.font_down_b, self.lyric_plus_b, self.lyric_minus_b, self.color_b):
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
    font-family: {UI_FONT_STACK};
    font-size: {max(12, int(16 * s))}px;
    font-weight: 800;
    padding: 0;
}}
QPushButton#toolBtn:hover {{ color: #ff9a3d; }}
""")
        for swatch in self._swatches:
            swatch.setFixedSize(int(18 * s), int(18 * s))
        self.lyric.setMinimumSize(int(560 * s), int(46 * s))
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

    def _shift_current_lyric(self, delta_ms):
        if not self.music.shift_current_lyric(delta_ms):
            return
        self.sync()
        self.music.force_refresh_lyric_render()

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
        self.lyric_plus_b.setToolTip(tr("歌词前进 0.5 秒"))
        self.lyric_minus_b.setToolTip(tr("歌词后退 0.5 秒"))
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
        self._playlist_render_pending = False
        self._pending_drop_files = []
        self._drop_image_name = "drop_upload_prompt"
        self._refresh_timer = None  # 曲库刷新 debounce 定时器（见 _schedule_library_refresh）
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        # 圆角改用「不透明窗口 + 遮罩」实现，不再使用 WA_TranslucentBackground：
        # 在 translucent 窗口下，子控件的 background: transparent 会「透到桌面」而不是
        # 透到父控件，导致列表区直接显示桌面壁纸/图标，而不是 PlayerCard 的米白 + bubu 玩偶。
        # 改为不透明窗口后，子控件的 transparent 会正确借到父控件（PlayerCard 米白+bubu）的像素；
        # 圆角外的像素由遮罩排除、不予绘制，视觉上仍是「圆角卡片浮在桌面」。
        # 只影响「窗口如何合成到屏幕」，不改动任何颜色/样式/布局。
        self.setAcceptDrops(True)
        self.setFixedSize(PLAYER_W, PLAYER_H)
        self._apply_window_mask()
        self._build()
        self._disable_default_buttons()
        self.installEventFilter(self)
        self.remoteSearchDone.connect(self._on_remote_search_done)
        self.remotePlayReady.connect(self._on_remote_play_ready)
        self.remoteDownloadReady.connect(self._on_remote_download_ready)
        music.player.positionChanged.connect(self._on_pos)
        music.player.durationChanged.connect(self._on_dur)

    def _apply_window_mask(self, radius: int = 20):
        """用 QBitmap 遮罩为窗口做圆角（配合「不透明窗口」使用）。

        QRegion 不直接支持圆角矩形（只有 Rectangle / Ellipse），所以先在 QBitmap 上
        画一个圆角实心矩形，再转成 QRegion 作为遮罩：遮罩内正常绘制、遮罩外不绘制
        （透出桌面），从而得到与原先 translucent 窗口一致的圆角外观。

        圆角半径与 PlayerCard.paintEvent 的 addRoundedRect(20, 20) 保持一致。
        本方法只影响「窗口如何合成到屏幕」，不触碰任何颜色/样式/布局。
        """
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        mask = QBitmap(QSize(w, h))
        mask.clear()
        p = QPainter(mask)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(Qt.BrushStyle.SolidPattern)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), radius, radius)
        p.end()
        self.setMask(QRegion(mask))

    def closeEvent(self, event):
        if getattr(self.music, "_closing", False):
            event.accept()
            return
        self.music.close_player()
        event.ignore()

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
        self.back_b.setToolTip(tr("最小化"))
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
        body.addSpacing(8)

        self.notice = NoticeLabel()
        self.notice.setObjectName("noticeText")
        self.notice.setMinimumHeight(16)
        self.notice.set_notice_text(tr("仅供学习交流使用，请支持正版音乐！"))
        body.addWidget(self.notice)
        body.addSpacing(10)

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
        self.favorite_b = IconButton("heart", 36)
        self.favorite_b.setObjectName("uploadBtn")
        self.favorite_b.setToolTip(tr("我喜欢的歌曲"))
        self.favorite_b.clicked.connect(self.music.toggle_favorite_mode)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(7)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.search_b)
        search_row.addWidget(self.favorite_b)
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
        self._build_drop_overlay()

    def _build_drop_overlay(self):
        self.drop_overlay = QWidget(self.card)
        self.drop_overlay.setObjectName("dropOverlay")
        self.drop_overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self.drop_overlay)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        layout.addStretch(1)
        self.drop_image = QLabel()
        self.drop_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.drop_image)
        self.drop_message = QLabel()
        self.drop_message.setObjectName("dropMessage")
        self.drop_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_message.setWordWrap(True)
        layout.addWidget(self.drop_message)
        self.drop_buttons = QWidget()
        btn_row = QHBoxLayout(self.drop_buttons)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        self.drop_yes_b = QPushButton(tr("是"))
        self.drop_yes_b.setObjectName("dropPrimary")
        self.drop_no_b = QPushButton(tr("否"))
        self.drop_no_b.setObjectName("dropSecondary")
        self.drop_yes_b.clicked.connect(self._confirm_drop_upload)
        self.drop_no_b.clicked.connect(self._cancel_drop_upload)
        btn_row.addWidget(self.drop_yes_b)
        btn_row.addWidget(self.drop_no_b)
        btn_row.addStretch(1)
        layout.addWidget(self.drop_buttons)
        layout.addStretch(1)
        self.drop_overlay.hide()
        self._layout_drop_overlay()

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

    def _layout_drop_overlay(self):
        if not hasattr(self, "drop_overlay"):
            return
        self.drop_overlay.setGeometry(self.card.rect())
        if hasattr(self, "drop_image"):
            image_h = 168 if self.height() <= PLAYER_H + 12 else 230
            self.drop_image.setFixedHeight(image_h)
            if self.drop_overlay.isVisible():
                img = assets.find_image(self._drop_image_name)
                self.drop_image.setPixmap(_rounded_pixmap(img or "", QSize(286, image_h), 16))

    def resizeEvent(self, e):  # noqa: N802
        self._layout_drop_overlay()
        self._apply_window_mask()
        super().resizeEvent(e)

    def _dropped_local_files(self, event):
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        paths = []
        for url in mime.urls():
            if url.isLocalFile():
                paths.append(url.toLocalFile())
        return paths

    def _is_supported_drop_audio(self, path):
        if not path or os.path.splitext(path)[1].lower() == ".mp4":
            return False
        return assets.is_audio_file(path)

    def dragEnterEvent(self, event):  # noqa: N802
        if self._dropped_local_files(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        if self._dropped_local_files(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):  # noqa: N802
        files = self._dropped_local_files(event)
        if not files:
            event.ignore()
            return
        event.acceptProposedAction()
        self.music.pause_for_drop()
        audio_files = [p for p in files if self._is_supported_drop_audio(p)]
        if audio_files:
            self._pending_drop_files = audio_files
            self._show_drop_overlay("是否上传该歌曲", "drop_upload_prompt", show_buttons=True)
        else:
            self._pending_drop_files = []
            self._show_drop_overlay(
                "我暂时不支持上传这种文件捏~",
                "drop_upload_prompt",
                show_buttons=False,
                auto_restore=True,
                restore_delay_ms=750,
            )

    def _show_drop_overlay(self, message_key, image_name, show_buttons=False, auto_restore=False, restore_delay_ms=2000):
        """显示拖放提示浮层。

        message_key 为 i18n 文案 key：在此统一翻译并记录，切换界面语言时
        浮层提示语与按钮可随 retranslate_ui 一起刷新（修复英文模式提示词残留中文）。
        """
        self._drop_image_name = image_name
        self._drop_message_key = message_key
        self.drop_message.setText(tr(message_key))
        self.drop_buttons.setVisible(show_buttons)
        img = assets.find_image(image_name)
        pix = _rounded_pixmap(img or "", QSize(286, 168), 16)
        self.drop_image.setPixmap(pix)
        self.drop_overlay.raise_()
        self.drop_overlay.show()
        if auto_restore:
            QTimer.singleShot(restore_delay_ms, self._hide_drop_overlay)

    def _hide_drop_overlay(self):
        self.drop_overlay.hide()
        self._pending_drop_files = []

    def _cancel_drop_upload(self):
        self._hide_drop_overlay()

    def _confirm_drop_upload(self):
        files = list(self._pending_drop_files)
        if not files:
            self._hide_drop_overlay()
            return
        imported = self.music.add_files(files)
        self._pending_drop_files = []
        if imported:
            self._show_drop_overlay("上传成功！", "drop_upload_success", show_buttons=False, auto_restore=True, restore_delay_ms=750)
        else:
            self._show_drop_overlay("歌曲已存在", "drop_upload_prompt", show_buttons=False, auto_restore=True)

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
        self.playlist_panel.setVisible(self._expanded)
        self.card.set_expanded(self._expanded)
        self.setFixedSize(PLAYER_W, PLAYER_EXPANDED_H if self._expanded else PLAYER_H)
        if self._auto_dock_enabled:
            self._dock_to_work_area_bottom()
        if self._expanded:
            self._render_playlist_soon()

    def _render_playlist_soon(self):
        if self._playlist_render_pending:
            return
        self._playlist_render_pending = True
        QTimer.singleShot(0, self._render_playlist_now)

    def _render_playlist_now(self):
        self._playlist_render_pending = False
        if self._expanded:
            self._filter(self._search_query, refresh=False)

    def perform_search(self):
        query = " ".join(self.search.text().split())
        self._search_query = query
        self._remote_query = ""
        self._remote_results = []
        self._remote_page = -1
        self._remote_has_more = False
        self._remote_error = ""
        self._filter(query)
        if query and not self.music.favorite_mode:
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
            if error == "network":
                say(tr("无法连接音乐服务，请检查网络后重试"))
            elif error == "empty":
                say(tr("这首歌暂时没有完整版资源"))
            elif error == "restricted":
                say(tr("该歌曲暂无版权"))
            else:
                say(tr("播放出错噜"))
            return
        # 搜索进行中：缓存播放完成时不重渲染列表，保持用户当前浏览位置
        self.music.play_cached(payload, sync_ui=not bool(self._search_query))

    def _on_remote_download_ready(self, payload, error):
        if error:
            if error == "歌曲已存在":
                say(tr("歌曲已存在"))
                return
            if error == "network":
                say(tr("无法连接音乐服务，请检查网络后重试"))
                return
            if error == "empty":
                say(tr("这首歌暂时没有完整版资源"))
                return
            if error == "restricted":
                say(tr("该歌曲暂无版权"))
                return
            say(tr("下载出错噜"))
            return
        remove_cache_path = (payload or {}).get("remove_cache_path")
        if remove_cache_path:
            self.music.delete_track_path(remove_cache_path, remove_sidecars=False)
        if (payload or {}).get("add_favorite") and (payload or {}).get("path"):
            self.music.add_favorite_track(payload.get("path"), announce=False)
        # 短时间内连续下载时，每个完成回调都 refresh_tracks()（全量磁盘扫描 + 时长解析）
        # 再 sync()（销毁重建所有行控件），主线程被反复占满 → 列表滑动掉帧。
        # 改用 300ms debounce 把多次「下载完成」合并成一次刷新。
        self._schedule_library_refresh()
        say(tr("已添加到我喜欢") if (payload or {}).get("add_favorite") else tr("下载完成"))

    def _schedule_library_refresh(self):
        """合并短时间内的多次曲库刷新请求为一次（300ms debounce）。"""
        if self._refresh_timer is None:
            self._refresh_timer = QTimer(self)
            self._refresh_timer.setSingleShot(True)
            self._refresh_timer.timeout.connect(self._flush_library_refresh)
        self._refresh_timer.start(300)

    def _flush_library_refresh(self):
        self.music.refresh_tracks()
        # 搜索进行中：不重建播放列表，避免下载完成把列表跳回顶部、打断浏览；
        # 底层数据已刷新，最终列表在清空搜索框时统一呈现。
        if not self._search_query:
            self.sync()

    def _sorted_tracks(self, tracks):
        sort_mode = _playlist_sort_mode()
        if sort_mode == "added":
            return sorted(
                tracks,
                key=lambda p: (
                    -(int((music_api.cache_info(p) or {}).get("created") or 0)),
                    _sort_text_key(_track_sort_title(p)),
                    p,
                ),
            )
        if sort_mode == "title_desc":
            return sorted(
                tracks,
                key=lambda p: (_sort_text_key_desc(_track_sort_title(p)), p),
            )
        if sort_mode == "artist_asc":
            return sorted(tracks, key=lambda p: (_sort_text_key(_track_sort_artist(p)), _sort_text_key(_track_sort_title(p)), p))
        if sort_mode == "artist_desc":
            return sorted(tracks, key=lambda p: (_sort_text_key_desc(_track_sort_artist(p)), _sort_text_key(_track_sort_title(p)), p))
        if sort_mode == "plays":
            play_counts = config.settings.get("trackPlayCounts", {}) or {}
            return sorted(
                tracks,
                key=lambda p: (
                    -int(play_counts.get(os.path.normcase(os.path.abspath(p)), 0) or 0),
                    _sort_text_key(_track_sort_title(p)),
                    p,
                ),
            )
        return sorted(tracks, key=lambda p: (_sort_text_key(_track_sort_title(p)), p))

    def set_playlist_sort(self, sort_key):
        if sort_key not in PLAYLIST_SORT_MODES:
            return
        config.settings.set("playlistSort", sort_key, save=True)
        self.music.refresh_tracks()
        self.sync()

    def on_favorite_requested(self, source, path, payload):
        """行内爱心按钮：切换「我喜欢的」状态——已收藏则取消、未收藏则添加（与右键菜单语义一致）。"""
        music = self.music
        if music is None:
            return
        if source == "remote":
            music.favorite_remote(dict(payload or {}))
            return
        if not path:
            return
        if music.is_favorite_track(path):
            music.remove_favorite_track(path)
        elif source == "cache":
            music.favorite_cached(path)
        else:
            music.add_favorite_track(path)

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
                elif source == "local":
                    payload = p
                favorited = self.music.is_favorite_track(p)
                row = TrackItemWidget(mark, title, duration, i, i == self.music.index, source=source, payload=payload, favorited=favorited)
                row.clicked.connect(self.music.play_index)
                # 普通播放列表：删除文件并立即渲染；
                # 「我喜欢的」视图：仅移除收藏、不删文件（与右键"删除"语义一致）
                row.deleteRequested.connect(
                    lambda p, pw=self: (
                        pw.music.remove_favorite_track(p)
                        if pw.music.favorite_mode
                        else pw.music.delete_track_path_and_sync(p, remove_sidecars=True)
                    )
                )
                row.favoriteRequested.connect(self.on_favorite_requested)
                row.downloadRequested.connect(self.music.download_remote)
                row.saveAsRequested.connect(self.music.save_as_track)
                self.playlist_layout.addWidget(row)
                matches += 1
        if query and not self.music.favorite_mode:
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
                        favorited=False,
                    )
                    row.clicked.connect(self.music.play_remote)
                    row.downloadRequested.connect(self.music.download_remote)
                    row.addRemoteRequested.connect(self.music.cache_remote)
                    row.favoriteRequested.connect(self.on_favorite_requested)
                    self.playlist_layout.addWidget(row)
                    matches += 1
                if not self._remote_results and matches == 0:
                    self.playlist_layout.addWidget(TrackItemWidget("", tr("没有搜到结果"), "", -1, source="status"))
        elif self.music.favorite_mode and matches == 0:
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
        self._sync_from_state()
        self.vol.setValue(self.music._volume)
        self._sync_volume_icon(self.music._volume)

    def _sync_from_state(self):
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
            self.favorite_b.kind = "heart_filled" if self.music.favorite_mode else "heart"
            self.favorite_b.update()
            self._sync_volume_icon(self.vol.value())
        else:
            self.title.setText(tr("未在播放"))
            self.artist.setText(tr("用户音乐"))
            self.lyric.setText(_marked_lyric(_default_lyric()))
            self.cover.set_album_art(None)
            self.cur_t.setText("00:00")
            self.dur_t.setText("00:00")
            self.prog.setValue(0)
            self.favorite_b.kind = "heart_filled" if self.music.favorite_mode else "heart"
            self.favorite_b.update()
        if self._expanded:
            self._filter(self._search_query, refresh=False)

    def refresh_display(self):
        self._sync_from_state()

    def retranslate_ui(self):
        self.back_b.setToolTip(tr("最小化"))
        self.close_b.setToolTip(tr("退出播放器"))
        self.search.setPlaceholderText(tr("搜索歌曲..."))
        self.search_b.setToolTip(tr("搜索歌曲"))
        self.upload_b.setToolTip(tr("上传音乐"))
        self.favorite_b.setToolTip(tr("我喜欢的歌曲"))
        if hasattr(self, "notice"):
            self.notice.set_notice_text(tr("仅供学习交流使用，请支持正版音乐！"))
        # 拖放浮层：是/否按钮随语言刷新；若浮层正显示，提示语也按 key 重译
        if hasattr(self, "drop_yes_b"):
            self.drop_yes_b.setText(tr("是"))
            self.drop_no_b.setText(tr("否"))
        if getattr(self, "_drop_message_key", None) and self.drop_overlay.isVisible():
            self.drop_message.setText(tr(self._drop_message_key))
        self.sync()


class MusicPlayer:
    def __init__(self, ctx):
        self.ctx = ctx
        if IS_MAC:
            # macOS：系统原生 AVFoundation 后端，避免 QtMultimedia 打包后无声
            self.player = create_audio_backend()  # -> AVAudioBackend
            self.audio = _MacAudioShim(self.player)
            self._apply_default_audio_output()
        else:
            self.player = QMediaPlayer()
            self._media_devices = QMediaDevices()
            self.audio = QAudioOutput()
            self._apply_default_audio_output()
            self._media_devices.audioOutputsChanged.connect(self._apply_default_audio_output)
            self.player.setAudioOutput(self.audio)
        self.tracks = []
        self.index = 0
        self.favorite_mode = False
        self.loop = 0  # 0 列表循环 / 1 单曲循环 / 2 随机
        self._muted = False
        self._volume = DEFAULT_MUSIC_VOLUME
        self._duration_cache = {}
        self._lyric_cache = {}
        self._cover_by_path: dict[str, str] = {}
        self._kuwo_lyric_requested = set()
        self._remote_download_lock = threading.Lock()
        self._global_space_filter = GlobalMusicSpaceFilter(self)
        self.player.mediaStatusChanged.connect(self._on_status)
        # 播放失败不再静默：把底层错误打到 stderr（从终端启动时可见），便于定位
        # macOS 上「播放无声/失效」这类问题（如多媒体后端插件缺失、格式不支持）。
        self.player.errorOccurred.connect(self._on_media_error)
        self._apply_player_loops()
        self.set_volume(config.settings.get("volume", DEFAULT_MUSIC_VOLUME))
        # 延迟到窗口显示后再扫描曲库：避免启动期同步「全量磁盘扫描 + 逐文件解析时长」
        # 阻塞主线程（macOS Intel VM + Rosetta 下尤为明显，表现为启动极慢/像起不来）。
        QTimer.singleShot(50, self.refresh_tracks)
        self.window = None
        self.lyric_overlay = None
        self._closing = False
        # 隐藏式播放标记（歌手/闹钟模式）：不属于「音乐播放器开启」，
        # 因此不会触发系统托盘的播放控制条。
        self._alarm_mode = False
        self._singer_show_active = False

    def _apply_default_audio_output(self):
        if IS_MAC:
            # AVAudioPlayer 由系统自动选择默认输出设备，无需 QMediaDevices
            self.audio.setVolume(0 if getattr(self, "_muted", False) else getattr(self, "_volume", DEFAULT_MUSIC_VOLUME) / 100.0)
            return
        device = QMediaDevices.defaultAudioOutput()
        if hasattr(device, "isNull") and device.isNull():
            return
        if self.audio.device() != device:
            self.audio.setDevice(device)
        self.audio.setVolume(0 if getattr(self, "_muted", False) else getattr(self, "_volume", DEFAULT_MUSIC_VOLUME) / 100.0)

    def _on_media_error(self, error, error_string):
        """QMediaPlayer 底层错误日志（macOS 上排查播放失效的关键线索）。"""
        try:
            print(f"[music] QMediaPlayer error {error}: {error_string}", file=sys.stderr, flush=True)
        except Exception:  # noqa: BLE001
            pass

    def _apply_player_loops(self):
        loops = QMediaPlayer.Loops.Infinite if self.loop == 1 else QMediaPlayer.Loops.Once
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

    def force_refresh_lyric_render(self):
        pos = self.player.position()
        text, progress = self.lyric_display(pos)
        if self.window and hasattr(self.window, "lyric"):
            self.window.lyric.setText(self.lyric_text(pos))
            self.window.lyric.update()
        if self.lyric_overlay:
            self.lyric_overlay.lyric.set_text(text, progress)
            self.lyric_overlay.lyric.update()

    def shift_current_lyric(self, delta_ms: int) -> bool:
        path = self.player.source().toLocalFile()
        if not path and 0 <= self.index < len(self.tracks):
            path = self.tracks[self.index]
        if not path:
            return False
        if not lyrics.shift_lyric_file(path, delta_ms):
            return False
        self._lyric_cache.pop(path, None)
        self.force_refresh_lyric_render()
        return True

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
        all_tracks = self._deduped_track_paths(assets.list_music_files() + music_api.list_cached_files())
        self._cleanup_favorites(all_tracks)
        if self.favorite_mode:
            all_tracks = [path for path in all_tracks if self.is_favorite_track(path)]
        self.tracks = self._sorted_tracks(all_tracks)
        self._warm_covers()
        live = set(self.tracks)
        self._duration_cache = {p: d for p, d in self._duration_cache.items() if p in live}
        for p in self.tracks:
            self._duration_cache.setdefault(p, _parse_duration(p))
        if current in live:
            lyrics.ensure_lyrics_async(current, self._duration_cache.get(current))
            self._ensure_cover(current)
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

    def _sorted_tracks(self, tracks):
        sort_mode = _playlist_sort_mode()
        play_counts = config.settings.get("trackPlayCounts", {}) or {}
        def created_key(path):
            if self.favorite_mode:
                value = self._favorite_tracks().get(self._track_key(path), 0)
                try:
                    return int(value or 0)
                except (TypeError, ValueError):
                    return 0
            cached = music_api.cache_info(path) or {}
            if cached.get("created"):
                return int(cached.get("created") or 0)
            try:
                return int(os.path.getmtime(path))
            except OSError:
                return 0

        def title_key(path):
            return _track_sort_title(path)

        def artist_key(path):
            return _track_sort_artist(path)

        def play_key(path):
            return int(play_counts.get(os.path.normcase(os.path.abspath(path)), 0) or 0)

        if sort_mode == "added":
            return sorted(tracks, key=lambda p: (-created_key(p), title_key(p), p))
        if sort_mode == "title_desc":
            return sorted(tracks, key=lambda p: (_sort_text_key_desc(title_key(p)), p))
        if sort_mode == "artist_asc":
            return sorted(tracks, key=lambda p: (_sort_text_key(artist_key(p)), _sort_text_key(title_key(p)), p))
        if sort_mode == "artist_desc":
            return sorted(tracks, key=lambda p: (_sort_text_key_desc(artist_key(p)), _sort_text_key(title_key(p)), p))
        if sort_mode == "plays":
            return sorted(tracks, key=lambda p: (-play_key(p), _sort_text_key(title_key(p)), p))
        return sorted(tracks, key=lambda p: (_sort_text_key(title_key(p)), p))

    @staticmethod
    def _track_key(path):
        return os.path.normcase(os.path.abspath(path)) if path else ""

    def _favorite_tracks(self):
        favorites = config.settings.get("favoriteTracks", {}) or {}
        return favorites if isinstance(favorites, dict) else {}

    def is_favorite_track(self, path):
        return bool(self._favorite_tracks().get(self._track_key(path)))

    def _cleanup_favorites(self, live_tracks):
        live = {self._track_key(path) for path in live_tracks}
        favorites = dict(self._favorite_tracks())
        cleaned = {key: value for key, value in favorites.items() if key in live}
        if cleaned != favorites:
            config.settings.set("favoriteTracks", cleaned, save=True)

    def add_favorite_track(self, path, announce=True, sync_ui=True):
        if not path or not os.path.exists(path):
            return False
        favorites = dict(self._favorite_tracks())
        key = self._track_key(path)
        if key not in favorites:
            import time
            favorites[key] = int(time.time())
            config.settings.set("favoriteTracks", favorites, save=True)
        if announce:
            say(tr("已添加到我喜欢"))
        if sync_ui and self.window:
            # 搜索进行中：仅写入收藏数据、不重建播放列表，避免滚动位置被重置、打断浏览；
            # 最终列表将在用户清空搜索框时由 _on_search_changed 统一重渲染。
            if getattr(self.window, "_search_query", ""):
                pass
            else:
                self.window.sync()
        return True

    def remove_favorite_track(self, path):
        current = self.player.source().toLocalFile()
        was_current = bool(current and path and os.path.abspath(current) == os.path.abspath(path))
        favorites = dict(self._favorite_tracks())
        key = self._track_key(path)
        if key in favorites:
            favorites.pop(key, None)
            config.settings.set("favoriteTracks", favorites, save=True)
        self.refresh_tracks()
        if self.favorite_mode and was_current:
            if self.tracks:
                self.index = max(0, min(self.index, len(self.tracks) - 1))
                self.play(self.tracks[self.index])
            else:
                self.index = 0
                self.player.stop()
                self.player.setSource(QUrl())
        if self.window:
            # 搜索进行中：仅写入数据、不重建播放列表，避免滚动位置被重置（与 add_favorite_track 一致）
            if getattr(self.window, "_search_query", ""):
                pass
            else:
                self.window.sync()
        say(tr("已取消我喜欢"))

    def toggle_favorite_mode(self):
        self.favorite_mode = not self.favorite_mode
        self.refresh_tracks()
        if self.favorite_mode:
            if self.tracks:
                self.index = max(0, min(self.index, len(self.tracks) - 1))
                self.play(self.tracks[self.index])
            else:
                self.index = 0
                self.player.stop()
                self.player.setSource(QUrl())
                if self.window:
                    self.window.refresh_display()
        else:
            current = self.player.source().toLocalFile()
            if current in self.tracks:
                self.index = self.tracks.index(current)
        if self.window:
            if not self.window._expanded:
                self.window.toggle_playlist()
            self.window.sync()

    def _bump_play_count(self, path, persist=True):
        if not path:
            return
        key = os.path.normcase(os.path.abspath(path))
        counts = dict(config.settings.get("trackPlayCounts", {}) or {})
        counts[key] = int(counts.get(key, 0) or 0) + 1
        config.settings.set("trackPlayCounts", counts, save=persist)

    def _ensure_cover(self, path):
        title, artist = _split_track_artist(path)
        # 立即复用已知封面（内存缓存或磁盘已存在），避免播放初期的空白等待；
        # 即使后台查找尚未返回，也能先显示上一次已找到的封面。
        known = self._cover_by_path.get(path) or covers.existing_cover(title, artist or None)
        if known and self.window:
            self.window.cover.set_album_art(known)
            self.window.cover.update()
        def on_done(saved_path):
            QTimer.singleShot(0, lambda p=path, s=saved_path: self._cover_ready(p, s))

        covers.ensure_cover_async(title, artist or None, on_done)

    def _warm_covers(self):
        # 列表加载完成后后台预取封面（covers 内部信号量限流，最多 8 并发）。
        # 这样用户在点击播放前，多数曲目封面已落盘，达成“极短时间即就绪”。
        if not self.tracks:
            return
        for path in self.tracks[:50]:
            title, artist = _split_track_artist(path)
            covers.ensure_cover_async(title, artist or None)

    def _prefetch_neighbors(self):
        # 顺序播放时，提前为下一首拉取封面与歌词，确保切歌瞬间即就绪。
        # 单曲循环无意义，随机模式无法预知下一首，故仅顺序模式预取。
        if self.loop != 0 or len(self.tracks) < 2:
            return
        nxt = (self.index + 1) % len(self.tracks)
        if nxt == self.index:
            return
        path = self.tracks[nxt]
        self._ensure_cover(path)
        if not lyrics.has_lyrics(path):
            lyrics.ensure_lyrics_async(path, self.duration_text(path))

    def _cover_ready(self, path, saved_path):
        # 始终记录已找到的封面，即使此时已切歌也不丢弃；
        # 下次该曲成为当前曲目时会通过 _ensure_cover 瞬时复用。
        self._cover_by_path[path] = saved_path
        if not self.window:
            return
        current = self.player.source().toLocalFile()
        if os.path.normcase(os.path.abspath(current)) != os.path.normcase(os.path.abspath(path)):
            return
        self.window.cover.set_album_art(saved_path)
        self.window.cover.update()

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
        # Serialize remote transfers: target selection, file creation, lyrics, and
        # cache metadata must form one transaction when users click rapidly.
        with self._remote_download_lock:
            existing = self._find_existing_track(item)
            cache_path = (item or {}).get("cache_path")
            moving_cache_to_library = (
                not cache and cache_path and existing and
                os.path.abspath(existing) == os.path.abspath(cache_path)
            )
            if existing and not moving_cache_to_library:
                raise DuplicateTrackError("歌曲已存在")
            result = music_api.resolve_playable(item, br)
            if result.get("error"):
                raise music_api.RemoteResolveError(result["error"])
            info = {k: v for k, v in result.items() if k != "error"}
            ext = info.get("format") or "mp3"
            out_path = music_api.target_path(item, folder, ext, include_rid=cache)
            music_api.download(info["url"], out_path)
            # Kuwo serves a short spoken "use the mobile app" clip (instead of the
            # song) for restricted IPs/networks. It arrives as a normal 200 + url,
            # so is_full_track can't catch it -- the user would hear Kuwo's own
            # "当前音乐仅在..." message. Detect the tiny clip and surface our own
            # restricted wording instead of playing the misleading audio.
            if music_api.looks_like_trial_clip(out_path, item, info):
                try:
                    os.remove(out_path)
                except OSError:
                    pass
                raise music_api.RemoteResolveError("restricted")
            lrc = music_api.get_lrc(item.get("rid", ""), item.get("source"), item.get("api"))
            if lrc:
                lyric_target = lyrics.lyric_path(out_path)
                os.makedirs(os.path.dirname(lyric_target), exist_ok=True)
                lyric_temp = lyric_target + ".tmp"
                try:
                    with open(lyric_temp, "w", encoding="utf-8") as f:
                        f.write(lyrics.simplified_text(lrc))
                    os.replace(lyric_temp, lyric_target)
                except Exception:
                    try:
                        if os.path.exists(lyric_temp):
                            os.remove(lyric_temp)
                    except OSError:
                        pass
                    raise
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

    # 注：原先的 _has_any_track / _has_local_track 预检已移除。
    # 它们会在「主线程」全量扫描本地曲库 + 缓存目录做去重，用户连续点击下载 /
    # 加入播放列表时主线程被反复扫描占满，正是列表滑动卡顿的主因。
    # 后台 _download_remote_to 取得下载锁后第一步就会做等价去重（DuplicateTrackError），
    # 重复歌曲仍会以「歌曲已存在」播报，用户可见行为一致，但不再阻塞 UI。

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
            except music_api.RemoteResolveError as exc:
                self.window.remotePlayReady.emit(None, exc.kind)
            except Exception as exc:  # noqa: BLE001
                self.window.remotePlayReady.emit(None, str(exc))
            finally:
                buffering_done.set()

        threading.Thread(target=worker, daemon=True).start()

    def cache_remote(self, item):
        if not item or not self.window:
            return
        # 去重不再于主线程预检：后台 _download_remote_to 持锁后会先做等价去重，
        # 重复时抛 DuplicateTrackError，仍会播报「歌曲已存在」（见 _on_remote_download_ready）。
        say(tr("正在添加到播放列表"))

        def worker():
            try:
                payload = self._download_remote_to(item, None, music_api.cache_dir(), cache=True)
                self.window.remoteDownloadReady.emit(payload, None)
            except music_api.RemoteResolveError as exc:
                self.window.remoteDownloadReady.emit(None, exc.kind)
            except Exception as exc:  # noqa: BLE001
                self.window.remoteDownloadReady.emit(None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def download_remote(self, item, br):
        if not item or not self.window:
            return
        # 同上：去掉主线程全量扫描预检，去重交由后台 _download_remote_to 处理。
        say(tr("开始下载"))

        def worker():
            try:
                payload = self._download_remote_to(item, br, assets.get_library_folder(), cache=False)
                self.window.remoteDownloadReady.emit(payload, None)
            except DuplicateTrackError as exc:
                self.window.remoteDownloadReady.emit(None, str(exc))
            except music_api.RemoteResolveError as exc:
                self.window.remoteDownloadReady.emit(None, exc.kind)
            except Exception as exc:  # noqa: BLE001
                self.window.remoteDownloadReady.emit(None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def favorite_remote(self, item):
        if not item or not self.window:
            return
        existing = self._find_existing_track(item)
        if existing and os.path.exists(existing) and not music_api.is_cache_path(existing):
            self.add_favorite_track(existing)
            return
        item = dict(item or {})
        if existing and music_api.is_cache_path(existing):
            item["cache_path"] = existing
        say(tr("开始下载"))

        def worker():
            try:
                payload = self._download_remote_to(item, None, assets.get_library_folder(), cache=False)
                payload["add_favorite"] = True
                self.window.remoteDownloadReady.emit(payload, None)
            except DuplicateTrackError:
                existing_path = self._find_existing_track(item)
                if existing_path:
                    self.window.remoteDownloadReady.emit({"path": existing_path, "add_favorite": True}, None)
                else:
                    self.window.remoteDownloadReady.emit(None, "歌曲已存在")
            except Exception as exc:  # noqa: BLE001
                self.window.remoteDownloadReady.emit(None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def favorite_cached(self, path):
        """将缓存歌曲收藏并落地到本地曲库；与在线收藏一致，均播报「已添加到我喜欢」。"""
        if not path:
            return
        # 非缓存来源退回原逻辑（保留语音播报）
        if not music_api.is_cache_path(path):
            self.add_favorite_track(path)
            return
        info = music_api.cache_info(path) or {}
        parsed_title, parsed_artist = music_api._split_track_artist_from_name(path)
        name = (info.get("name") or "").strip() or parsed_title
        artist = (info.get("artist") or "").strip() or parsed_artist
        item = {
            "name": name, "artist": artist,
            "rid": info.get("rid") or info.get("id") or "",
            "id": info.get("rid") or info.get("id") or "",
            "source": info.get("source", ""), "api": info.get("api", ""),
            "cover": info.get("cover", ""), "duration": info.get("duration", 0),
            "full_qualities": info.get("full_qualities", []),
        }
        # 曲库已有同名本地副本时，直接收藏该副本，避免重复落地
        existing = self._find_existing_track(item)
        if existing and os.path.exists(existing) and not music_api.is_cache_path(existing):
            self.add_favorite_track(existing, announce=True)
            return
        library_folder = assets.get_library_folder()
        ext = (os.path.splitext(path)[1].lstrip(".") or "mp3")
        target = music_api.target_path(item, library_folder, ext, include_rid=False)
        try:
            shutil.copy2(path, target)
        except OSError:
            # 落地失败则退化为仅收藏缓存路径（仍播报）
            self.add_favorite_track(path, announce=True)
            return
        self._promote_cached_sidecars(path, target)
        music_api.remember_track(target, item, info.get("quality"))
        self.refresh_tracks()
        self.add_favorite_track(target, announce=True)

    def _promote_cached_sidecars(self, src, dst):
        """把缓存歌曲的歌词等附件一并拷贝到本地曲库目录。"""
        try:
            from app.core import lyrics
            for lp in (lyrics.lyric_path(src), lyrics.plain_lyric_path(src)):
                if lp and os.path.exists(lp):
                    try:
                        shutil.copy2(lp, lyrics.lyric_path(dst))
                    except OSError:
                        pass
                    break
        except Exception:  # noqa: BLE001
            pass

    def play_cached(self, payload, sync_ui=True):
        path = (payload or {}).get("path")
        self.refresh_tracks()
        if path in self.tracks:
            self.index = self.tracks.index(path)
        self.play(path)
        # 搜索进行中默认不重建列表，避免单/双击缓存完成即跳回顶部、打断浏览；
        # 仅当非搜索态或显式要求时同步整个界面。
        if self.window and sync_ui and not getattr(self.window, "_search_query", ""):
            self.window.sync()

    def save_as_track(self, i):
        self.refresh_tracks()
        if not (0 <= i < len(self.tracks)):
            return
        self.save_as_track_path(self.tracks[i])

    def save_as_track_path(self, src):
        if not src:
            return
        title = _track_display_title(src).replace(" · 缓存", "")
        ext = os.path.splitext(src)[1] or ".mp3"
        target, _ = QFileDialog.getSaveFileName(None, tr("另存为"), f"{title}{ext}", f"{tr('音频文件')} (*.*)")
        if not target:
            return
        try:
            shutil.copy2(src, target)
            say(tr("保存完成"))
        except OSError:
            say(tr("保存失败，请稍后再试"))

    def _wait_media_released(self, timeout_ms=1500):
        """主动等待 QMediaPlayer 释放当前媒体文件句柄。

        Windows WMF 后端在 stop()/setSource(QUrl()) 后不会立即释放文件句柄，
        若不等待就删除会出现「正被另一进程使用」而失败。轮询媒体状态直到
        NoMedia/InvalidMedia（或超时），避免随后删除被占用文件。
        """
        # macOS 下 AVAudioPlayer 在 stop()/setSource 后立即释放文件句柄，无需等待
        if IS_MAC:
            return True
        from PyQt6.QtCore import QElapsedTimer
        from PyQt6.QtMultimedia import QMediaPlayer

        timer = QElapsedTimer()
        timer.start()
        while timer.elapsed() < timeout_ms:
            QApplication.processEvents()
            try:
                status = self.player.mediaStatus()
            except Exception:
                return True
            if status in (QMediaPlayer.MediaStatus.NoMedia,
                          QMediaPlayer.MediaStatus.InvalidMedia):
                return True
            QThread.msleep(30)
        return True

    def delete_track_path(self, path, remove_sidecars=True):
        if not path:
            return True
        cached_info = music_api.cache_info(path) or {}
        current = self.player.source().toLocalFile()
        if current and os.path.abspath(current) == os.path.abspath(path):
            self.player.stop()
            self.player.setSource(QUrl())
            # 等待媒体资源真正释放，避免 Windows 下删除被占用文件失败
            self._wait_media_released(timeout_ms=1500)
        ok = self._delete_audio_file(path)
        if not ok:
            return False
        self._duration_cache.pop(path, None)
        self._lyric_cache.pop(path, None)
        if remove_sidecars:
            self._delete_track_sidecars(path, cached_info)
        # 缓存索引写入为非关键操作，失败不应影响本次删除结果
        try:
            music_api.forget_cache(path)
        except Exception:
            pass
        return True

    def delete_track_path_and_sync(self, path, remove_sidecars=True):
        current = self.player.source().toLocalFile()
        was_current = bool(current) and os.path.abspath(current) == os.path.abspath(path)
        try:
            deleted = self.delete_track_path(path, remove_sidecars=remove_sidecars)
        except Exception:
            deleted = False
        if not deleted:
            # 删除未成功也要回写 UI，避免行残留
            if self.window:
                self.window.sync()
            return False
        try:
            self.refresh_tracks()
        except Exception:
            # refresh_tracks 内部偶发异常（如缓存索引写入失败）不应阻断渲染
            pass
        # 删除的是正在播放的曲目：立即推进到下一首，保证播放连贯
        if was_current and self.tracks:
            self.index = max(0, min(self.index, len(self.tracks) - 1))
            self.play(self.tracks[self.index])
        if self.window:
            self.window.sync()
        return True

    def _delete_audio_file(self, path, attempts=24, initial_ms=50, max_ms=250):
        delay = initial_ms
        for _ in range(attempts):
            try:
                if os.path.exists(path):
                    os.remove(path)
                return True
            except OSError:
                QApplication.processEvents()
                QThread.msleep(delay)
                delay = min(delay * 2, max_ms)
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
            self.window._sync_volume_icon(0 if self._muted else self._volume)

    def play(self, path):
        if not path or not os.path.exists(path):
            return
        self._apply_player_loops()
        self.player.setSource(QUrl.fromLocalFile(path))
        self._apply_player_loops()
        self._apply_default_audio_output()
        self.player.play()
        self._bump_play_count(path)
        self._ensure_cover(path)
        self._prefetch_neighbors()
        if self.window:
            self.window.refresh_display()

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
            self.window.refresh_display()

    def pause_for_drop(self):
        if self.player.isPlaying():
            self.player.pause()
        if self.window:
            self.window.refresh_display()

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
            self.window.refresh_display()
        self.sync_lyric_overlay()

    def play_index(self, i):
        if 0 <= i < len(self.tracks):
            self.index = i
            self.play(self.tracks[i])
            if self.window:
                self.window.refresh_display()

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
            self.window.refresh_display()

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
            self.window.refresh_display()

    def cycle_loop(self):
        self.loop = (self.loop + 1) % 3
        self._apply_player_loops()
        if self.window:
            self.window.loop_b.kind = ["loop", "loop_one", "shuffle"][self.loop]
            self.window.loop_b.update()
        self.sync_lyric_overlay()

    def _on_status(self, status):
        from PyQt6.QtMultimedia import QMediaPlayer
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self._singer_show_active:
                # 歌手隐藏式演唱结束：停止并播报收尾语，不自动切歌。
                self._singer_show_active = False
                self.player.stop()
                self.player.setSource(QUrl())
                say(tr("还想听吗？那就快去听听歌吧！"))
                return
            if self._alarm_mode:
                # 闹钟铃声单曲循环，直到 stop_alarm。
                QTimer.singleShot(0, self._replay_current_source)
                return
            if self.loop == 1:
                QTimer.singleShot(0, self._replay_current_source)
            else:
                # Advance through the playlist; modulo in next() wraps the
                # last track back to the first one.
                QTimer.singleShot(0, self.next)

    def play_random(self, duration=None, show_player=True):
        self.refresh_tracks()
        # 进入可见播放会话：清除任何隐藏式（歌手/闹钟）标记。
        self._alarm_mode = False
        self._singer_show_active = False
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
            # 通知托盘：音乐播放器已开启，显示播放控制条。
            self._notify_tray(True)
        if not self.tracks:
            say(tr("当前没有可播放的音乐，请先上传"))
            return
        self.index = self._pick_random_index()
        self.play(self.tracks[self.index])
        if show_player and self.window:
            self.window.sync()

    def stop(self):
        self._apply_player_loops()
        self.player.stop()
        self.player.setSource(QUrl())

    def close_player(self):
        """关闭播放器会话：仅隐藏窗口并停止播放，不退出整个 AT小PP 应用。

        卜卜音悦原版会在此处调用 app.quit()（因为其播放器即整个应用）；
        AT小PP 中播放器只是桌宠的一个面板，关闭它不应结束整个程序。
        """
        self._alarm_mode = False
        self._singer_show_active = False
        self.stop()
        if self.window:
            self.window.hide()
        if self.lyric_overlay:
            self.lyric_overlay.hide()
        self._notify_tray(False)

    def _notify_tray(self, visible):
        """通知系统托盘显示/隐藏音乐播放控制条（仅播放器窗口开启时显示）。"""
        tray = getattr(self.ctx, "tray", None)
        if tray is not None and hasattr(tray, "set_music_visible"):
            tray.set_music_visible(bool(visible))

    # ---- 兼容层：歌手 / 闹钟 隐藏式播放 ----
    # 卜卜音悦移植版移除了这些方法（其无歌手/闹钟概念），但 AT小PP 的
    # 场景系统与闹钟提醒仍依赖它们。它们复用同一个 QMediaPlayer，且不打开
    # 播放器窗口，因此不会触发托盘播放控制条（符合「隐藏式播放器不算」）。
    def play_alarm(self, path):
        """隐藏播放闹钟铃声（单曲循环，直到 stop_alarm）。"""
        if not path or not os.path.exists(path):
            return
        if self.window:
            self.window.hide()
        self._singer_show_active = False
        self._alarm_mode = True
        self.player.setLoops(QMediaPlayer.Loops.Once)
        self._apply_default_audio_output()
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def start_singer_show(self):
        """隐藏式歌手演唱：随机播放一首本地曲目（不打开播放器窗口）。"""
        self.refresh_tracks()
        local_tracks = assets.list_music_files()
        if not local_tracks:
            say(tr("当前没有可播放的音乐，请先上传"))
            return
        say(tr("歌手小PP登场捏~"))
        path = random.choice(local_tracks)
        self._alarm_mode = False
        self.play(path)
        self._singer_show_active = True
        self.player.setLoops(QMediaPlayer.Loops.Once)

    def _stop_singer(self):
        self._singer_show_active = False
        self.player.stop()
        self.player.setSource(QUrl())

    def stop_alarm(self):
        if self._alarm_mode:
            self._alarm_mode = False
            self._apply_player_loops()
            self.player.stop()
            self.player.setSource(QUrl())

    def alarm_active(self):
        return self._alarm_mode

    def retranslate_ui(self):
        if self.window:
            self.window.retranslate_ui()
        if self.lyric_overlay:
            self.lyric_overlay.retranslate_ui()

    def leave_activity(self):
        if self.window is None or not self.window.isVisible():
            self.stop()

    def upload(self):
        # 默认指向系统音乐目录（macOS = ~/Music），而非软件自有的曲库目录
        start_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.MusicLocation
        ) or assets.get_music_folder()
        files, _ = QFileDialog.getOpenFileNames(
            None, tr("上传音乐"), start_dir,
            f"{tr('音频文件')} (*.mp3 *.wav *.ogg *.flac *.m4a)"
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
        dest = assets.get_library_folder()
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
