"""Album cover lookup and cache for user music."""

from __future__ import annotations

import json
import html
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from app.core import pathutil


LRCAPI_COVER = "https://api.lrc.cx/api/v1/cover/music"
LRCAPI_ALBUM_COVER = "https://api.lrc.cx/api/v1/cover/album"
NETEASE_SEARCH = "https://music.163.com/api/cloudsearch/pc"
QQ_SEARCH = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
ITUNES_SEARCH = "https://itunes.apple.com/search"
DEEZER_SEARCH = "https://api.deezer.com/search/track"
KUWO_MUSIC_INFO = "https://wapi.kuwo.cn/api/www/music/musicInfo"
MUSICBRAINZ_RECORDING = "https://musicbrainz.org/ws/2/recording/"
CAA_FRONT = "https://coverartarchive.org/release/{release_id}/front-500"
TIMEOUT = 12
HEADERS = {"User-Agent": "ATXiaoPP/1.0 (album cover lookup)"}
MUSIC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Referer": "https://music.163.com/",
}
QQ_HEADERS = {**MUSIC_HEADERS, "Referer": "https://y.qq.com/"}

_lock = threading.Lock()
_requested: set[str] = set()
_downloading: set[str] = set()
_last_musicbrainz_request = 0.0


def covers_dir() -> str:
    return os.path.dirname(pathutil.data_file("music", "covers", ".keep"))


def safe_filename(name: str) -> str:
    for c in '<>:"/\\|?*':
        name = name.replace(c, "_")
    return name.strip().strip(".") or "unknown"


def cover_key(title: str, artist: str | None = None) -> str:
    title = " ".join((title or "").split()).strip()
    artist = " ".join((artist or "").split()).strip()
    return safe_filename(f"{title} - {artist}" if artist else title)


def cover_path(title: str, artist: str | None = None) -> str:
    return os.path.join(covers_dir(), cover_key(title, artist) + ".jpg")


def existing_cover(title: str, artist: str | None = None) -> str | None:
    path = cover_path(title, artist)
    return path if os.path.exists(path) else None


def ensure_cover_async(title: str, artist: str | None = None, on_done=None) -> None:
    title = " ".join((title or "").split()).strip()
    artist = " ".join((artist or "").split()).strip() or None
    if not title or existing_cover(title, artist):
        return
    key = cover_key(title, artist)
    with _lock:
        if key in _requested or key in _downloading:
            return
        _requested.add(key)
        _downloading.add(key)

    def worker() -> None:
        saved = None
        try:
            url = _find_cover_url(title, artist)
            if url:
                saved = _download_cover(url, cover_path(title, artist))
        except Exception:  # noqa: BLE001
            saved = None
        finally:
            with _lock:
                _downloading.discard(key)
            if saved and on_done:
                try:
                    on_done(saved)
                except Exception:  # noqa: BLE001
                    pass

    threading.Thread(target=worker, daemon=True).start()


def _get_json(url: str, params: dict[str, object], timeout: int = TIMEOUT, headers: dict[str, str] | None = None) -> object | None:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    req = urllib.request.Request(f"{url}?{query}", headers=headers or HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _find_cover_url(title: str, artist: str | None) -> str | None:
    return (
        _find_lrcapi_cover(title, artist) or
        _find_lrcapi_album_cover(title, artist) or
        _find_netease_cover(title, artist) or
        _find_qq_cover(title, artist) or
        _find_itunes_cover(title, artist) or
        _find_deezer_cover(title, artist) or
        _find_kuwo_cover(title, artist) or
        _find_musicbrainz_cover(title, artist)
    )


def _norm_text(value: str | None) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (value or "").lower())


def _strip_markup(value: str | None) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value or ""))


def _title_matches(wanted: str, found: str | None) -> bool:
    wanted_key = _norm_text(wanted)
    found_key = _norm_text(_strip_markup(found))
    if not wanted_key or not found_key:
        return False
    return wanted_key in found_key or found_key in wanted_key


def _artist_matches(wanted: str | None, found: str | None) -> bool:
    wanted_key = _norm_text(wanted)
    if not wanted_key:
        return True
    found_key = _norm_text(_strip_markup(found))
    return bool(found_key and (wanted_key in found_key or found_key in wanted_key))


def _query_terms(title: str, artist: str | None) -> list[str]:
    terms = []
    compact_title = re.sub(r"\s*\([^)]*\)", "", title).strip()
    for item in (f"{title} {artist or ''}".strip(), f"{compact_title} {artist or ''}".strip(), title, compact_title):
        if item and item not in terms:
            terms.append(item)
    return terms


def _valid_image_url(url: str | None) -> str | None:
    if isinstance(url, str) and url.startswith("http"):
        return url
    return None


def _find_lrcapi_cover(title: str, artist: str | None) -> str | None:
    try:
        data = _get_json(LRCAPI_COVER, {"title": title, "artist": artist}, timeout=5)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(data, dict):
        img = data.get("img") or data.get("cover") or data.get("url")
        return _valid_image_url(img)
    return None


def _find_lrcapi_album_cover(title: str, artist: str | None) -> str | None:
    try:
        data = _get_json(LRCAPI_ALBUM_COVER, {"title": title, "artist": artist}, timeout=5)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(data, dict):
        img = data.get("img") or data.get("cover") or data.get("url")
        return _valid_image_url(img)
    return None


def _find_netease_cover(title: str, artist: str | None) -> str | None:
    for term in _query_terms(title, artist):
        try:
            data = _get_json(NETEASE_SEARCH, {"s": term, "type": 1, "offset": 0, "limit": 12}, timeout=6, headers=MUSIC_HEADERS)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        songs = data.get("result", {}).get("songs", []) if isinstance(data.get("result"), dict) else []
        for item in songs:
            if not isinstance(item, dict) or not _title_matches(title, item.get("name")):
                continue
            artists = item.get("ar") or item.get("artists") or []
            artist_text = " ".join(str(a.get("name") or "") for a in artists if isinstance(a, dict))
            if not _artist_matches(artist, artist_text):
                continue
            album = item.get("al") or item.get("album") or {}
            if not isinstance(album, dict):
                continue
            found = _valid_image_url(album.get("picUrl"))
            if found:
                return found.replace("http://", "https://", 1)
    return None


def _find_qq_cover(title: str, artist: str | None) -> str | None:
    for term in _query_terms(title, artist):
        try:
            data = _get_json(QQ_SEARCH, {"w": term, "format": "json", "p": 1, "n": 12}, timeout=6, headers=QQ_HEADERS)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        song = data.get("data", {}).get("song", {}) if isinstance(data.get("data"), dict) else {}
        items = song.get("list", []) if isinstance(song, dict) else []
        for item in items:
            if not isinstance(item, dict) or not _title_matches(title, item.get("songname")):
                continue
            singers = item.get("singer") or []
            artist_text = " ".join(str(s.get("name") or "") for s in singers if isinstance(s, dict))
            if not _artist_matches(artist, artist_text):
                continue
            album_mid = str(item.get("albummid") or "").strip()
            if album_mid:
                return f"https://y.gtimg.cn/music/photo_new/T002R800x800M000{album_mid}.jpg"
    return None


def _find_itunes_cover(title: str, artist: str | None) -> str | None:
    try:
        term = f"{title} {artist or ''}".strip()
        data = _get_json(ITUNES_SEARCH, {"term": term, "media": "music", "entity": "song", "limit": 12})
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    for item in data.get("results", []):
        if not isinstance(item, dict):
            continue
        track_ok = _title_matches(title, item.get("trackName"))
        artist_ok = _artist_matches(artist, item.get("artistName"))
        if not (track_ok and artist_ok):
            continue
        artwork = item.get("artworkUrl100") or item.get("artworkUrl60")
        if isinstance(artwork, str) and artwork.startswith("http"):
            return artwork.replace("100x100bb", "600x600bb").replace("60x60bb", "600x600bb")
    return None


def _find_deezer_cover(title: str, artist: str | None) -> str | None:
    try:
        if artist:
            query = f'track:"{title}" artist:"{artist}"'
        else:
            query = title
        data = _get_json(DEEZER_SEARCH, {"q": query, "limit": 8}, timeout=6)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    for item in data.get("data", []):
        if not isinstance(item, dict):
            continue
        track_ok = _title_matches(title, item.get("title"))
        artist_info = item.get("artist") if isinstance(item.get("artist"), dict) else {}
        artist_ok = _artist_matches(artist, artist_info.get("name"))
        if not (track_ok and artist_ok):
            continue
        album = item.get("album") if isinstance(item.get("album"), dict) else {}
        cover = album.get("cover_xl") or album.get("cover_big") or album.get("cover_medium")
        found = _valid_image_url(cover)
        if found:
            return found
    return None


def _find_kuwo_cover(title: str, artist: str | None) -> str | None:
    try:
        from app.core import music_api

        query = f"{title} {artist or ''}".strip()
        for item in music_api.search(query, size=8):
            track_ok = _norm_text(item.get("name")) == _norm_text(title)
            artist_ok = not artist or _norm_text(artist) in _norm_text(item.get("artist"))
            if not (track_ok and artist_ok):
                continue
            cover = _valid_image_url(item.get("cover"))
            if cover:
                return cover
            rid = item.get("rid") or item.get("id")
            info = _get_json(KUWO_MUSIC_INFO, {"mid": rid, "httpsStatus": 1}) if rid else None
            body = info.get("data") if isinstance(info, dict) else None
            if isinstance(body, dict):
                cover = _valid_image_url(body.get("pic") or body.get("albumPic") or body.get("artistPic"))
                if cover:
                    return cover
    except Exception:  # noqa: BLE001
        pass
    return None


def _find_musicbrainz_cover(title: str, artist: str | None) -> str | None:
    global _last_musicbrainz_request
    with _lock:
        wait = 1.05 - (time.monotonic() - _last_musicbrainz_request)
        if wait > 0:
            time.sleep(wait)
        _last_musicbrainz_request = time.monotonic()
    try:
        query = f'recording:"{title}"'
        if artist:
            query += f' AND artist:"{artist}"'
        data = _get_json(MUSICBRAINZ_RECORDING, {"query": query, "fmt": "json", "limit": 5, "inc": "releases"})
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    for rec in data.get("recordings", []):
        for rel in rec.get("releases", []) if isinstance(rec, dict) else []:
            release_id = rel.get("id") if isinstance(rel, dict) else None
            if release_id:
                return CAA_FRONT.format(release_id=release_id)
    return None


def _download_cover(url: str, out_path: str) -> str | None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        data = resp.read()
    image_magic = data.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF")) or data[:6] in (b"GIF87a", b"GIF89a")
    if len(data) < 512 or ("image" not in ctype and not image_magic):
        return None
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, out_path)
    return out_path
