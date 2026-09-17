"""Network music search/download API with full-track filtering."""

from __future__ import annotations

import json
import html
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode

from Crypto.Cipher import DES

from app.core import pathutil


KUWO_SEARCH = "https://www.kuwo.cn/search/searchMusicBykeyWord"
KUWO_JSONP_SEARCH = "https://search.kuwo.cn/r.s"
KUWO_PLAY = "https://mobi.kuwo.cn/mobi.s"
KUWO_LRC = "http://m.kuwo.cn/newh5/singles/songinfoandlrc"
ISOUDY_PARSE = "https://api.isoudy.com/api/ajax.php"
TIMEOUT = 12
SEARCH_TIMEOUT = 5
SEARCH_CACHE_SECONDS = 300
TEMP_DAYS = 3
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://www.kuwo.cn/",
}
ISOUDY_HEADERS = {
    **HEADERS,
    "Referer": "https://www.shiyinren.net/tool/song/",
    "Origin": "https://www.shiyinren.net",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}
_search_cache: dict[tuple[str, int, int], tuple[float, list[dict]]] = {}
_search_lock = threading.Lock()


def safe_filename(name: str) -> str:
    for c in '<>:"/\\|?*':
        name = name.replace(c, "_")
    return name.strip().strip(".") or "unknown"


def cache_dir() -> str:
    return os.path.dirname(pathutil.data_file("music", "temp", ".keep"))


def meta_path() -> str:
    return pathutil.data_file("music", "temp", "index.json")


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _read_meta() -> dict:
    try:
        with open(meta_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return {_path_key(path): info for path, info in data.items() if isinstance(path, str)}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_meta(data: dict) -> None:
    with open(meta_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_cache_path(path: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(cache_dir())]) == os.path.abspath(cache_dir())
    except ValueError:
        return False


def list_cached_files() -> list[str]:
    cleanup_cache()
    folder = cache_dir()
    out: list[str] = []
    for name in os.listdir(folder):
        p = os.path.join(folder, name)
        if os.path.isfile(p) and os.path.splitext(name)[1].lower() in {".mp3", ".flac", ".aac", ".m4a", ".ogg"}:
            out.append(p)
    return sorted(out, key=lambda p: os.path.getmtime(p))


def cleanup_cache(days: int = TEMP_DAYS) -> None:
    folder = cache_dir()
    meta = _read_meta()
    changed = False
    cutoff = time.time() - days * 86400
    for name in list(os.listdir(folder)):
        p = os.path.join(folder, name)
        if p == meta_path() or not os.path.isfile(p):
            continue
        try:
            if os.path.getmtime(p) < cutoff:
                info = meta.get(_path_key(p)) or {}
                os.remove(p)
                _delete_track_sidecars(p, info)
                meta.pop(_path_key(p), None)
                changed = True
        except OSError:
            pass
    for p in list(meta):
        if not os.path.exists(p):
            meta.pop(p, None)
            changed = True
    if changed:
        _write_meta(meta)


def _split_track_artist_from_name(path: str) -> tuple[str, str]:
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


def _delete_track_sidecars(path: str, info: dict | None = None) -> None:
    try:
        from app.core import covers, lyrics
    except Exception:  # noqa: BLE001
        return

    info = info or {}
    title, artist = _split_track_artist_from_name(path)
    identities = {(title, artist or None)}
    meta_title = " ".join(str(info.get("name") or "").split()).strip()
    meta_artist = " ".join(str(info.get("artist") or "").split()).strip()
    if meta_title:
        identities.add((meta_title, meta_artist or None))

    folder = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    sidecars = {
        os.path.join(folder, stem + ".lrc"),
        os.path.join(folder, stem + ".txt"),
        lyrics.lyric_path(path),
        lyrics.plain_lyric_path(path),
    }
    for item_title, item_artist in identities:
        lyric_key = lyrics.safe_filename(f"{item_title} - {item_artist}" if item_artist else item_title)
        sidecars.add(os.path.join(lyrics.lyrics_dir(), lyric_key + ".lrc"))
        sidecars.add(os.path.join(lyrics.lyrics_dir(), lyric_key + ".txt"))
        sidecars.add(covers.cover_path(item_title, item_artist))
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        sidecars.add(os.path.join(folder, stem + ext))
    for sidecar in sidecars:
        try:
            if sidecar and os.path.exists(sidecar):
                os.remove(sidecar)
        except OSError:
            pass


def cache_info(path: str) -> dict | None:
    return _read_meta().get(_path_key(path))


def remember_cache(path: str, item: dict, quality: dict | None = None) -> None:
    meta = _read_meta()
    meta[_path_key(path)] = {
        "id": item.get("id") or item.get("rid", ""),
        "rid": item.get("id") or item.get("rid", ""),
        "name": item.get("name", ""),
        "artist": item.get("artist", ""),
        "album": item.get("album", ""),
        "duration": item.get("duration", 0),
        "source": item.get("source", "kuwo"),
        "api": item.get("api", "kuwo"),
        "cover": item.get("cover", ""),
        "minfo": item.get("minfo", ""),
        "full_qualities": item.get("full_qualities", []),
        "quality": quality or {},
        "created": int(time.time()),
    }
    _write_meta(meta)


def remember_track(path: str, item: dict, quality: dict | None = None) -> None:
    remember_cache(path, item, quality)


def forget_cache(path: str) -> None:
    meta = _read_meta()
    meta.pop(_path_key(path), None)
    _write_meta(meta)


def _request(url: str, params: dict[str, object] | None = None, timeout: int = TIMEOUT):
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{query}"
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, timeout=timeout)


def _request_json(url: str, params: dict[str, object] | None = None, timeout: int = TIMEOUT) -> object | None:
    with _request(url, params, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _post_json(url: str, data: dict[str, object], timeout: int = TIMEOUT) -> object | None:
    body = urllib.parse.urlencode({k: v for k, v in data.items() if v not in (None, "")}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=ISOUDY_HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _request_text(url: str, params: dict[str, object] | None = None, timeout: int = TIMEOUT) -> str:
    with _request(url, params, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _duration_value(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _song_from_raw(raw: dict) -> dict | None:
    def clean(value) -> str:
        return html.unescape(str(value or "")).replace("\xa0", " ").strip()

    musicrid = raw.get("MUSICRID") or raw.get("musicrid") or ""
    match = re.search(r"MUSIC_(\d+)", musicrid)
    rid = match.group(1) if match else str(raw.get("id") or raw.get("rid") or "").strip()
    name = clean(raw.get("NAME") or raw.get("SONGNAME") or raw.get("name"))
    if not rid or not name:
        return None
    return {
        "id": rid,
        "rid": rid,
        "name": name,
        "artist": clean(raw.get("ARTIST") or raw.get("artist")),
        "album": clean(raw.get("ALBUM") or raw.get("album")),
        "albumid": clean(raw.get("ALBUMID") or raw.get("albumid")),
        "artistid": clean(raw.get("ARTISTID") or raw.get("artistid")),
        "duration": _duration_value(raw.get("DURATION") or raw.get("duration")),
        "minfo": raw.get("MINFO") or raw.get("minfo") or "",
        "source": "kuwo",
        "api": "kuwo",
        "cover": clean(raw.get("PICPATH") or raw.get("pic") or raw.get("cover")),
    }


def _search_jsonp(keyword: str, page: int, size: int) -> list[dict]:
    text = _request_text(KUWO_JSONP_SEARCH, {
        "all": keyword,
        "ft": "music",
        "client": "kt",
        "cluster": 0,
        "pn": page,
        "rn": size,
        "rformat": "json",
        "callback": "searchMusicResult",
        "encoding": "utf8",
        "vipver": "MUSIC_8.0.3.1",
    }, timeout=SEARCH_TIMEOUT)
    match = re.search(r"(?:var\s+jsondata\s*=|searchMusicResult\()\s*(\{.*?\})\s*(?:;|\))", text, re.S)
    if not match:
        return []
    data = json.loads(match.group(1))
    return [song for raw in data.get("abslist") or [] if isinstance(raw, dict) for song in [_song_from_raw(raw)] if song]


def _search_official(keyword: str, page: int, size: int) -> list[dict]:
    data = _request_json(KUWO_SEARCH, {
        "vipver": 1, "client": "kt", "ft": "music", "cluster": 0,
        "strategy": 2012, "encoding": "utf8", "rformat": "json",
        "mobi": 1, "issubtitle": 1, "show_copyright_off": 1,
        "pn": page, "rn": size, "all": keyword,
    }, timeout=SEARCH_TIMEOUT)
    return [song for raw in (data or {}).get("abslist") or [] if isinstance(raw, dict) for song in [_song_from_raw(raw)] if song]


def search(keyword: str, page: int = 0, size: int = 20) -> list[dict]:
    keyword = " ".join((keyword or "").split())
    if not keyword:
        return []
    cache_key = (keyword.lower(), int(page), int(size))
    now = time.time()
    with _search_lock:
        cached = _search_cache.get(cache_key)
        if cached and now - cached[0] <= SEARCH_CACHE_SECONDS:
            return [dict(item) for item in cached[1]]

    candidates: list[dict] = []
    for getter in (_search_jsonp, _search_official):
        try:
            candidates.extend(getter(keyword, page, max(size, 30)))
        except Exception:  # noqa: BLE001
            continue
        if len(candidates) >= size:
            break
    seen: set[str] = set()
    items: list[dict] = []
    for item in candidates:
        rid = item.get("rid") or item.get("id")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        items.append(item)
        if len(items) >= size:
            break
    with _search_lock:
        _search_cache[cache_key] = (now, [dict(item) for item in items])
    return items


def parse_qualities(minfo: str) -> list[tuple[int, str]]:
    qualities: list[tuple[int, str]] = []
    for bitrate, fmt in re.findall(r"bitrate:(\d+),format:(\w+)", minfo or ""):
        quality = (int(bitrate), fmt.lower())
        if quality not in qualities:
            qualities.append(quality)
    return sorted(qualities, reverse=True)


def quality_label(quality: tuple[int, str]) -> str:
    bitrate, fmt = quality
    return f"{bitrate}k{fmt}"


def quality_options(item: dict) -> list[str]:
    verified = item.get("full_qualities") or []
    if verified:
        return list(verified)
    options = [quality_label(q) for q in parse_qualities(item.get("minfo", ""))]
    return options or ["128kmp3"]


def pick_br(minfo: str, prefer=("128kmp3", "192kmp3", "320kmp3", "300kogg", "2000kflac")) -> str:
    support = {(b, f) for b, f in parse_qualities(minfo)}
    for want in prefer:
        match = re.match(r"(\d+)k(\w+)", want)
        if not match:
            continue
        want_b, want_f = int(match.group(1)), match.group(2).lower()
        for b, f in sorted(support):
            if f == want_f and b <= want_b:
                return f"{b}k{f}"
    if support:
        b, f = min(support, key=lambda item: item[0])
        return f"{b}k{f}"
    return "128kmp3"


def _format_from_br(br: str) -> str:
    match = re.match(r"\d+k(\w+)", br or "")
    return (match.group(1) if match else "mp3").lower()


def _quality_from_url(url: str, br: str) -> tuple[int, str]:
    bitrate = 0
    fmt = ""
    bit_match = re.search(r"bitrate[$=](\d+)", url or "")
    fmt_match = re.search(r"format[$=]([a-zA-Z0-9]+)", url or "")
    if bit_match:
        bitrate = int(bit_match.group(1))
    if fmt_match:
        fmt = fmt_match.group(1).lower()
    br_match = re.match(r"(\d+)k(\w+)", br or "")
    if br_match:
        bitrate = bitrate or int(br_match.group(1))
        fmt = fmt or br_match.group(2).lower()
    return bitrate or 128, fmt or "mp3"


def _isoudy_token(rid: str, br: str, fmt: str) -> str:
    query = (
        "user=0&android_id=0&prod=kwplayer_ar_8.5.5.0&corp=kuwo&newver=3"
        "&vipver=8.5.5.0&source=kwplayer_ar_8.5.5.0_apk_keluze.apk&p2p=1"
        f"&notrace=0&type=convert_url2&br={br}&format={fmt}&sig=0&rid={rid}"
        "&priority=bitrate&loginUid=0&network=WIFI&loginSid=0&mode=download"
    )
    raw = query.encode("utf-8")
    pad = (8 - len(raw) % 8) % 8 or 8
    cipher = DES.new(b"ylzsxkwm", DES.MODE_ECB)
    return b64encode(cipher.encrypt(raw + b"\0" * pad)).decode("ascii")


# Kuwo (and similar sources) answer a play-URL request with code 200 yet no
# usable URL when a track is DRM/VIP/copyright restricted -- only a "this song
# is mobile-app-only" notice (e.g. "当前音乐仅在酷我音乐最新手机版可播放").
# This must NOT be treated as a generic network/empty failure; it is a distinct
# 'restricted' outcome that the UI surfaces verbatim to the user.
_RESTRICTED_HINTS = ("手机版", "版权", "会员专享", "当前音乐仅", "仅可在", "客户端播放")


class RemoteResolveError(RuntimeError):
    """Raised when a remote track URL cannot be resolved.

    kind is one of:
      - 'network'    -> every resolver was unreachable / timed out / unparseable
      - 'empty'      -> resolvers answered but no playable (full) URL was returned
      - 'restricted' -> a resolver explicitly reported the track is DRM/VIP/
                        copyright-restricted (e.g. Kuwo: '当前音乐仅在酷我音乐
                        最新手机版可播放'), so no desktop playback URL exists
    """

    def __init__(self, kind: str, message: str = ""):
        self.kind = kind
        super().__init__(message or kind)


def _response_restricted(data) -> bool:
    if not isinstance(data, dict):
        return False
    blob = json.dumps(data, ensure_ascii=False)
    return any(hint in blob for hint in _RESTRICTED_HINTS)


def _isoudy_url(item: dict, br: str) -> dict | None:
    rid = str(item.get("rid") or item.get("id") or "").strip()
    if not rid:
        return None
    fmt = _format_from_br(br)
    attempts = [(br or "192kmp3", fmt or "mp3")]
    if fmt == "mp3":
        attempts.append(("192kmp3", "flac|mp3|aac"))
    for want_br, want_fmt in attempts:
        token = _isoudy_token(rid, want_br, want_fmt)
        data = _post_json(ISOUDY_PARSE, {
            "mid": rid,
            "token": token,
            "name": item.get("name", ""),
            "singer": item.get("artist", ""),
            "album": item.get("album", ""),
        })
        if not isinstance(data, dict):
            continue
        url = (((data.get("data") or {}) if isinstance(data.get("data"), dict) else {}).get("url") or "").strip()
        if not url:
            if _response_restricted(data):
                raise RemoteResolveError("restricted")
            continue
        bitrate, actual_fmt = _quality_from_url(url, want_br)
        return {
            "url": url,
            "bitrate": bitrate,
            "format": actual_fmt,
            "duration": _duration_value(item.get("duration")),
            "trial": False,
            "br": f"{bitrate}k{actual_fmt}",
            "resolver": "shiyinren-isoudy",
        }
    return None


def _play_url(rid: str, br: str) -> dict | None:
    data = _request_json(KUWO_PLAY, {
        "f": "web", "source": "jiakong", "type": "convert_url_with_sign",
        "rid": rid, "br": br,
    })
    if isinstance(data, dict) and data.get("code") == 200 and data.get("data", {}).get("url"):
        body = data["data"]
        return {
            "url": body["url"],
            "bitrate": _duration_value(body.get("bitrate")),
            "format": (body.get("format") or "mp3").lower(),
            "duration": _duration_value(body.get("duration")),
            "trial": False,
            "br": br,
        }
    if isinstance(data, dict) and _response_restricted(data):
        raise RemoteResolveError("restricted")
    return None


def is_full_track(item: dict, info: dict | None) -> bool:
    if not info or not info.get("url"):
        return False
    if _duration_value(info.get("bitrate")) <= 1:
        return False
    expected = _duration_value(item.get("duration"))
    actual = _duration_value(info.get("duration"))
    if expected <= 0 or actual <= 0:
        return True
    return actual >= max(expected - 8, int(expected * 0.90))


def _kuwo_anti_url(rid: str, br: str) -> dict | None:
    """Resolve play URL via antiserver.kuwo.cn (anti-leech CDN frontend)."""
    data = _request_json("https://antiserver.kuwo.cn/anti.s", {
        "type": "convert_url",
        "rid": rid,
        "format": _format_from_br(br) or "mp3",
        "br": br,
        "from": "web",
    })
    if not isinstance(data, dict) or data.get("code") != 200:
        if isinstance(data, dict) and _response_restricted(data):
            raise RemoteResolveError("restricted")
        return None
    url = (data.get("url") or "").strip()
    if not url and isinstance(data.get("data"), dict):
        url = (data["data"].get("url") or "").strip()
    if not url:
        if _response_restricted(data):
            raise RemoteResolveError("restricted")
        return None
    bitrate, fmt = _quality_from_url(url, br)
    return {
        "url": url,
        "bitrate": bitrate,
        "format": fmt,
        "duration": 0,
        "trial": False,
        "br": br,
        "resolver": "kuwo-anti",
    }


def looks_like_trial_clip(out_path: str, item: dict, info: dict) -> bool:
    """Detect Kuwo's spoken 'use the mobile app' trial clip."""
    expected_dur = _duration_value(item.get("duration"))
    if expected_dur <= 90:
        return False
    bitrate = _duration_value(info.get("bitrate")) or _quality_from_url(info.get("url", ""), info.get("br", ""))[0]
    if bitrate <= 0:
        return False
    try:
        size = os.path.getsize(out_path)
    except OSError:
        return False
    implied_seconds = size / (bitrate * 125.0)
    return implied_seconds < 0.6 * expected_dur


def full_url(item: dict, br: str) -> dict | None:
    try:
        info = _isoudy_url(item, br)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError):
        info = None
    if is_full_track(item, info):
        return info
    try:
        info = _play_url(item.get("rid") or item.get("id", ""), br)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        info = None
    if is_full_track(item, info):
        return info
    return None


def verified_full_qualities(item: dict) -> list[str]:
    verified: list[str] = []
    for br in [quality_label(q) for q in parse_qualities(item.get("minfo", ""))] or ["128kmp3"]:
        try:
            if full_url(item, br):
                verified.append(br)
        except Exception:  # noqa: BLE001
            pass
    return verified


def search_full(keyword: str, page: int = 0, size: int = 20, candidates: int | None = None) -> list[dict]:
    results = search(keyword, page=page, size=candidates or max(size, 30))
    out: list[dict] = []
    for item in results:
        options = quality_options(item)
        out.append({**item, "full_qualities": options})
        if len(out) >= size:
            break
    return out


DEFAULT_PREFER = ("128kmp3", "192kmp3", "320kmp3", "300kogg", "48kaac")
_NETWORK_EXC = (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError)


def resolve_playable(item: dict, br: str | None = None) -> dict:
    """Resolve a FULL-length playable URL, distinguishing network failure
    from a genuinely missing resource.

    Always returns a dict containing an 'error' key:
      - None     -> success; url info lives in url/bitrate/format/duration/br/resolver
      - 'network'-> every resolver raised a network/timeout/parse error
      - 'empty'  -> resolvers answered but no usable (full) URL was available
      - 'restricted' -> track explicitly reported as DRM/VIP/copyright restricted
    """
    rid = str(item.get("rid") or item.get("id") or "").strip()
    if not rid:
        return {"error": "empty"}
    network_failed = False
    restricted_seen = False

    def try_one(br_str: str) -> dict | None:
        nonlocal network_failed, restricted_seen
        try:
            info = _isoudy_url(item, br_str)
        except _NETWORK_EXC:
            info = None
            network_failed = True
        except RemoteResolveError as exc:
            if exc.kind == "restricted":
                restricted_seen = True
            info = None
        if info and is_full_track(item, info):
            return info
        try:
            info = _play_url(rid, br_str)
        except _NETWORK_EXC:
            info = None
            network_failed = True
        except RemoteResolveError as exc:
            if exc.kind == "restricted":
                restricted_seen = True
            info = None
        if info and is_full_track(item, info):
            return info
        try:
            info = _kuwo_anti_url(rid, br_str)
        except _NETWORK_EXC:
            info = None
            network_failed = True
        except RemoteResolveError:
            info = None
        if info and is_full_track(item, info):
            return info
        return None

    if br:
        info = try_one(br)
        if info:
            return {**info, "error": None}
        return {"error": "restricted" if restricted_seen else ("network" if network_failed else "empty")}

    tried: set[str] = set()
    for want in list(DEFAULT_PREFER) + ["2000kflac"]:
        br_str = pick_br(item.get("minfo", ""), prefer=(want,))
        if br_str in tried:
            continue
        tried.add(br_str)
        info = try_one(br_str)
        if info:
            return {**info, "error": None}
    return {"error": "restricted" if restricted_seen else ("network" if network_failed else "empty")}


def best_url(item: dict, prefer=("128kmp3", "192kmp3", "320kmp3", "300kogg", "48kaac"), full_only: bool = True) -> dict | None:
    tried: set[str] = set()
    fallback = None
    for want in list(prefer) + ["2000kflac"]:
        br = pick_br(item.get("minfo", ""), prefer=(want,))
        if br in tried:
            continue
        tried.add(br)
        try:
            info = _isoudy_url(item, br)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError):
            info = None
        if info and is_full_track(item, info):
            return info
        try:
            info = _play_url(item.get("rid") or item.get("id", ""), br)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            info = None
        if not info:
            continue
        if is_full_track(item, info):
            return info
        if not full_only:
            fallback = fallback or {**info, "trial": True}
    return None if full_only else fallback


def get_lrc(song_id: str, source: str | None = None, api: str | None = None) -> str:
    del source, api
    try:
        data = _request_json(KUWO_LRC, {"musicId": song_id})
        lrclist = ((data or {}).get("data") or {}).get("lrclist") or []
    except Exception:  # noqa: BLE001
        return ""
    lines = []
    for seg in lrclist:
        try:
            t = float(seg.get("time") or 0)
        except (TypeError, ValueError):
            t = 0.0
        mm, ss = int(t // 60), int(t % 60)
        frac = int(round((t - int(t)) * 100))
        lines.append(f"[{mm:02d}:{ss:02d}.{frac:02d}]{seg.get('lineLyric', '')}")
    return "\n".join(lines)


def download(url: str, out_path: str, progress_cb=None) -> str:
    with _request(url, timeout=45) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(out_path, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb and total:
                    progress_cb(done / total)
    return out_path


def target_path(item: dict, folder: str, ext: str, include_rid: bool = False) -> str:
    title = f"{item.get('name') or '未知歌曲'} - {item.get('artist') or '未知歌手'}"
    if include_rid and (item.get("id") or item.get("rid")):
        title = f"{title} [{item.get('id') or item.get('rid')}]"
    base = os.path.join(folder, safe_filename(title))
    candidate = f"{base}.{ext}"
    n = 1
    while os.path.exists(candidate):
        candidate = f"{base} ({n}).{ext}"
        n += 1
    return candidate
