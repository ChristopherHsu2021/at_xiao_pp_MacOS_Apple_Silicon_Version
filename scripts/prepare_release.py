"""Clean user/test data before building a release package.

Keeps app configuration, character assets, and pre-recorded voice media.
Removes only user-created/test runtime content: music files, lyrics, covers,
temporary music cache, todo items, alarms, and transient TTS playback files.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MUSIC = DATA / "music"
VOICE = DATA / "voice"
TTS = DATA / "tts"

AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma", ".opus", ".ape"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
LYRIC_EXTS = {".lrc", ".txt"}


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _remove_files(folder: Path, suffixes: set[str]) -> int:
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        return 0
    removed = 0
    for path in folder.iterdir():
        if path.is_file() and path.suffix.lower() in suffixes:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def _clear_folder(folder: Path, keep: set[str] | None = None) -> int:
    keep = keep or set()
    folder.mkdir(parents=True, exist_ok=True)
    removed = 0
    for path in folder.iterdir():
        if path.name in keep:
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        else:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def main() -> int:
    removed = 0

    removed += _remove_files(MUSIC, AUDIO_EXTS)
    removed += _remove_files(MUSIC / "covers", IMAGE_EXTS)
    removed += _remove_files(MUSIC / "lyrics", LYRIC_EXTS)
    removed += _clear_folder(MUSIC / "temp")
    _write_json(MUSIC / "temp" / "index.json", {})

    _write_json(DATA / "todos.json", [])
    _write_json(DATA / "alarms.json", [])

    removed += _clear_folder(TTS / "temp")
    removed += _clear_folder(TTS / "volume_playback")

    # Keep generated/upload voice media. They are release assets, not test data.
    (VOICE / "Generated Voice Media").mkdir(parents=True, exist_ok=True)
    (VOICE / "Upload Voice Media").mkdir(parents=True, exist_ok=True)
    (VOICE / "Additional Voice Media").mkdir(parents=True, exist_ok=True)

    print(f"release data cleaned; removed {removed} runtime files/folders")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
