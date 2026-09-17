"""Build the Windows release installer after cleaning runtime test data."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "venv" / "Scripts" / "python.exe"
ISCC = Path(os.environ.get("ISCC_EXE", r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"))
INNER_SETUP = ROOT / "release" / "at_xiaopp_inner_setup.exe"
OLD_INNER_SETUP = ROOT / "release" / "AT小PP-beta-version-1.0-inner-setup.exe"
DIST_INTERNAL = ROOT / "dist" / "AT小PP" / "_internal"


def _run(args: list[str | os.PathLike[str]]) -> None:
    printable = " ".join(str(arg) for arg in args)
    print(f"> {printable}")
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def _pyinstaller_args(python: Path, spec: Path, clean: bool, *extra: str | os.PathLike[str]) -> list[str | os.PathLike[str]]:
    args: list[str | os.PathLike[str]] = [python, "-m", "PyInstaller", spec, "--noconfirm"]
    if clean:
        args.append("--clean")
    args.extend(extra)
    return args


def _prune_dist() -> None:
    translations = DIST_INTERNAL / "PyQt6" / "Qt6" / "translations"
    if translations.exists():
        shutil.rmtree(translations)
        print(f"removed unused Qt translations: {translations}")

    qt_pdf = DIST_INTERNAL / "PyQt6" / "Qt6" / "bin" / "Qt6Pdf.dll"
    if qt_pdf.exists():
        qt_pdf.unlink()
        print(f"removed unused QtPdf runtime: {qt_pdf}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build AT小PP Windows installer.")
    parser.add_argument("--clean", action="store_true", help="force a full PyInstaller rebuild")
    parser.add_argument("--skip-assets", action="store_true", help="reuse existing optimized release assets")
    args = parser.parse_args()

    python = PYTHON if PYTHON.exists() else Path(sys.executable)
    if not ISCC.exists():
        raise FileNotFoundError(f"Inno Setup compiler not found: {ISCC}")

    _run([python, ROOT / "scripts" / "prepare_release.py"])
    if not args.skip_assets:
        _run([python, ROOT / "scripts" / "build_release_assets.py"])
    _run(_pyinstaller_args(python, ROOT / "build.spec", args.clean))
    _prune_dist()
    _run([ISCC, ROOT / "installer" / "AT小PP.iss"])
    _run(_pyinstaller_args(python, ROOT / "bootstrap.spec", args.clean, "--distpath", ROOT / "release"))

    INNER_SETUP.unlink(missing_ok=True)
    OLD_INNER_SETUP.unlink(missing_ok=True)
    print("Windows release package is ready: release/AT小PP-beta-version-1.0-setup.exe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
