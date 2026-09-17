"""Pre-generated voice media management for low-latency playback."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.core import config, pathutil


PREGENERATED_DIR_NAME = "Generated Voice Media"
ADDITIONAL_DIR_NAME = "Additional Voice Media"


class VoiceMediaQualityError(RuntimeError):
    pass


def prepared_dir() -> str:
    return pathutil.data_file("voice", PREGENERATED_DIR_NAME)


def bundled_prepared_dir() -> str:
    bundled = os.path.join(pathutil.get_bundled_data_dir(), "voice", PREGENERATED_DIR_NAME)
    if os.path.isdir(bundled):
        return bundled
    return os.path.join(pathutil.APP_DIR, "data", "voice", PREGENERATED_DIR_NAME)


def additional_dir() -> str:
    return pathutil.data_file("voice", ADDITIONAL_DIR_NAME)


def text_key(text: str) -> str:
    normalized = (text or "").strip()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def media_path_for_text(text: str, folder: str | None = None) -> str:
    return os.path.join(folder or prepared_dir(), f"{text_key(text)}.wav")


def find_prepared(text: str) -> str | None:
    key = text_key(text)
    for folder in (additional_dir(), prepared_dir(), bundled_prepared_dir()):
        path = os.path.join(folder, f"{key}.wav")
        if os.path.exists(path) and os.path.getsize(path) > 44:
            return path
    return None


def safe_label(text: str, limit: int = 28) -> str:
    label = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", (text or "").strip())
    label = re.sub(r"\s+", "", label)[:limit]
    return label or "voice"


def tts_text(text: str) -> str:
    """Normalize app-brand mixed text so Chinese-only TTS does not need NLTK."""
    return (text or "").replace("AT小PP", "诶替小屁屁")


def _load_audio(path: str):
    import numpy as np
    import soundfile as sf

    data, rate = sf.read(path, dtype="float32", always_2d=True)
    if data.size == 0 or rate <= 0:
        raise VoiceMediaQualityError(f"生成音频为空：{path}")
    mono = data.mean(axis=1)
    return data, mono, rate


def analyze_wav(path: str) -> dict:
    """Return lightweight speech-presence metrics for generated wav quality checks."""
    import numpy as np

    data, mono, rate = _load_audio(path)
    abs_mono = np.abs(mono)
    duration = len(mono) / rate
    peak = float(abs_mono.max(initial=0.0))
    rms = float(np.sqrt(np.mean(mono * mono))) if len(mono) else 0.0
    if peak < 0.002 or rms < 0.0008:
        return {"duration": duration, "lead": duration, "active": 0.0, "rms": rms, "peak": peak, "valid": False}

    frame = max(1, int(rate * 0.02))
    hop = max(1, int(rate * 0.01))
    if len(mono) <= frame:
        frame_rms = np.array([rms], dtype="float32")
    else:
        starts = np.arange(0, len(mono) - frame + 1, hop)
        frame_rms = np.array([np.sqrt(np.mean(mono[s:s + frame] ** 2)) for s in starts], dtype="float32")
    noise = float(np.percentile(frame_rms, 12)) if len(frame_rms) else 0.0
    voice_ref = float(np.percentile(abs_mono, 95))
    threshold = max(0.004, noise * 3.0, voice_ref * 0.08)
    active_idx = np.flatnonzero(frame_rms > threshold)
    if active_idx.size == 0:
        return {"duration": duration, "lead": duration, "active": 0.0, "rms": rms, "peak": peak, "valid": False}
    first = int(active_idx[0] * hop)
    last = int(min(len(mono), active_idx[-1] * hop + frame))
    lead = first / rate
    active = max(0.0, (last - first) / rate)
    return {"duration": duration, "lead": lead, "active": active, "rms": rms, "peak": peak, "valid": active >= 0.30 and rms >= 0.0025}


def postprocess_wav(path: str, *, max_lead_ms: int = 90, tail_ms: int = 520) -> dict:
    """Trim generated wav so speech starts quickly and reject silent output."""
    import numpy as np
    import soundfile as sf

    data, mono, rate = _load_audio(path)
    metrics = analyze_wav(path)
    if not metrics["valid"]:
        raise VoiceMediaQualityError(f"生成音频疑似无声或有效语音过短：{path}")

    abs_mono = np.abs(mono)
    frame = max(1, int(rate * 0.02))
    hop = max(1, int(rate * 0.01))
    starts = np.arange(0, max(1, len(mono) - frame + 1), hop)
    frame_rms = np.array([np.sqrt(np.mean(mono[s:min(len(mono), s + frame)] ** 2)) for s in starts], dtype="float32")
    noise = float(np.percentile(frame_rms, 12)) if len(frame_rms) else 0.0
    threshold = max(0.004, noise * 3.0, float(np.percentile(abs_mono, 95)) * 0.08)
    active_idx = np.flatnonzero(frame_rms > threshold)
    if active_idx.size == 0:
        raise VoiceMediaQualityError(f"生成音频疑似无声：{path}")
    first = int(active_idx[0] * hop)
    last = int(min(len(mono), active_idx[-1] * hop + frame))
    keep_lead = int(rate * max_lead_ms / 1000)
    keep_tail = int(rate * tail_ms / 1000)
    start = max(0, first - keep_lead)
    end = min(len(mono), last + keep_tail)
    if start > 0 or end < len(mono):
        tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"at_xiaopp_post_{os.getpid()}_{time.time_ns()}.wav",
        )
        sf.write(tmp_path, data[start:end], rate, subtype="PCM_16")
        try:
            os.replace(tmp_path, path)
        except OSError:
            shutil.copyfile(tmp_path, path)
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    final_metrics = analyze_wav(path)
    if not final_metrics["valid"] or final_metrics["lead"] > 0.18:
        raise VoiceMediaQualityError(f"生成音频开头空白过长或质量异常：{path}")
    return final_metrics


def needs_regeneration(path: str) -> bool:
    if not os.path.exists(path) or os.path.getsize(path) <= 44:
        return True
    try:
        metrics = analyze_wav(path)
        return (not metrics["valid"]) or metrics["lead"] > 0.20
    except Exception:  # noqa: BLE001
        return True


def save_additional(source_wav: str, text: str) -> str:
    if not os.path.exists(source_wav) or os.path.getsize(source_wav) <= 44:
        raise FileNotFoundError(f"音频不存在或无效：{source_wav}")
    folder = additional_dir()
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, f"{text_key(text)}.wav")
    shutil.copyfile(source_wav, dest)
    meta = os.path.join(folder, f"{text_key(text)}.json")
    with open(meta, "w", encoding="utf-8") as f:
        json.dump({"text": text, "file": os.path.basename(dest)}, f, ensure_ascii=False, indent=2)
    return dest


def _configured_path(value: str, default: str, must_exist: bool = True) -> str:
    if not value:
        return default
    if not must_exist or os.path.exists(value):
        return value
    return default


def tts_settings() -> dict:
    tts_dir = os.path.join(pathutil.APP_DIR, "my_local_tts")
    runtime_dir = os.path.join(tts_dir, "runtime")
    defaults = {
        "refAudio": os.path.join(tts_dir, "ref_audio", "reference.wav"),
        "promptText": "",
        "promptLang": "zh",
        "textLang": "zh",
        "gptSoVitsPython": os.path.join(runtime_dir, "python", "python.exe"),
        "gptSoVitsRoot": os.path.join(runtime_dir, "GPT-SoVITS"),
        "gptWeight": os.path.join(tts_dir, "model_output", "GPT_weights", "my_voice.ckpt"),
        "sovitsWeight": os.path.join(tts_dir, "model_output", "SoVITS_weights", "my_voice.pth"),
        "speed": 1.0,
    }
    opts = config.settings.get("gptSoVits", {}) or {}
    return {
        "ref_audio": _configured_path(opts.get("refAudio"), defaults["refAudio"]),
        "ref_text": opts.get("promptText") or _read_ref_text(defaults["refAudio"]),
        "ref_language": opts.get("promptLang") or defaults["promptLang"],
        "target_language": opts.get("textLang") or defaults["textLang"],
        "python": _configured_path(opts.get("gptSoVitsPython"), defaults["gptSoVitsPython"]),
        "root": _configured_path(opts.get("gptSoVitsRoot"), defaults["gptSoVitsRoot"]),
        "gpt_weight": _configured_path(opts.get("gptWeight"), defaults["gptWeight"]),
        "sovits_weight": _configured_path(opts.get("sovitsWeight"), defaults["sovitsWeight"]),
        "speed": float(opts.get("speed") or defaults["speed"]),
    }


def _read_ref_text(ref_audio: str) -> str:
    txt = os.path.splitext(ref_audio)[0] + ".txt"
    try:
        with open(txt, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:  # noqa: BLE001
        return ""


def _startupinfo():
    if os.name != "nt":
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return startupinfo


def _tts_env(settings: dict) -> dict:
    env = os.environ.copy()
    root = settings["root"]
    py_dir = os.path.dirname(settings["python"])
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in [pathutil.APP_DIR, root, os.path.join(root, "GPT_SoVITS"), os.path.join(root, "tools"), os.path.join(root, "tools", "asr"), os.path.join(root, "tools", "uvr5")] if p
    )
    env["PATH"] = os.pathsep.join(
        p for p in [os.path.join(py_dir, "Library", "bin"), py_dir, os.path.join(py_dir, "Scripts"), env.get("PATH", "")] if p
    )
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["is_half"] = env.get("is_half", "True")
    return env


_DAEMON_PROC = None


def _daemon_script() -> str:
    return os.path.join(pathutil.APP_DIR, "my_local_tts", "tts_daemon.py")


def _ensure_daemon(settings: dict):
    global _DAEMON_PROC
    if _DAEMON_PROC is not None and _DAEMON_PROC.poll() is None:
        return _DAEMON_PROC
    _DAEMON_PROC = None
    script = _daemon_script()
    if not os.path.exists(script):
        return None
    try:
        _DAEMON_PROC = subprocess.Popen(
            [settings["python"], script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=_startupinfo(),
            env=_tts_env(settings),
        )
        return _DAEMON_PROC
    except Exception:  # noqa: BLE001
        _DAEMON_PROC = None
        return None


def _generate_with_daemon(settings: dict, text: str, output_wav: str) -> bool:
    proc = _ensure_daemon(settings)
    if proc is None or proc.stdin is None or proc.stdout is None:
        return False
    try:
        payload = {
            "text": tts_text(text),
            "ref_audio": settings["ref_audio"],
            "ref_text": settings["ref_text"],
            "gpt_weight": settings["gpt_weight"],
            "sovits_weight": settings["sovits_weight"],
            "output_wav": output_wav,
            "speed": settings["speed"],
            "gpt_sovits_root": settings["root"],
            "ref_language": settings["ref_language"],
            "target_language": settings["target_language"],
        }
        proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            return False
        reply = json.loads(line)
        return bool(reply.get("ok"))
    except Exception:  # noqa: BLE001
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        return False


def generate_to_file(text: str, output_wav: str, *, speed: float | None = None) -> str:
    text = (text or "").strip()
    if not text:
        raise ValueError("内容不能为空")
    settings = tts_settings()
    if speed is not None:
        settings["speed"] = float(speed)
    Path(output_wav).parent.mkdir(parents=True, exist_ok=True)
    script = os.path.join(pathutil.APP_DIR, "my_local_tts", "tts_infer.py")
    last_error = ""
    for attempt in range(3):
        tmp = output_wav
        if attempt:
            tmp = os.path.join(tempfile.gettempdir(), f"at_xiaopp_voice_retry_{os.getpid()}_{attempt}.wav")
        if not _generate_with_daemon(settings, text, tmp):
            cmd = [
                settings["python"], script,
                "--text", tts_text(text),
                "--ref-audio", settings["ref_audio"],
                "--ref-text", settings["ref_text"],
                "--gpt-weight", settings["gpt_weight"],
                "--sovits-weight", settings["sovits_weight"],
                "--output-wav", tmp,
                "--speed", str(settings["speed"]),
                "--gpt-sovits-root", settings["root"],
                "--ref-language", settings["ref_language"],
                "--target-language", settings["target_language"],
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=_startupinfo(),
                env=_tts_env(settings),
                timeout=180,
                check=False,
            )
            if result.returncode != 0:
                last_error = (result.stderr or result.stdout or "未知错误").strip()
                continue
        if not os.path.exists(tmp) or os.path.getsize(tmp) <= 44:
            last_error = f"生成音频无效：{tmp}"
            continue
        try:
            postprocess_wav(tmp)
            if tmp != output_wav:
                shutil.copyfile(tmp, output_wav)
            return output_wav
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
    raise RuntimeError(f"生成失败：{last_error or '音频质量检查未通过'}")
    return output_wav


def generate_prepared(text: str, *, speed: float | None = None) -> str:
    return generate_to_file(text, media_path_for_text(text), speed=speed)
