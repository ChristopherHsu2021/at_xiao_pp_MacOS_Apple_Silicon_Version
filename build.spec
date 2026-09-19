# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包脚本（跨平台）。

- macOS：生成 AT小PP.app（one-folder / windowed），无控制台黑窗。
  用法：pyinstaller build.spec
- Windows：生成 dist/AT小PP/AT小PP.exe（沿用原行为）。
  用法：pyinstaller build.spec
"""

import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

IS_MAC = sys.platform == "darwin"

# 目标架构：默认跟随宿主机（最稳、零额外依赖）。
# 设置环境变量 ATPP_TARGET_ARCH=universal2 可产出通用二进制（Intel + Apple Silicon 通吃），
# 前提：宿主机 Python 为 universal2 构建，且所用依赖（PyQt6/Qt 等）含通用切片。
# 若依赖仅为单架构，则保持默认（跳过 universal2）以免构建失败。
ATPP_TARGET_ARCH = os.environ.get("ATPP_TARGET_ARCH") or None

block_cipher = None
release_assets = os.path.join("build_assets", "optimized_assets")
assets_source = release_assets if os.path.isdir(release_assets) else "assets"


def _without_package_tests(name):
    return ".test" not in name.lower() and ".selftest" not in name.lower()


hiddenimports = [
    "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.QtMultimedia",
    "Crypto.Cipher.DES", "Crypto.Cipher._raw_des",
]

if IS_MAC:
    # macOS：仅保留跨平台依赖；winreg/comtypes/msvcrt/winsound 仅 Windows 可用。
    excludes = [
        "winreg", "comtypes", "msvcrt", "win32api", "winsound",
        "my_local_tts", "numpy", "soundfile", "torch", "torchaudio",
        "librosa", "scipy", "numba", "llvmlite", "onnxruntime",
        "transformers", "gradio", "fastapi", "uvicorn",
    ]
    # PyObjC：AVFoundation 后端（macOS 原生音频）需要被 PyInstaller 收集进包。
    # objc 桥接 + Foundation + AVFoundation 三个包都是 Python 桥接层（纯 Python + C 扩展），
    # 它们运行期桥接到系统自带的 AVFoundation.framework（无需打包系统框架）。
    hiddenimports += collect_submodules("objc")
    hiddenimports += collect_submodules("Foundation")
    hiddenimports += collect_submodules("AVFoundation")
else:
    hiddenimports += (
        ["winreg"]
        + collect_submodules("comtypes", filter=_without_package_tests)
        + collect_submodules("opencc")
    )
    excludes = [
        "my_local_tts", "numpy", "soundfile", "torch", "torchaudio",
        "librosa", "scipy", "numba", "llvmlite", "onnxruntime",
        "transformers", "gradio", "fastapi", "uvicorn",
    ]

datas = [
    (assets_source, "assets"),
    ("data/character_config.json", "data"),
    ("data/settings.json", "data"),
]
# 预录制语音样例（仓库内实际有 100 个 wav，已纳入 git）：必须打进所有平台包，
# 否则 macOS 上 find_prepared() 找不到内置音频 → 回退系统 say，语音播报不走预录制。
datas += [
    ("data/voice/Generated Voice Media", "data/voice/Generated Voice Media"),
    ("data/voice/Upload Voice Media", "data/voice/Upload Voice Media"),
]
if not IS_MAC:
    datas += [
        ("uninstall_at_xiaopp.bat", "."),
        ("uninstall_launcher.vbs", "."),
    ]
datas += collect_data_files("opencc") + collect_data_files("pypinyin")

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

a = Analysis(["main.py"], **analysis_kwargs)

if IS_MAC:
    # macOS PyQt6-Qt6 6.7.3 wheel：Qt6 库为 Qt*.framework 目录（**不带 "6"，是 QtMultimedia.framework
    # 而非 Qt6Multimedia.framework**），标准 Versions/A 布局。PyInstaller 的 hook-PyQt6.QtMultimedia
    # 经 add_qt6_dependencies 收集框架，但在本环境最终 bundle 中 QtMultimedia.framework 时常未落地 ->
    # darwinmedia 后端插件 dlopen 失败 -> 'No QtMultimedia backends found' -> 播放无声。
    # 这里显式收集 multimedia 家族框架，dest 用真实 install_name 路径
    # @rpath/QtMultimedia.framework/Versions/A/QtMultimedia，COLLECT 阶段整目录落到
    # Contents/Frameworks/PyQt6/Qt6/lib/，darwinmedia 经 @rpath 必命中 -> 出声。
    # 扁平 libQt*Multimedia*.dylib 形态也兼容（部分环境）。package_macos.py 另有 post-build copytree 兜底。
    try:
        import PyQt6
        from pathlib import Path as _P
        _pkg = _P(PyQt6.__file__).resolve().parent  # .../site-packages/PyQt6
        _src = _pkg / "Qt6" / "lib"
        if not _src.is_dir():
            # 兜底：基于 QtCore 模块定位 Qt6/lib（同目录）
            import PyQt6.QtCore as _qc
            _src = _P(_qc.__file__).resolve().parent / "Qt6" / "lib"
        if _src.is_dir():
            _added = []
            for _ent in sorted(_src.iterdir()):
                _name = _ent.name
                if _ent.is_dir() and "Multimedia" in _name and _name.endswith(".framework"):
                    # 主 dylib：QtMultimedia.framework/Versions/A/QtMultimedia（无 "6"）
                    _main = _ent / "Versions" / "A" / _name[: -len(".framework")]
                    if not _main.is_file():
                        _main = _ent / _name[: -len(".framework")]  # 扁平 framework 兜底
                    if _main.is_file():
                        _rel = f"PyQt6/Qt6/lib/{_name}/Versions/A/{_main.name}"
                        a.binaries += [(_rel, str(_main), "BINARY")]
                        _added.append(_rel)
                elif _ent.is_file() and _ent.name.startswith("libQt") and "Multimedia" in _ent.name and _ent.name.endswith(".dylib"):
                    _rel = f"PyQt6/Qt6/lib/{_ent.name}"
                    a.binaries += [(_rel, str(_ent), "BINARY")]
                    _added.append(_rel)
            if _added:
                print(f"[build.spec] 已显式收集 Qt Multimedia 动态库 {len(_added)} 项（darwinmedia 后端依赖）：{', '.join(_added)}")
            else:
                print(f"[build.spec] 警告：{_src} 下未找到 Qt*Multimedia 框架/动态库（由 package_macos.py 兜底）")
        else:
            print("[build.spec] 警告：未定位到 PyQt6 的 Qt6/lib 目录，跳过 Qt 动态库收集（由 package_macos.py 兜底）")
    except Exception as e:
        print(f"[build.spec] 收集 Qt Multimedia 动态库失败（由 package_macos.py 兜底）：{e}")

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if IS_MAC:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="AT小PP",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        icon="build_assets/app_icon.icns",
        target_arch=ATPP_TARGET_ARCH,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="AT小PP",
    )
    app = BUNDLE(
        coll,
        name="AT小PP.app",
        icon="build_assets/app_icon.icns",
        bundle_identifier="com.christopherhsu.atxiaopp",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.15",
            "CFBundleDisplayName": "AT小PP",
            "CFBundleName": "AT小PP",
            "CFBundleIdentifier": "com.christopherhsu.atxiaopp",
            "NSPrincipalClass": "NSApplication",
            "CFBundlePackageType": "APPL",
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="AT小PP",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,          # 关键：不显示 cmd 黑窗
        icon="build_assets/app_icon.ico",
        version="version_info.txt",
        disable_windowed_traceback=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="AT小PP",
    )
