"""跨平台音频播放后端抽象。

设计目标：让 music_player.py 的调用点几乎无需改动，同时在 macOS 上用系统原生
AVFoundation (AVAudioPlayer) 替代 PyQt6.QtMultimedia，彻底绕开打包 .app 后
QtMultimedia 后端插件（darwinmedia）因 @rpath 解析失败导致「No QtMultimedia
backends found / QMediaPlayer Not available」而静默无声的坑。

- macOS (darwin): AVAudioBackend —— 通过 PyObjC 桥接 AVFoundation，苹果原生音频栈。
- 其它平台: 直接复用 PyQt6.QtMultimedia.QMediaPlayer（行为与原实现完全一致）。

对外暴露与 QMediaPlayer 高度一致的接口（同名方法 + 同名 pyqtSignal + 枚举常量），
枚举常量复用 QMediaPlayer 的真实枚举，保证 music_player.py 中的比较/赋值零改动。
"""
import sys

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
# 复用 QMediaPlayer 的枚举常量，使调用方的 MediaStatus/Loops 比较无需改动
from PyQt6.QtMultimedia import QMediaPlayer

IS_MAC = sys.platform == "darwin"

MediaStatus = QMediaPlayer.MediaStatus
PlaybackState = QMediaPlayer.PlaybackState
Loops = QMediaPlayer.Loops

# macOS 专用依赖仅在 darwin 下导入，避免非 mac 平台 import 该模块时报缺包
if IS_MAC:
    from Foundation import NSObject, NSURL  # type: ignore
    from AVFoundation import AVAudioPlayer  # type: ignore
    import objc  # type: ignore


class _BasePlayer(QObject):
    """两端共用的信号定义（与 QMediaPlayer 信号签名一致）。"""

    positionChanged = pyqtSignal(int)
    durationChanged = pyqtSignal(int)
    # macOS 这一版 PyQt6 的 PlaybackState/MediaStatus 是普通 enum.Enum（非 IntEnum），
    # 不能用 int(成员)；按 QMediaPlayer 原语义直接发射枚举成员，调用方据此做成员比较。
    playbackStateChanged = pyqtSignal(object)
    mediaStatusChanged = pyqtSignal(object)
    errorOccurred = pyqtSignal(int, str)
    # 兼容 QMediaPlayer.sourceChanged(QUrl)：加载/清空音源时发出，供 UI 同步状态
    sourceChanged = pyqtSignal(QUrl)

    def __init__(self):
        super().__init__()
        self._current_path = ""

    # ---------- 通用兼容接口（两端一致） ----------

    def source(self) -> QUrl:
        """兼容 QMediaPlayer.source()：返回当前本地文件 QUrl，未加载则为空。"""
        if self._current_path:
            return QUrl.fromLocalFile(self._current_path)
        return QUrl()

    def setAudioOutput(self, output):
        """macOS 下 AVAudioPlayer 自管音频输出设备，忽略该调用。"""
        return

    def setVolume(self, v: float):
        raise NotImplementedError


if IS_MAC:

    class _AVDelegate(NSObject):
        """AVAudioPlayer 播放结束回调桥接（结束 -> 触发 EndOfMedia 状态）。"""

        def init(self):
            # PyObjC 警告：Objective-C 子类的 init 必须用 objc.super 调父类的 OC 方法，
            # 不能用 Python 的 super()（其不解析 OC runtime 方法，会 AttributeError）。
            self = objc.super(_AVDelegate, self).init()
            if self is None:
                return None
            self.backend = None
            return self

        @objc.signature(b"v@:@c")
        def audioPlayerDidFinishPlaying_successfully_(self, player, flag):
            # b"v@:@c" = void; self; sel; player(id); successfully(BOOL 编为 char)
            # 注意：PyObjC>=12 要求签名传 bytes 而非 str，否则 makeSignature 报
            # 'a bytes-like object is required, not str'
            if self.backend is not None:
                self.backend._on_finished()

    class AVAudioBackend(_BasePlayer):
        """macOS 原生音频后端：AVFoundation AVAudioPlayer。

        功能覆盖：播放/暂停/停止、进度(position/duration)、拖动定位(setPosition)、
        音量(setVolume)、循环(setLoops 单曲/列表)、结束自动下一首(EndOfMedia 状态)。
        进度条与歌词同步所需的 positionChanged 由内部 QTimer(250ms) 轮询 currentTime 驱动。
        """

        def __init__(self):
            super().__init__()
            self._av = None
            self._delegate = _AVDelegate.alloc().init()
            self._delegate.backend = self
            self._timer = QTimer()
            self._timer.setInterval(250)
            self._timer.timeout.connect(self._poll)
            self._state = PlaybackState.StoppedState
            self._volume = 1.0
            self._loops = 0  # AVAudioPlayer: 0=一次, -1=无限循环

        # ---------- 内部：构造底层播放器 ----------

        def _create_player(self, path: str):
            url = NSURL.fileURLWithPath_(path)
            if url is None:
                self.errorOccurred.emit(-1, "AVAudioPlayer 无效路径")
                self.mediaStatusChanged.emit(MediaStatus.InvalidMedia)
                return
            # initWithContentsOfURL:error: 的 NSError** 输出参数在 PyObjC 下会返回
            # (player, error) 元组（版本相关）。run#27 真机即此表现，直接对元组调
            # setDelegate_ 触发 "'tuple' object has no attribute 'setDelegate_'" 崩溃。
            # 统一拆包，兼容“返回元组”与“直接返回 player”两种行为。
            res = AVAudioPlayer.alloc().initWithContentsOfURL_error_(url, None)
            if isinstance(res, tuple):
                av = res[0]
                error = res[1] if len(res) > 1 else None
            else:
                av, error = res, None
            if av is None:
                msg = "AVAudioPlayer 初始化失败"
                if error is not None:
                    msg = f"AVAudioPlayer 初始化失败: {error}"
                self.errorOccurred.emit(-1, msg)
                self.mediaStatusChanged.emit(MediaStatus.InvalidMedia)
                return
            av.setDelegate_(self._delegate)
            av.setVolume_(self._volume)
            av.setNumberOfLoops_(self._loops)
            av.prepareToPlay()
            self._av = av
            self._current_path = path
            dur_ms = int(av.duration() * 1000)
            self.durationChanged.emit(dur_ms)
            self.mediaStatusChanged.emit(MediaStatus.LoadedMedia)

        # ---------- 公开接口（与 QMediaPlayer 一致） ----------

        def setSource(self, url):
            # 兼容两种用法：setSource(QUrl.fromLocalFile(path)) 或 setSource(QUrl()) 清空
            if isinstance(url, QUrl) and url.isEmpty():
                self.stop()
                self._current_path = ""
                self.mediaStatusChanged.emit(MediaStatus.NoMedia)
                self.sourceChanged.emit(QUrl())
                return
            path = url.toLocalFile() if isinstance(url, QUrl) else str(url)
            if not path:
                return
            self.stop()
            self._create_player(path)
            self.sourceChanged.emit(url if isinstance(url, QUrl) else QUrl.fromLocalFile(path))

        def play(self):
            if self._av is None:
                return
            if self._av.play():
                self._state = PlaybackState.PlayingState
                self.playbackStateChanged.emit(self._state)
                if not self._timer.isActive():
                    self._timer.start()
            else:
                self.errorOccurred.emit(-1, "AVAudioPlayer play() returned False")

        def pause(self):
            if self._av is None:
                return
            self._av.pause()
            self._state = PlaybackState.PausedState
            self.playbackStateChanged.emit(self._state)
            self._timer.stop()

        def stop(self):
            if self._av is not None:
                self._av.stop()
                try:
                    self._av.setCurrentTime_(0.0)
                except Exception:  # noqa: BLE001
                    pass
            self._state = PlaybackState.StoppedState
            self.playbackStateChanged.emit(self._state)
            self._timer.stop()

        def isPlaying(self) -> bool:
            return bool(self._av is not None and self._av.isPlaying())

        def position(self) -> int:
            if self._av is None:
                return 0
            return int(self._av.currentTime() * 1000)

        def duration(self) -> int:
            if self._av is None:
                return 0
            return int(self._av.duration() * 1000)

        def setPosition(self, ms: int):
            if self._av is not None:
                self._av.setCurrentTime_(ms / 1000.0)
                self.positionChanged.emit(ms)

        def setLoops(self, loops):
            # QMediaPlayer.Loops.Infinite / Once —— 映射为 AVAudioPlayer 的 -1 / 0
            # 兼容普通 Enum（macOS PyQt6）：用 .value 取整数，成员或 int 都能接
            v = loops.value if hasattr(loops, "value") else loops
            self._loops = -1 if int(v) == int(Loops.Infinite.value) else 0
            if self._av is not None:
                self._av.setNumberOfLoops_(self._loops)

        def setVolume(self, v: float):
            self._volume = float(v)
            if self._av is not None:
                self._av.setVolume_(self._volume)

        def mediaStatus(self):
            # 返回枚举成员（与 QMediaPlayer.mediaStatus() 语义一致），供调用方做成员比较
            if not self._current_path:
                return MediaStatus.NoMedia
            if self._av is None:
                return MediaStatus.InvalidMedia
            return MediaStatus.LoadedMedia

        # ---------- 内部：轮询 / 结束回调 ----------

        def _poll(self):
            if self._av is None:
                return
            self.positionChanged.emit(int(self._av.currentTime() * 1000))

        def _on_finished(self):
            self._timer.stop()
            self.positionChanged.emit(self.duration())
            self._state = PlaybackState.StoppedState
            self.playbackStateChanged.emit(self._state)
            # 通知业务层：媒体播放结束（music_player._on_status 据此切歌/单曲循环）
            self.mediaStatusChanged.emit(MediaStatus.EndOfMedia)


class _MacAudioShim:
    """macOS 下替代 QAudioOutput 的薄壳：仅转发音量，设备相关调用直接忽略。

    AVAudioPlayer 由系统自动选择默认输出设备，无需也不支持 QAudioOutput 的设备切换。
    """

    def __init__(self, backend):
        self._backend = backend

    def setVolume(self, v: float):
        self._backend.setVolume(v)

    def setDevice(self, device):
        return

    def device(self):
        return None


def create_audio_backend():
    """按平台返回音频后端实例。

    - macOS: AVAudioBackend（原生 AVFoundation）
    - 其它: 直接返回 QMediaPlayer（保持原行为）
    """
    if IS_MAC:
        return AVAudioBackend()
    return QMediaPlayer()
