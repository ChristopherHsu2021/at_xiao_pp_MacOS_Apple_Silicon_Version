"""快速、非阻塞的音频时长探测（基于文件头解析）并带磁盘缓存。

本模块为卜卜音悦播放器移植到 AT小PP 的适配版本：
- 缓存写入 AT小PP 的 data/music/meta/durations.json
- 其余解析逻辑与卜卜音悦保持一致。
"""

from __future__ import annotations

import json
import os
import threading

from app.core import pathutil


_CACHE_LOCK = threading.Lock()
_cache: dict | None = None  # {abspath: [mtime, size, seconds]}


def _cache_path() -> str:
    return pathutil.data_file("music", "meta", "durations.json")


def _load_cache() -> None:
    global _cache
    if _cache is not None:
        return
    try:
        with open(_cache_path(), "r", encoding="utf-8") as f:
            _cache = json.load(f)
    except Exception:  # noqa: BLE001
        _cache = {}


def _save_cache() -> None:
    try:
        path = _cache_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_cache, f)
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        pass


def get_duration(path: str) -> float | None:
    """返回时长（秒，float）或 None（无法解析时）。"""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = os.path.abspath(path)
    _load_cache()
    cached = _cache.get(key)
    if cached and len(cached) == 3 and cached[0] == st.st_mtime and cached[1] == st.st_size:
        return cached[2]
    secs = _probe(path, st.st_size)
    if secs:
        with _CACHE_LOCK:
            if _cache is None:
                _load_cache()
            _cache[key] = [st.st_mtime, st.st_size, secs]
            _save_cache()
    return secs


# ---------------------------------------------------------------------------
# 各格式解析器（均不解码音频，仅读取头部元数据）
# ---------------------------------------------------------------------------

_MP3_BITRATES = {
    # (version, layer): 16 项码率表（kbps），索引为帧头 br_idx(0..15)
    (3, 3): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, 0],   # MPEG1 L1
    (3, 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 0],       # MPEG1 L2
    (3, 1): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],        # MPEG1 L3
    (2, 3): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, 0],       # MPEG2/2.5 L1
    (2, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],            # MPEG2/2.5 L2
    (2, 1): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],            # MPEG2/2.5 L3
    (0, 3): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, 0],       # MPEG2.5 L1
    (0, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],            # MPEG2.5 L2
    (0, 1): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],            # MPEG2.5 L3
}

_MP3_SAMPLERATES = {
    3: [44100, 48000, 32000, 0],   # MPEG1
    2: [22050, 24000, 16000, 0],   # MPEG2
    0: [11025, 12000, 8000, 0],    # MPEG2.5
}

# 每帧采样数：(version, layer) -> 采样数
_MP3_SAMPLES_PER_FRAME = {
    (3, 3): 384, (3, 2): 1152, (3, 1): 1152,
    (2, 3): 384, (2, 2): 1152, (2, 1): 576,
    (0, 3): 384, (0, 2): 1152, (0, 1): 576,
}


def _mp3_duration(path: str, size: int) -> float | None:
    try:
        with open(path, "rb") as f:
            head = f.read(65536)
    except OSError:
        return None
    i = 0
    n = len(head)
    while i + 4 <= n:
        if head[i] != 0xFF or (head[i + 1] & 0xE0) != 0xE0:
            i += 1
            continue
        ver = (head[i + 1] >> 3) & 0x03
        layer = (head[i + 1] >> 1) & 0x03
        br_idx = (head[i + 2] >> 4) & 0x0F
        sr_idx = (head[i + 2] >> 2) & 0x03
        padding = (head[i + 2] >> 1) & 0x01
        # 校验字段合法性
        if ver == 1 or layer == 0 or br_idx in (0, 15) or sr_idx == 3:
            i += 1
            continue
        bitrate = _MP3_BITRATES[(ver, layer)][br_idx]
        samplerate = _MP3_SAMPLERATES[ver][sr_idx]
        if not bitrate or not samplerate:
            i += 1
            continue
        # 探测 VBR（Xing / Info）帧数
        frames = _mp3_vbr_frames(head, i, ver)
        if frames:
            spf = _MP3_SAMPLES_PER_FRAME[(ver, layer)]
            return frames * spf / samplerate
        # CBR 估算：时长 ≈ 文件字节数 / (码率 / 8)
        return size * 8 / (bitrate * 1000)
    return None


def _mp3_vbr_frames(head: bytes, i: int, ver: int) -> int | None:
    off = i + 4
    if head[off:off + 4] in (b"Xing", b"Info"):
        flags = int.from_bytes(head[off + 4:off + 8], "big")
        p = off + 8
        if flags & 0x0001:  # frames 标志位
            if p + 4 <= len(head):
                return int.from_bytes(head[p:p + 4], "big")
    return None


def _flac_duration(path: str) -> float | None:
    try:
        with open(path, "rb") as f:
            head = f.read(42)
    except OSError:
        return None
    if len(head) < 42 or head[0:4] != b"fLaC":
        return None
    b = head[8:42]  # STREAMINFO 内容（34 字节）

    def bits(off: int, count: int) -> int:
        result = 0
        for k in range(count):
            byte = b[(off + k) // 8]
            bit = (byte >> (7 - ((off + k) % 8))) & 1
            result = (result << 1) | bit
        return result

    # 前 80 bit: min/max block size(16+16) + min/max frame size(24+24)
    samplerate = bits(80, 20)
    # 再跳过 3(channels)+5(bps)=8 bit，取 36 bit total_samples
    total_samples = bits(108, 36)
    if samplerate and total_samples:
        return total_samples / samplerate
    return None


def _wav_duration(path: str) -> float | None:
    try:
        with open(path, "rb") as f:
            head = f.read(12)
            if len(head) < 12 or head[0:4] != b"RIFF" or head[8:12] != b"WAVE":
                return None
            channels = samplerate = byterate = bits = None
            while True:
                chunk = f.read(8)
                if len(chunk) < 8:
                    break
                cid = chunk[0:4]
                clen = int.from_bytes(chunk[4:8], "little")
                if cid == b"fmt ":
                    fmt = f.read(clen)
                    if len(fmt) >= 16:
                        channels = int.from_bytes(fmt[2:4], "little")
                        samplerate = int.from_bytes(fmt[4:8], "little")
                        byterate = int.from_bytes(fmt[8:12], "little")
                        bits = int.from_bytes(fmt[14:16], "little")
                    if clen > 16:
                        f.seek(clen - 16, 1)
                elif cid == b"data":
                    if byterate:
                        return clen / byterate
                    if channels and samplerate and bits:
                        return clen / (channels * samplerate * (bits // 8))
                    return None
                else:
                    f.seek(clen, 1)
                    if clen & 1:
                        f.seek(1, 1)
    except OSError:
        return None
    return None


def _m4a_duration(path: str) -> float | None:
    # 尽力而为：在前 512KB 内寻找 mvhd，读取 timescale / duration
    try:
        with open(path, "rb") as f:
            data = f.read(512 * 1024)
    except OSError:
        return None
    idx = data.find(b"mvhd")
    if idx < 0:
        return None
    p = idx + 8  # 跳过 size(4) + 'mvhd'(4)
    if p + 24 > len(data):
        return None
    try:
        ver = data[p]
        if ver == 1:
            ts = int.from_bytes(data[p + 20:p + 24], "big")
            dur = int.from_bytes(data[p + 24:p + 32], "big")
        else:
            ts = int.from_bytes(data[p + 12:p + 16], "big")
            dur = int.from_bytes(data[p + 16:p + 20], "big")
    except Exception:  # noqa: BLE001
        return None
    if ts:
        return dur / ts
    return None


def _probe(path: str, size: int) -> float | None:
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".wav":
            return _wav_duration(path)
        if ext == ".flac":
            return _flac_duration(path)
        if ext in (".mp3", ".mp2"):
            return _mp3_duration(path, size)
        if ext in (".m4a", ".mp4", ".aac"):
            return _m4a_duration(path)
    except Exception:  # noqa: BLE001
        return None
    return None
