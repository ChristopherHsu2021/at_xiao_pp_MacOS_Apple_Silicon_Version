"""Prepare smaller asset folders for release builds.

Source assets stay untouched. The release build uses optimized copies so the
installed app keeps the same UI while avoiding packaging huge source PNGs.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ASSETS = ROOT / "assets"
BUILD_ASSETS = ROOT / "build_assets"
RUNTIME_ASSETS = BUILD_ASSETS / "optimized_assets"
INSTALLER_ASSETS = BUILD_ASSETS / "installer_assets"

RUNTIME_MAX_SIDE = 1024
INSTALLER_MAX_SIDE = 640
INSTALLER_REQUIRED = {
    "app_icon.png",
    "bubu_cutout.png",
    "character_config.json",
    "uninstall_pleading.png",
    "uninstall_crying.png",
    "uninstall_goodbye.png",
}


def _reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _copy_plain(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _save_optimized_image(src: Path, dst: Path, max_side: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as image:
        image.load()
        if max(image.size) > max_side:
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if image.mode not in {"RGB", "RGBA", "L"}:
            image = image.convert("RGBA")
        image.save(dst, optimize=True, compress_level=9)


def _copy_tree_optimized(src_root: Path, dst_root: Path, max_side: int) -> tuple[int, int]:
    before = 0
    after = 0
    for src in src_root.rglob("*"):
        if not src.is_file():
            continue
        dst = dst_root / src.relative_to(src_root)
        before += src.stat().st_size
        if src.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            _save_optimized_image(src, dst, max_side)
        else:
            _copy_plain(src, dst)
        after += dst.stat().st_size
    return before, after


def _copy_installer_assets() -> tuple[int, int]:
    before = 0
    after = 0
    for name in INSTALLER_REQUIRED:
        src = SOURCE_ASSETS / name
        if not src.exists():
            continue
        dst = INSTALLER_ASSETS / name
        before += src.stat().st_size
        if src.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            _save_optimized_image(src, dst, INSTALLER_MAX_SIDE)
        else:
            _copy_plain(src, dst)
        after += dst.stat().st_size
    return before, after


def _fmt(size: int) -> str:
    return f"{size / 1024 / 1024:.2f} MB"


def main() -> int:
    if not SOURCE_ASSETS.exists():
        raise FileNotFoundError(f"assets folder not found: {SOURCE_ASSETS}")

    _reset_dir(RUNTIME_ASSETS)
    _reset_dir(INSTALLER_ASSETS)

    runtime_before, runtime_after = _copy_tree_optimized(
        SOURCE_ASSETS,
        RUNTIME_ASSETS,
        RUNTIME_MAX_SIDE,
    )
    installer_before, installer_after = _copy_installer_assets()

    print(
        "release assets prepared; "
        f"runtime {_fmt(runtime_before)} -> {_fmt(runtime_after)}, "
        f"installer {_fmt(installer_before)} -> {_fmt(installer_after)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
