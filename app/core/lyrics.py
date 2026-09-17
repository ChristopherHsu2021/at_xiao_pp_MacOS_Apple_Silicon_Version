"""LRCLIB lyric lookup, local cache, and LRC line selection."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from app.core import config, pathutil
from app.core.i18n import SIM2TW


LRCLIB_GET = "https://lrclib.net/api/get"
LRCLIB_SEARCH = "https://lrclib.net/api/search"
LRCAPI_SINGLE = "https://api.lrc.cx/api/v1/lyrics/single"
TIMEOUT = 12
HEADERS = {"User-Agent": "ATXiaoPP/1.0 (lrclib lyric client)"}

_download_lock = threading.Lock()
_downloading: set[str] = set()
_requested: dict[str, float] = {}
REQUEST_RETRY_SECONDS = 180
_converter_cache = {}

TW2SIM = {v: k for k, v in SIM2TW.items() if len(k) == 1 and len(v) == 1}
SIM_EXTRA = {
    "爱": "愛", "会": "會", "说": "說", "听": "聽", "为": "為", "无": "無",
    "与": "與", "风": "風", "梦": "夢", "泪": "淚", "云": "雲", "电": "電",
    "声": "聲", "乐": "樂", "万": "萬", "东": "東", "后": "後", "从": "從",
    "对": "對", "长": "長", "台": "臺",
}
TW2SIM.update({
    "愛": "爱", "會": "会", "說": "说", "聽": "听", "為": "为", "無": "无",
    "與": "与", "風": "风", "夢": "梦", "淚": "泪", "雲": "云", "電": "电",
    "聲": "声", "樂": "乐", "萬": "万", "東": "东", "後": "后", "從": "从",
    "對": "对", "還": "还", "讓": "让", "長": "长", "點": "点", "臺": "台",
})
SIMPLIFIED_MARKERS = set(SIM_EXTRA) | set(TW2SIM.values())
TRADITIONAL_MARKERS = set(TW2SIM)
LYRIC_SIMPLIFY_EXTRA = str.maketrans({
    "妳": "你",
    "著": "着",
    "裡": "里",
    "裏": "里",
    "麼": "么",
    "麽": "么",
    "爲": "为",
    "為": "为",
    "於": "于",
    "乾": "干",
    "幹": "干",
    "纔": "才",
    "卻": "却",
    "祇": "只",
    "衹": "只",
    "鐘": "钟",
    "鍾": "钟",
    "鬱": "郁",
    "臺": "台",
    "檯": "台",
    "颱": "台",
    "徵": "征",
    "復": "复",
    "複": "复",
    "髮": "发",
    "瞭": "了",
    "喫": "吃",
    "囉": "啰",
    "囁": "嗫",
    "菸": "烟",
    "彆": "别",
    "週": "周",
    "洩": "泄",
    "佔": "占",
    "拚": "拼",
    "瀰": "弥",
    "夥": "伙",
    "讚": "赞",
})


def lyrics_dir() -> str:
    return os.path.dirname(pathutil.data_file("music", "lyrics", ".keep"))


def safe_filename(name: str) -> str:
    for c in '<>:"/\\|?*':
        name = name.replace(c, "_")
    return name.strip().strip(".") or "unknown"


def track_key(path: str) -> str:
    track, artist = _split_track_artist(path)
    return safe_filename(f"{track} - {artist}" if artist else track)


def _unique_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _candidate_keys(path: str) -> list[str]:
    keys = [track_key(path)]
    stem = os.path.splitext(os.path.basename(path))[0].strip()
    stem = re.sub(r"\s*\[\d+\]$", "", stem)
    stem = " ".join(stem.split())
    if stem:
        keys.append(safe_filename(stem))
    return list(dict.fromkeys(keys))


def lyric_paths(path: str) -> list[str]:
    return _unique_paths([os.path.join(lyrics_dir(), key + ".lrc") for key in _candidate_keys(path)])


def plain_lyric_paths(path: str) -> list[str]:
    return _unique_paths([os.path.join(lyrics_dir(), key + ".txt") for key in _candidate_keys(path)])


def lyric_path(path: str) -> str:
    return lyric_paths(path)[0]


def plain_lyric_path(path: str) -> str:
    return plain_lyric_paths(path)[0]


def has_lyrics(path: str) -> bool:
    return existing_lyric_file(path) is not None


def existing_lyric_file(path: str) -> str | None:
    for candidate in lyric_paths(path) + plain_lyric_paths(path):
        if os.path.exists(candidate):
            return candidate
    return None


def _split_track_artist(path: str) -> tuple[str, str | None]:
    try:
        from app.core import music_api

        cached = music_api.cache_info(path)
    except Exception:  # noqa: BLE001
        cached = None
    if isinstance(cached, dict):
        title = " ".join(str(cached.get("name") or "").split()).strip()
        artist = " ".join(str(cached.get("artist") or "").split()).strip()
        if title:
            return title, artist or None
    stem = os.path.splitext(os.path.basename(path))[0].strip()
    stem = re.sub(r"\s*\[\d+\]$", "", stem)
    stem = " ".join(stem.split())
    for sep in (" - ", "－", "—", "–", "-"):
        if sep in stem:
            left, right = stem.rsplit(sep, 1)
            left, right = " ".join(left.split()).strip(), " ".join(right.split()).strip()
            if left and right:
                return left, right
    return stem, None


def _duration_seconds(duration_text: str | None) -> int | None:
    if not duration_text or duration_text == "--:--":
        return None
    try:
        minute, second = duration_text.split(":", 1)
        return int(minute) * 60 + int(second)
    except (ValueError, AttributeError):
        return None


def _request_json(url: str, params: dict[str, object], timeout: int = TIMEOUT) -> object | None:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    req = urllib.request.Request(f"{url}?{query}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _norm_text(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").lower())


def _looks_like_lrc(text: str) -> bool:
    return bool(_TIME_RE.search(text or ""))


def _pick_text(item: dict) -> tuple[str, bool]:
    synced = (item.get("syncedLyrics") or "").strip()
    if synced:
        return synced, True
    for key in ("plainLyrics", "lyric", "lyrics", "lrc", "text"):
        text = (item.get(key) or "").strip()
        if text:
            return text, _looks_like_lrc(text)
    return "", False


def _fetch_lrclib(track_name: str, artist_name: str | None, duration: int | None) -> tuple[str, bool]:
    try:
        data = _request_json(
            LRCLIB_GET,
            {"track_name": track_name, "artist_name": artist_name, "duration": duration},
        )
    except Exception:  # noqa: BLE001
        data = None
    if isinstance(data, dict):
        text, synced = _pick_text(data)
        if text:
            return text, synced

    try:
        data = _request_json(LRCLIB_SEARCH, {"track_name": track_name, "artist_name": artist_name})
    except Exception:  # noqa: BLE001
        data = None
    if isinstance(data, list):
        target_title = _norm_text(track_name)
        target_artist = _norm_text(artist_name)
        for item in data:
            if not isinstance(item, dict):
                continue
            title_ok = not target_title or _norm_text(item.get("trackName")) == target_title
            artist_ok = not target_artist or target_artist in _norm_text(item.get("artistName"))
            if not (title_ok and artist_ok):
                continue
            text, synced = _pick_text(item)
            if text:
                return text, synced
        for item in data:
            if isinstance(item, dict):
                text, synced = _pick_text(item)
                if text:
                    return text, synced
    return "", False


def _fetch_lrcapi(track_name: str, artist_name: str | None, duration: int | None) -> tuple[str, bool]:
    del duration
    try:
        data = _request_json(LRCAPI_SINGLE, {"title": track_name, "artist": artist_name}, timeout=5)
    except Exception:  # noqa: BLE001
        return "", False
    if isinstance(data, dict):
        text, synced = _pick_text(data)
        if text:
            return text, synced
        nested = data.get("data")
        if isinstance(nested, dict):
            return _pick_text(nested)
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                text, synced = _pick_text(item)
                if text:
                    return text, synced
    return "", False


def _fetch_kuwo(track_name: str, artist_name: str | None, duration: int | None) -> tuple[str, bool]:
    try:
        from app.core import music_api

        query = f"{track_name} {artist_name or ''}".strip()
        for item in music_api.search(query, size=8):
            title_ok = _norm_text(item.get("name")) == _norm_text(track_name)
            artist_ok = not artist_name or _norm_text(artist_name) in _norm_text(item.get("artist"))
            expected = duration or 0
            actual = int(item.get("duration") or 0)
            duration_ok = expected <= 0 or actual <= 0 or abs(actual - expected) <= 8
            if not (title_ok and artist_ok and duration_ok):
                continue
            text = music_api.get_lrc(item.get("rid") or item.get("id") or "")
            if text:
                return text, True
    except Exception:  # noqa: BLE001
        pass
    return "", False


def _fetch_lyrics(track_name: str, artist_name: str | None, duration: int | None) -> tuple[str, bool]:
    candidates: list[tuple[str, bool, int, int]] = []
    for order, getter in enumerate((_fetch_kuwo, _fetch_lrcapi, _fetch_lrclib)):
        text, synced = getter(track_name, artist_name, duration)
        if text:
            candidates.append((text, synced, _simplified_score(text), order))
    if not candidates:
        return "", False
    text, synced, _score, _order = max(candidates, key=lambda item: (item[2], int(item[1]), -item[3]))
    return _to_simplified(text), synced


def _simplified_score(text: str) -> int:
    simplified = sum(1 for ch in text if ch in SIMPLIFIED_MARKERS)
    traditional = sum(1 for ch in text if ch in TRADITIONAL_MARKERS)
    return simplified - traditional * 3


def _to_simplified(text: str) -> str:
    return _convert_text(text, "t2s").translate(LYRIC_SIMPLIFY_EXTRA)


def simplified_text(text: str) -> str:
    return _to_simplified(text or "")


def simplify_existing_lyrics(path: str) -> None:
    for file_path in lyric_paths(path) + plain_lyric_paths(path):
        if not os.path.exists(file_path):
            continue
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
            simplified = simplified_text(text)
            if simplified != text:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(simplified)
        except OSError:
            pass


def ensure_lyrics_async(path: str, duration_text: str | None = None, force: bool = False) -> None:
    if not path:
        return
    if has_lyrics(path):
        simplify_existing_lyrics(path)
        return
    key = os.path.normcase(os.path.abspath(path))
    with _download_lock:
        last_requested = _requested.get(key, 0)
        if key in _downloading or (not force and time.time() - last_requested < REQUEST_RETRY_SECONDS):
            return
        _requested[key] = time.time()
        _downloading.add(key)

    def worker() -> None:
        try:
            track_name, artist_name = _split_track_artist(path)
            text, synced = _fetch_lyrics(track_name, artist_name, _duration_seconds(duration_text))
            if text:
                text = _to_simplified(text)
                out_path = lyric_path(path) if synced else plain_lyric_path(path)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(text)
        except Exception:  # noqa: BLE001
            pass
        finally:
            with _download_lock:
                _downloading.discard(key)

    threading.Thread(target=worker, daemon=True).start()


_TIME_RE = re.compile(r"\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        matches = list(_TIME_RE.finditer(raw))
        if not matches:
            continue
        lyric = _TIME_RE.sub("", raw).strip()
        if not lyric:
            continue
        for match in matches:
            minute = int(match.group(1))
            second = int(match.group(2))
            fraction = match.group(3) or "0"
            ms = int((fraction + "00")[:3])
            lines.append(((minute * 60 + second) * 1000 + ms, lyric))
    return sorted(lines, key=lambda item: item[0])


def load_lrc(path: str) -> list[tuple[int, str]]:
    for file_path in lyric_paths(path):
        if not os.path.exists(file_path):
            continue
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return parse_lrc(simplified_text(f.read()))
        except OSError:
            return []
    return []


def line_at(lines: list[tuple[int, str]], position_ms: int) -> str:
    current = ""
    for start_ms, text in lines:
        if start_ms > position_ms:
            break
        current = text
    return current


def display_text(text: str) -> str:
    lang = config.settings.get("language", "zh-CN")
    if lang == "zh-TW":
        return _convert_text(text, "s2t")
    if lang == "zh-CN":
        return _convert_text(text, "t2s")
    return text


def _convert_text(text: str, mode: str) -> str:
    try:
        from opencc import OpenCC  # type: ignore

        config_name = "s2twp" if mode == "s2t" else "t2s"
        converter = _converter_cache.get(config_name)
        if converter is None:
            converter = OpenCC(config_name)
            _converter_cache[config_name] = converter
        return converter.convert(text)
    except Exception:  # noqa: BLE001
        pass
    if mode == "s2t":
        out = []
        for ch in text:
            out.append(SIM_EXTRA.get(ch, SIM2TW.get(ch, ch)))
        return "".join(out)
    return "".join(TW2SIM.get(ch, ch) for ch in text)
