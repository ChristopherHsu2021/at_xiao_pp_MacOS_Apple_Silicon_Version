# -*- mode: python ; coding: utf-8 -*-
"""自定义安装器外壳打包脚本（跨平台）。

- macOS：生成 AT小PP Installer.app（自定义 PyQt 向导），并把真实应用
  release/AT小PP.app 作为 payload 内嵌，安装时复制到 ~/Applications。
  用法：pyinstaller bootstrap.spec
- Windows：生成 release/AT小PP-version-1.0-setup.exe（沿用原 Inno 行为）。
  用法：pyinstaller bootstrap.spec --clean --noconfirm
"""

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

IS_MAC = sys.platform == "darwin"

block_cipher = None
installer_assets = "build_assets/installer_assets"
assets_source = installer_assets if os.path.isdir(installer_assets) else "assets"


def _without_package_tests(name):
    return ".test" not in name.lower() and ".selftest" not in name.lower()


hiddenimports = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "Crypto.Cipher.DES",
    "Crypto.Cipher._raw_des",
]

if IS_MAC:
    excludes = [
        "winreg", "comtypes", "msvcrt", "win32api", "winsound",
        "my_local_tts", "numpy", "soundfile", "torch", "torchaudio",
        "librosa", "scipy", "numba", "llvmlite", "onnxruntime",
        "transformers", "gradio", "fastapi", "uvicorn", "Crypto",
    ]
else:
    hiddenimports += (
        ["winreg"]
        + collect_submodules("comtypes", filter=_without_package_tests)
    )
    excludes = [
        "my_local_tts", "numpy", "soundfile", "torch", "torchaudio",
        "librosa", "scipy", "numba", "llvmlite", "onnxruntime",
        "transformers", "gradio", "fastapi", "uvicorn", "Crypto",
        "opencc",
    ]

datas = [
    (assets_source, "assets"),
]
if IS_MAC:
    # 内嵌真实应用包，安装时由自定义向导复制到 Applications。
    datas.append(("release/AT小PP.app", "payload"))
else:
    datas += [
        ("release/at_xiaopp_inner_setup.exe", "."),
        ("uninstall_at_xiaopp.bat", "."),
        ("uninstall_launcher.vbs", "."),
    ]

analysis_kwargs = dict(
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    cipher=block_cipher,
    noarchive=False,
)
if not IS_MAC:
    analysis_kwargs.update(win_no_prefer_redirects=False, win_private_assemblies=False)

a = Analysis(["installer_bootstrap.py"], **analysis_kwargs)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if IS_MAC:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="AT小PP Installer",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        icon="build_assets/app_icon.icns",
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    app = BUNDLE(
        exe,
        name="AT小PP Installer.app",
        icon="build_assets/app_icon.icns",
        bundle_identifier="com.christopherhsu.atxiaopp.installer",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.15",
            "CFBundleDisplayName": "AT小PP 安装器",
            "CFBundleName": "AT小PP 安装器",
            "CFBundleIdentifier": "com.christopherhsu.atxiaopp.installer",
            "NSPrincipalClass": "NSApplication",
            "CFBundlePackageType": "APPL",
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="AT小PP-version-1.0-setup",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        icon="build_assets/app_icon.ico",
        version="version_info.txt",
        uac_admin=True,
        disable_windowed_traceback=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
