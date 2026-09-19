"""语音播报引擎。

优先播放预生成语音；没有预生成音频时使用 Windows SAPI5。
语音在独立工作线程里执行，避免阻塞界面主线程。
"""

import os
import json
import hashlib
import subprocess
import sys
import time
import tempfile
import wave
import audioop

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from app.core import config, pathutil, voice_media
from app.core.speech import apply_ni

try:
    import comtypes.client  # noqa: F401
    _HAS_COMTYPES = True
except Exception:  # noqa: BLE001
    _HAS_COMTYPES = False

try:
    import winsound
    _HAS_WINSOUND = True
except Exception:  # noqa: BLE001
    winsound = None
    _HAS_WINSOUND = False


class SapiVoiceEngine:
    def __init__(self):
        self.available = False
        self.voice = None
        self._voices = []
        if not _HAS_COMTYPES:
            return
        try:
            self.voice = comtypes.client.CreateObject("SAPI.SPVoice")
            self.available = True
        except Exception:  # noqa: BLE001
            self.voice = None
            self.available = False
        if self.available:
            try:
                cnt = self.voice.GetVoices().Count
                self._voices = [self.voice.GetVoices().Item(i) for i in range(cnt)]
            except Exception:  # noqa: BLE001
                self._voices = []

    def select_voice(self, lang: str):
        if not self.available or not self._voices:
            return
        kw = {
            "zh-CN": ["中文", "Chinese", "ZH", "CHS", "普通话"],
            "zh-TW": ["中文", "Chinese", "TW", "CHT", "繁體", "繁体"],
            "en": ["English", "EN"],
        }.get(lang, ["Chinese"])
        for v in self._voices:
            try:
                desc = v.GetDescription()
            except Exception:  # noqa: BLE001
                continue
            if any(k.lower() in desc.lower() for k in kw):
                try:
                    self.voice.Voice = v
                    return
                except Exception:  # noqa: BLE001
                    pass

    def set_rate(self, rate: int):
        if self.available:
            try:
                self.voice.Rate = int(rate)
            except Exception:  # noqa: BLE001
                pass

    def set_volume(self, vol: int):
        if self.available:
            try:
                self.voice.Volume = max(0, min(100, int(vol)))
            except Exception:  # noqa: BLE001
                pass

    def speak(self, text: str, temporary: bool = False):
        if self.available and text:
            try:
                self.voice.Speak(text, 1)
                try:
                    self.voice.WaitUntilDone(-1)
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001
                pass

    def stop(self):
        if self.available:
            try:
                self.voice.Speak("", 3)
            except Exception:  # noqa: BLE001
                pass


class MacSayVoiceEngine:
    """macOS 语音引擎：使用系统内置 ``say`` 命令（NSSpeechSynthesizer）。

    仅在 macOS 上可用；其它平台 available=False，回退到无操作。
    接口与 SapiVoiceEngine 完全一致，供 VoiceEngine 统一调用。
    """

    def __init__(self):
        self.available = sys.platform == "darwin"
        self._voices = []
        self._current = None
        self._rate = 200
        if self.available:
            try:
                out = subprocess.run(
                    ["say", "-v", "?"],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", check=False,
                ).stdout
                for line in out.splitlines():
                    name = line.split()[0] if line.strip() else ""
                    if name:
                        self._voices.append(name)
            except Exception:  # noqa: BLE001
                self._voices = []

    def select_voice(self, lang: str):
        if not self.available or not self._voices:
            return
        kw = {
            "zh-CN": ["Chinese", "Mandarin", "Ting", "Mei", "Yu", "Yue"],
            "zh-TW": ["Taiwan", "Han", "Yue", "Mei"],
            "en": ["English", "Samantha", "Alex", "Daniel", "Victoria"],
        }.get(lang, ["Chinese"])
        for v in self._voices:
            if any(k.lower() in v.lower() for k in kw):
                self._current = v
                return

    def set_rate(self, rate: int):
        # SAPI 的整型档位近似映射到 say 的 wpm。
        try:
            self._rate = int(180 + (int(rate) or 0) * 20)
        except Exception:  # noqa: BLE001
            self._rate = 200

    def set_volume(self, vol: int):
        # say 不支持音量控制；音量由 wav 播放路径（_volume_adjusted_wav）处理。
        pass

    def speak(self, text: str, temporary: bool = False):
        if self.available and text:
            cmd = ["say"]
            if self._current:
                cmd += ["-v", self._current]
            cmd += ["-r", str(self._rate), text]
            try:
                subprocess.run(
                    cmd, check=False,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception:  # noqa: BLE001
                pass

    def stop(self):
        if self.available:
            try:
                subprocess.run(
                    ["killall", "say"], check=False,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception:  # noqa: BLE001
                pass


class LocalSoVitsEngine:
    def __init__(self):
        self.available = _HAS_WINSOUND or (sys.platform == "darwin")
        tts_dir = os.path.join(pathutil.APP_DIR, "my_local_tts")
        runtime_dir = os.path.join(tts_dir, "runtime")
        self.ref_audio = os.path.join(tts_dir, "ref_audio", "reference.wav")
        self.prompt_text = "我打算去吃个寿司郎"
        self.prompt_lang = "zh"
        self.text_lang = "zh"
        self.gpt_python = os.path.join(runtime_dir, "python", "python.exe")
        self.gpt_sovits_root = os.path.join(runtime_dir, "GPT-SoVITS")
        self.gpt_weight = os.path.join(tts_dir, "model_output", "GPT_weights", "my_voice.ckpt")
        self.sovits_weight = os.path.join(tts_dir, "model_output", "SoVITS_weights", "my_voice.pth")
        self._out_path = pathutil.data_file("tts", "at_xiaopp_tts.wav")
        self.speed = 1.0
        self._disabled_until = 0.0
        self._daemon = None
        self._cache_dir = pathutil.data_file("tts", "cache")

    @staticmethod
    def _configured_path(value: str, default: str, must_exist: bool = True) -> str:
        if not value:
            return default
        if not must_exist or os.path.exists(value):
            return value
        return default

    def apply_settings(self):
        opts = config.settings.get("gptSoVits", {}) or {}
        self.ref_audio = self._configured_path(opts.get("refAudio"), self.ref_audio)
        self.prompt_text = opts.get("promptText") or ""
        self.prompt_lang = opts.get("promptLang") or "zh"
        self.text_lang = opts.get("textLang") or "zh"
        self.gpt_python = self._configured_path(opts.get("gptSoVitsPython"), self.gpt_python)
        self.gpt_sovits_root = self._configured_path(opts.get("gptSoVitsRoot"), self.gpt_sovits_root)
        self.gpt_weight = self._configured_path(opts.get("gptWeight"), self.gpt_weight)
        self.sovits_weight = self._configured_path(opts.get("sovitsWeight"), self.sovits_weight)
        self._out_path = self._configured_path(opts.get("outputWav"), self._out_path, must_exist=False)
        self.speed = float(opts.get("speed") or 1.0)

    def _play_wav(self, path: str, *, delete_after: bool = False):
        play_path = _volume_adjusted_wav(path, config.settings.get("volume", 50))
        try:
            _play_wav_file(play_path)
        finally:
            for cleanup in ({play_path, path} if delete_after else {play_path}):
                if cleanup != path or delete_after:
                    try:
                        if os.path.exists(cleanup):
                            os.remove(cleanup)
                    except Exception:  # noqa: BLE001
                        pass

    def _load_prompt_text(self) -> str:
        if self.prompt_text:
            return self.prompt_text
        txt_path = os.path.splitext(self.ref_audio)[0] + ".txt"
        if os.path.exists(txt_path):
            try:
                with open(txt_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:  # noqa: BLE001
                pass
        return ""

    def speak(self, text: str, temporary: bool = False) -> bool:
        if not self.available or not text or time.time() < self._disabled_until:
            return False
        try:
            if temporary:
                temp_dir = pathutil.data_file("tts", "temp")
                os.makedirs(temp_dir, exist_ok=True)
                audio_path = os.path.join(temp_dir, f"temp_{time.time_ns()}.wav")
                self._generate(text, audio_path)
                self._play_wav(audio_path, delete_after=True)
            else:
                audio_path = self._cache_path(text)
                if not os.path.exists(audio_path) or os.path.getsize(audio_path) <= 44:
                    self._generate(text, audio_path)
                self._play_wav(audio_path)
            return True
        except Exception as e:  # noqa: BLE001
            print(f"GPT-SoVITS 播报不可用，已回退 SAPI：{e}")
            self._disabled_until = time.time() + 30
            return False

    def _cache_path(self, text: str) -> str:
        os.makedirs(self._cache_dir, exist_ok=True)
        parts = [
            text,
            self.ref_audio,
            self._load_prompt_text(),
            self.gpt_weight,
            self.sovits_weight,
            str(self.speed),
        ]
        for path in (self.ref_audio, self.gpt_weight, self.sovits_weight):
            try:
                parts.append(str(os.path.getmtime(path)))
            except OSError:
                parts.append("0")
        digest = hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()
        return os.path.join(self._cache_dir, f"{digest}.wav")

    def _generate(self, text: str, output_wav: str):
        project_root = pathutil.APP_DIR
        if self.gpt_python:
            if not os.path.exists(self.gpt_python):
                raise FileNotFoundError(f"内置 GPT-SoVITS Python 不存在：{self.gpt_python}")
            prompt_text = self._load_prompt_text()
            if self._generate_with_daemon(text, prompt_text, output_wav):
                return
            self._generate_once(text, prompt_text, output_wav)
            return

        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from my_local_tts.tts_infer import text_to_wav

        text_to_wav(
            text=text,
            ref_wav_path=self.ref_audio,
            ref_text=self._load_prompt_text(),
            gpt_ckpt_path=self.gpt_weight,
            sovits_pth_path=self.sovits_weight,
            output_wav=output_wav,
            speed=self.speed,
            gpt_sovits_root=self.gpt_sovits_root,
            ref_language=self.prompt_lang,
            target_language=self.text_lang,
        )

    def _startupinfo(self):
        if os.name != "nt":
            return None
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return startupinfo

    def _tts_env(self) -> dict:
        env = os.environ.copy()
        root = self.gpt_sovits_root
        py_dir = os.path.dirname(self.gpt_python)
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in [root, os.path.join(root, "GPT_SoVITS"), os.path.join(root, "tools"), os.path.join(root, "tools", "asr"), os.path.join(root, "tools", "uvr5")] if p
        )
        env["PATH"] = os.pathsep.join(
            p for p in [os.path.join(py_dir, "Library", "bin"), py_dir, os.path.join(py_dir, "Scripts"), env.get("PATH", "")] if p
        )
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def _daemon_request(self, text: str, prompt_text: str, output_wav: str) -> dict:
        return {
            "text": text,
            "ref_audio": self.ref_audio,
            "ref_text": prompt_text,
            "gpt_weight": self.gpt_weight,
            "sovits_weight": self.sovits_weight,
            "output_wav": output_wav,
            "speed": self.speed,
            "gpt_sovits_root": self.gpt_sovits_root,
            "ref_language": self.prompt_lang,
            "target_language": self.text_lang,
        }

    def _ensure_daemon(self) -> bool:
        if self._daemon is not None and self._daemon.poll() is None:
            return True
        self._daemon = None
        script = os.path.join(pathutil.APP_DIR, "my_local_tts", "tts_daemon.py")
        if not os.path.exists(script):
            return False
        try:
            self._daemon = subprocess.Popen(
                [self.gpt_python, script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=self._startupinfo(),
                env=self._tts_env(),
            )
            return True
        except Exception:  # noqa: BLE001
            self._daemon = None
            return False

    def _generate_with_daemon(self, text: str, prompt_text: str, output_wav: str) -> bool:
        if not self._ensure_daemon() or self._daemon is None or self._daemon.stdin is None or self._daemon.stdout is None:
            return False
        try:
            payload = json.dumps(self._daemon_request(text, prompt_text, output_wav), ensure_ascii=False)
            self._daemon.stdin.write(payload + "\n")
            self._daemon.stdin.flush()
            line = self._daemon.stdout.readline()
            if not line:
                return False
            reply = json.loads(line)
            if not reply.get("ok"):
                raise RuntimeError(reply.get("error") or "daemon 生成失败")
            return True
        except Exception:
            self._stop_daemon()
            return False

    def _generate_once(self, text: str, prompt_text: str, output_wav: str):
        script = os.path.join(pathutil.APP_DIR, "my_local_tts", "tts_infer.py")
        cmd = [
            self.gpt_python,
            script,
            "--text",
            text,
            "--ref-audio",
            self.ref_audio,
            "--ref-text",
            prompt_text,
            "--gpt-weight",
            self.gpt_weight,
            "--sovits-weight",
            self.sovits_weight,
            "--output-wav",
            output_wav,
            "--speed",
            str(self.speed),
            "--ref-language",
            self.prompt_lang,
            "--target-language",
            self.text_lang,
        ]
        if self.gpt_sovits_root:
            cmd.extend(["--gpt-sovits-root", self.gpt_sovits_root])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=self._startupinfo(),
            env=self._tts_env(),
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "未知错误").strip()
            raise RuntimeError(f"外部 GPT-SoVITS 推理失败：{detail}")

    def _stop_daemon(self):
        proc = self._daemon
        self._daemon = None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass

    def stop(self):
        self._stop_daemon()
        if _HAS_WINSOUND:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:  # noqa: BLE001
                pass


class VoiceEngine:
    def __init__(self):
        self.sapi = MacSayVoiceEngine() if sys.platform != "win32" else SapiVoiceEngine()
        self.sovits = LocalSoVitsEngine()
        self.engine_name = "sapi"

    def select_voice(self, lang: str):
        self.sapi.select_voice(lang)

    def set_rate(self, rate: int):
        self.sapi.set_rate(rate)

    def set_volume(self, vol: int):
        self.sapi.set_volume(vol)

    def apply_settings(self):
        self.engine_name = config.settings.get("voiceEngine", "sapi")
        self.sovits.apply_settings()

    def speak(self, text: str, temporary: bool = False):
        prepared = voice_media.find_prepared(text)
        if prepared and (sys.platform != "win32" or _HAS_WINSOUND) and not temporary:
            try:
                play_path = _volume_adjusted_wav(prepared, config.settings.get("volume", 50))
                try:
                    _play_wav_file(play_path)
                finally:
                    try:
                        if play_path != prepared and os.path.exists(play_path):
                            os.remove(play_path)
                    except Exception:  # noqa: BLE001
                        pass
                return
            except Exception:  # noqa: BLE001
                pass
        if self.engine_name == "gpt_sovits" and self.sovits.speak(text, temporary=temporary):
            return
        self.sapi.speak(text)

    def play_wav(self, path: str):
        if not path or not os.path.exists(path):
            return
        if sys.platform == "win32" and not _HAS_WINSOUND:
            return
        play_path = _volume_adjusted_wav(path, config.settings.get("volume", 50))
        try:
            _play_wav_file(play_path)
        finally:
            try:
                if play_path != path and os.path.exists(play_path):
                    os.remove(play_path)
            except Exception:  # noqa: BLE001
                pass

    def stop(self):
        self.sovits.stop()
        self.sapi.stop()


class VoiceWorker(QObject):
    request_speak = pyqtSignal(str)
    request_speak_temp = pyqtSignal(str)
    request_play_wav = pyqtSignal(str)
    request_stop = pyqtSignal()
    spoken = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.engine = None
        self.request_speak.connect(self.do_speak)
        self.request_speak_temp.connect(self.do_speak_temp)
        self.request_play_wav.connect(self.do_play_wav)
        self.request_stop.connect(self.do_stop)

    @pyqtSlot()
    def bootstrap(self):
        if self.engine is None:
            self.engine = VoiceEngine()
            apply_settings_to_voice()

    @pyqtSlot(str)
    def do_speak(self, text: str):
        if self.engine is None:
            self.bootstrap()
        self.engine.speak(text)
        self.spoken.emit()

    @pyqtSlot(str)
    def do_speak_temp(self, text: str):
        if self.engine is None:
            self.bootstrap()
        self.engine.speak(text, temporary=True)
        self.spoken.emit()

    @pyqtSlot(str)
    def do_play_wav(self, path: str):
        if self.engine is None:
            self.bootstrap()
        self.engine.play_wav(path)
        self.spoken.emit()

    @pyqtSlot()
    def do_stop(self):
        if self.engine is not None:
            self.engine.stop()


_engine = None
_bridge = None
_thread = None


def init_voice():
    """在主线程初始化语音引擎与桥接对象。"""
    global _engine, _bridge, _thread
    _thread = QThread()
    _bridge = VoiceWorker()
    _bridge.moveToThread(_thread)
    _thread.started.connect(_bridge.bootstrap)
    _thread.start()


def apply_settings_to_voice():
    """根据当前设置同步音量/语言/语速。"""
    if _bridge is None or _bridge.engine is None:
        return
    _bridge.engine.apply_settings()
    _bridge.engine.set_volume(config.settings.get("volume", 50))
    _bridge.engine.select_voice(config.settings.get("language", "zh-CN"))
    # SAPI 语速是整数档位；从当前偏快档位下调一档，接近 0.9 倍体感速度。
    _bridge.engine.set_rate(1)


def say(text: str):
    """线程安全的语音播报（自动应用 捏 规则）。"""
    if _bridge is None or not text:
        return False
    text = apply_ni(text)
    _bridge.request_speak.emit(text)
    return True


def say_temporary(text: str):
    """线程安全的临时语音播报，播完即删文件。"""
    if _bridge is None or not text:
        return False
    text = apply_ni(text)
    _bridge.request_speak_temp.emit(text)
    return True


def say_wav(path: str):
    """线程安全播放指定 wav，播完触发 spoken。"""
    if _bridge is None or not path:
        return False
    _bridge.request_play_wav.emit(path)
    return True


def stop_speaking():
    """立即清空当前语音队列并停止播报。"""
    if _bridge is None:
        return
    _bridge.request_stop.emit()


def on_spoken(callback):
    """在当前播报完成后调用一次。"""
    if _bridge is None:
        return False
    def _once():
        try:
            _bridge.spoken.disconnect(_once)
        except Exception:  # noqa: BLE001
            pass
        callback()
    _bridge.spoken.connect(_once)
    return True


def _play_wav_file(path: str) -> None:
    """跨平台播放 wav：Windows 用 winsound，macOS 用系统 afplay。"""
    if not path or not os.path.exists(path):
        return
    if sys.platform == "win32":
        if _HAS_WINSOUND:
            try:
                winsound.PlaySound(path, winsound.SND_FILENAME)
            except Exception:  # noqa: BLE001
                pass
        return
    if sys.platform == "darwin":
        try:
            subprocess.run(
                ["afplay", path], check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:  # noqa: BLE001
            pass


def _volume_adjusted_wav(source: str, volume: int) -> str:
    """Return a temporary wav scaled to app volume for winsound playback."""
    vol = max(0, min(100, int(volume)))
    if vol >= 99:
        return source
    out_dir = pathutil.data_file("tts", "volume_playback")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"play_{os.getpid()}_{time.time_ns()}.wav")
    factor = vol / 100.0
    with wave.open(source, "rb") as src:
        params = src.getparams()
        frames = src.readframes(src.getnframes())
    if frames and params.sampwidth in (1, 2, 3, 4):
        frames = audioop.mul(frames, params.sampwidth, factor)
    with wave.open(out, "wb") as dst:
        dst.setparams(params)
        dst.writeframes(frames)
    return out
