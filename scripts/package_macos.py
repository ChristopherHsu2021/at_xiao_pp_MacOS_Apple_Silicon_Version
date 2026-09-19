"""构建 AT小PP 的 macOS 发行包（.dmg 直接含真身 AT小PP.app，无安装/卸载向导）。

流程：
  1. 由 PNG 生成 build_assets/app_icon.icns（仅 macOS 可运行）。
  2. pyinstaller build.spec            -> dist/AT小PP.app（真身应用，无控制台黑窗）
  3. 裁剪无用 Qt 翻译 / QtPdf 以减小体积
  4. 对 .app 做免费自签名（ad-hoc codesign），消除「App 已损坏」类拦截
  5. hdiutil 打包为 release/AT小PP-macos.dmg（含 AT小PP.app 与 Applications 快捷方式）

使用方式（类比 Windows「安装到本地」）：
  - 挂载 .dmg 后，把里面的 AT小PP.app 拖进 /Applications（或 ~/Applications）即可。
  - 卸载 = 把 AT小PP.app 拖进废纸篓。无需任何向导。

仅在 macOS 上运行；依赖 requirements-macos.txt 与 PyInstaller。
全程零成本：无需 Apple 付费开发者账号（自签名为本地 ad-hoc，免费）。

兼容性说明（兼容性优先方案）：
  - 通过环境变量 ATPP_TARGET_ARCH=x86_64 产出 x86_64 包：
      Intel Mac 原生运行；Apple Silicon Mac 经 Rosetta 2 运行。
      单个 .dmg 即可覆盖几乎所有 Mac，系统兼容性最强（这也是默认 CI 方案）。
  - 加 --universal 可尝试产出 universal2（Intel+Apple Silicon 单包通吃），
    需宿主机 Python 为 universal2 且依赖含通用切片；否则自动回退宿主机架构。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import struct
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
RELEASE = ROOT / "release"
BUILD = ROOT / "build"


def _run(args: list[str | os.PathLike[str]], cwd: Path = ROOT) -> None:
    printable = " ".join(str(a) for a in args)
    print(f"> {printable}")
    subprocess.run([str(a) for a in args], cwd=str(cwd), check=True)


def _python_is_universal() -> bool:
    """宿主机 Python 是否为 universal2 构建（可产出通用二进制）。"""
    try:
        out = subprocess.run(
            ["file", sys.executable], capture_output=True, text=True
        ).stdout.lower()
        return "universal" in out
    except Exception:
        return False


def _codesign(path: Path) -> None:
    """免费自签名（ad-hoc）：`codesign --force --deep --sign -`。

    作用：满足 Gatekeeper 对「已签名」的要求，消除「App 已损坏 / 无法验证」类拦截。
    不花钱、无需 Apple 开发者账号。局限：下载自网络的未公证包首次启动仍可能弹「无法确认
    开发者」——此时右键→打开 或 `xattr -dr com.apple.quarantine` 一次即可（本地拷贝无此问题）。
    """
    print(f"codesign (ad-hoc): {path}")
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ensure_icns() -> None:
    icns = ROOT / "build_assets" / "app_icon.icns"
    if icns.exists():
        print(f"icns 已存在，跳过生成：{icns}")
        return
    png = ROOT / "assets" / "app_icon.png"
    if not png.exists():
        print("缺少 assets/app_icon.png，无法生成 icns；请手动放置 build_assets/app_icon.icns")
        return
    # build_assets/ 被 .gitignore 排除（CI 上不存在），必须先建目录
    icns.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="atpp_iconset_")
    iconset = Path(tmp) / "app.iconset"
    iconset.mkdir()
    # Apple 标准 iconset 恰好 10 个成员（多出 icon_64x64/icon_1024x1024 等非标准
    # 文件名会让 iconutil 直接报 "Failed to generate ICNS"，已踩坑验证）。
    # 命名 -> (像素尺寸, 对应 ICNS OSType)
    #   ic07=128 ic08=256 ic09=512 ic10=512@2x ic11=16@2x ic12=32@2x ic13=128@2x ic14=256@2x
    entries = [
        ("icon_16x16.png", 16, None),
        ("icon_16x16@2x.png", 32, "ic11"),
        ("icon_32x32.png", 32, None),
        ("icon_32x32@2x.png", 64, "ic12"),
        ("icon_128x128.png", 128, "ic07"),
        ("icon_128x128@2x.png", 256, "ic13"),
        ("icon_256x256.png", 256, "ic08"),
        ("icon_256x256@2x.png", 512, "ic14"),
        ("icon_512x512.png", 512, "ic09"),
        ("icon_512x512@2x.png", 1024, "ic10"),
    ]
    for name, px, _ostype in entries:
        out = iconset / name
        _run(["sips", "-z", str(px), str(px), str(png), "--out", str(out)])

    # 优先用 iconutil 官方转换；它在部分 runner/环境下会无故报
    # "Failed to generate ICNS"（无 verbose 可查，社区多起同类案例），
    # 因此失败时回退为手工组装 ICNS 容器——现代 .icns 支持直接内嵌 PNG，
    # 此方法结果 100% 确定性，不依赖 iconutil。
    try:
        _run(["iconutil", "--convert", "icns", "--output", str(icns), str(iconset)])
    except subprocess.CalledProcessError:
        print("iconutil 失败，回退为手工组装 ICNS（PNG 内嵌容器）...")
        _write_icns_manual(icns, iconset, entries)
    print(f"已生成：{icns}")


def _write_icns_manual(
    icns: Path,
    iconset: Path,
    entries: list[tuple[str, int, str | None]],
) -> None:
    """手工组装 ICNS：'icns' 魔数 + 总长度 + 若干 (OSType, 长度, PNG 数据) 条目。

    现代 macOS（10.15+）的 .icns 允许 PNG 压缩条目， Finder/Dock 均正常显示。
    """
    blocks: list[bytes] = []
    for name, _px, ostype in entries:
        if not ostype:
            continue  # icon_16x16/icon_32x32 的一倍图可省略（有 @2x 已足够）
        data = (iconset / name).read_bytes()
        blocks.append(ostype.encode("ascii") + struct.pack(">I", len(data) + 8) + data)
    total = 8 + sum(len(b) for b in blocks)
    payload = b"icns" + struct.pack(">I", total) + b"".join(blocks)
    icns.write_bytes(payload)


def _pyinstaller(spec: Path, clean: bool) -> None:
    args = [sys.executable, "-m", "PyInstaller", str(spec), "--noconfirm"]
    if clean:
        args.append("--clean")
    _run(args)


def _qt6_root(app_dir: Path) -> Path | None:
    """定位 bundle 内的 PyQt6/Qt6 目录。

    注意：macOS .app 的 PyInstaller one-folder 实际位于 Contents/Frameworks
    （sys._MEIPASS），不是 Contents/MacOS —— 不能写死路径，必须全包搜索。
    """
    hits = [p for p in app_dir.rglob("PyQt6/Qt6") if p.is_dir()]
    return hits[0] if hits else None


def _prune_app(app_dir: Path) -> None:
    """删除无用的 Qt 翻译与 QtPdf，显著减小 .app 体积。

    注意：PyQt6/Qt6 在 bundle 内可能有多份（Frameworks/Resources，可能互为软链）。
    只删其中一份会让另一份变悬空软链 → 后续 copytree 崩溃。必须全量清理。
    """
    for translations in list(app_dir.rglob("PyQt6/Qt6/translations")):
        try:
            if translations.is_symlink():
                translations.unlink()
            elif translations.is_dir():
                shutil.rmtree(translations)
            print(f"removed Qt translations: {translations}")
        except FileNotFoundError:
            pass  # 已随软链目标一起消失
    qt_pdf = app_dir / "Contents" / "Frameworks" / "QtPdf.framework"
    if qt_pdf.exists():
        shutil.rmtree(qt_pdf)
        print(f"removed QtPdf framework: {qt_pdf}")


def _is_macho_dylib(path: Path) -> bool:
    """粗略判断文件是否为可被 dlopen 的 Mach-O 动态库（MH_DYLIB）。

    用于在物化 Python 共享库前排除「解释器可执行文件（MH_EXECUTE）」这类
    无法被 PyInstaller 启动器 dlopen 的文件。无法判定（非 Mach-O / 通用二进制
    未深究）时放行，避免误杀。
    """
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except OSError:
        return False
    # 通用二进制（FAT）：放行（x86_64 单架构产物通常不是 fat，这里不深究）
    if magic in (b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
        return True
    if magic in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"):  # MH_MAGIC_64
        try:
            with open(path, "rb") as f:
                f.seek(12)  # magic(4)+cputype(4)+cpusubtype(4)
                ft = struct.unpack("<I", f.read(4))[0]
        except OSError:
            return False
        return ft == 0x6  # MH_DYLIB
    if magic in (b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce"):  # MH_MAGIC (32-bit)
        try:
            with open(path, "rb") as f:
                f.seek(12)
                ft = struct.unpack("<I", f.read(4))[0]
        except OSError:
            return False
        return ft == 0x6
    return False


def _find_libpython() -> Path | None:
    """定位构建用 Python 的共享库（libpython dylib），用于物化到 bundle。

    框架式 Python：真正的本体是 Python.framework/Versions/x/Python（MH_DYLIB，
    可被 dlopen 的动态库，PyInstaller 自身也用它）；bin/python3.x 只是解释器
    可执行文件（MH_EXECUTE），绝不能拿来当 Python 共享库，否则启动器 dlopen 失败。
    非框架（homebrew/pyenv --enable-shared）：本体是 lib/libpython3.x.dylib。

    候选顺序：框架 dylib 最优先，其次 libpython*.dylib/*.so，最后兜底
    sys.executable（仅当它“看起来像 dylib”时才采用，否则跳过以免误用可执行文件）。
    """
    prefix = Path(sys.prefix)
    cands: list[Path] = []
    cands.append(prefix / "Python")  # 框架式 dylib —— 首选
    cands += sorted(
        prefix.rglob("libpython*.dylib"),
        key=lambda p: -p.stat().st_size if p.exists() else 0,
    )
    cands += list(prefix.rglob("libpython*.so"))
    cands.append(Path(os.path.realpath(sys.executable)))

    # 第一遍：真实文件且确为 dylib
    for c in cands:
        try:
            if c.exists() and not c.is_symlink() and _is_macho_dylib(c):
                return c
        except OSError:
            continue
    # 第二遍：解析软链后再判定
    for c in cands:
        try:
            r = Path(os.path.realpath(c))
            if r.exists() and not r.is_symlink() and _is_macho_dylib(r):
                return r
        except OSError:
            continue
    return None


def _ensure_python_lib(app_dir: Path) -> None:
    """确保 Contents/Frameworks/Python 是真实存在的 libpython（非悬空符号链接）。

    关键修复：PyInstaller 在部分框架式 Python 上会把该文件生成为符号链接，
    dmg 拷贝时 shutil.copytree(ignore_dangling_symlinks=True) 会静默丢弃它，
    导致运行时 [PYI-848] Failed to load Python shared library -> 启动直接失败且
    不产生崩溃报告（正是 run#13 废包的根因）。这里强制物化为真实文件。
    """
    fw = app_dir / "Contents" / "Frameworks"
    fw.mkdir(parents=True, exist_ok=True)
    py = fw / "Python"
    if py.exists() and not py.is_symlink():
        print(f"Python 共享库已为真实文件，跳过物化：{py}")
        return
    src = _find_libpython()
    if src is None:
        raise RuntimeError(
            "未能定位构建用 Python 的共享库（libpython），无法物化 "
            "Contents/Frameworks/Python。请检查 CI 使用的 Python 是否为框架/"
            "含 libpython 的构建。"
        )
    if py.is_symlink() or py.exists():
        py.unlink()
    shutil.copy2(src, py)
    size = py.stat().st_size
    if not _is_macho_dylib(py):
        raise RuntimeError(
            f"致命：物化后的 Contents/Frameworks/Python 不是可被 dlopen 的 Mach-O 动态库"
            f"（疑似误用了 MH_EXECUTE 可执行文件，来源 {src}）。该文件无法被 PyInstaller 启动器加载，"
            f"会导致 [PYI-xxx] Failed to load Python shared library。请修正 _find_libpython 候选顺序。"
        )
    print(f"已物化 Python 共享库 -> {py}（来源 {src}，{size} 字节，已校验为 Mach-O dylib）")


def _ensure_qt_conf(app_dir: Path) -> None:
    """显式写入 qt.conf，强制 Qt 用文件系统路径解析 Qt 库/插件，而非查询主 bundle。

    关键修复：PyQt6/Qt 6.x 在 .so 静态初始化期会调用 QLibraryInfo::path()
    -> CFBundleCopyBundleURL()，若 qt.conf 缺失则该调用在 CFBundleGetMainBundle()
    返回 NULL 时直接 SIGSEGV（EXC_BAD_ACCESS）。显式给出 Prefix 可彻底绕开 bundle 查询。
    """
    macos_dir = app_dir / "Contents" / "MacOS"
    qt6_dir = _qt6_root(app_dir)
    if qt6_dir is None:
        print("警告：未找到 PyQt6/Qt6 目录，跳过 qt.conf 写入")
        return
    # Prefix 为相对于 qt.conf 所在目录（Contents/MacOS）的路径
    prefix = os.path.relpath(qt6_dir, macos_dir)
    conf = (
        "[Paths]\n"
        f"Prefix = {prefix}\n"
        f"Libraries = {prefix}/lib\n"
        f"Plugins = {prefix}/plugins\n"
        f"Imports = {prefix}/imports\n"
        f"Qml2Imports = {prefix}/qml\n"
        f"ArchData = {prefix}\n"
        f"Data = {prefix}\n"
        f"Translations = {prefix}/translations\n"
    )
    # Qt 查找顺序：可执行文件同目录 -> ../Resources；两者都写，确保命中
    targets = [macos_dir / "qt.conf"]
    resources_dir = app_dir / "Contents" / "Resources"
    if resources_dir.exists():
        targets.append(resources_dir / "qt.conf")
    for t in targets:
        t.write_text(conf, encoding="utf-8")
        print(f"wrote qt.conf -> {t} (Prefix={prefix})")


def _qt6_lib_has_multimedia(lib_dir: Path) -> bool:
    """判断某 Qt6 lib 目录是否含 QtMultimedia 动态库（darwinmedia 后端依赖）。

    关键：PyQt6-Qt6 6.7.3 的 macOS wheel 里框架名为 QtMultimedia.framework（**不带 "6"**），
    且为标准 Versions/A 布局：QtMultimedia.framework/Versions/A/QtMultimedia；
    扁平 dylib 形态则为 libQt6Multimedia*.dylib / libQtMultimedia*.dylib。
    （之前数版 run 全在找 Qt6*.framework 这种错误名字 -> 永远匹配不到 -> 校验必失败、无声。）
    """
    if not lib_dir.is_dir():
        return False
    try:
        names = [n for n in os.listdir(str(lib_dir))]
    except OSError:
        return False
    for fw in ("QtMultimedia.framework", "Qt6Multimedia.framework"):
        if fw in names:
            fw_dir = lib_dir / fw
            # 标准布局：Versions/A/<name>
            main = fw_dir / "Versions" / "A" / fw[: -len(".framework")]
            if main.is_file():
                return True
            # 扁平 framework（无 Versions）：<fw>/<name>
            if (fw_dir / fw[: -len(".framework")]).is_file():
                return True
    # 扁平 dylib 形态（部分环境）
    for n in names:
        if n.startswith(("libQt6Multimedia", "libQtMultimedia")) and n.endswith(".dylib"):
            return True
    return False


def _find_qt6_lib() -> Path | None:
    """定位 PyQt6 自带的 Qt6 库目录（macOS 为 Qt6*.framework 目录；部分环境为扁平 libQt6*.dylib）。

    关键修复：本环境 PyQt6 以 .framework 形式提供 Qt6 库（如 Qt6Core.framework），
    不存在 libQt6Core.dylib 扁平文件。上一版以 libQt6Core.dylib 为锚点 -> 返回 None ->
    _ensure_qt_frameworks 整体跳过补全 -> Qt6Multimedia.framework 未进包 -> 播放无声。
    改为以「Qt6Core.framework 目录 或 libQt6Core.dylib 文件」任一存在即认定源目录，
    两种形态都兼容；再由 _ensure_qt_frameworks 把整目录 Qt6*.framework / libQt6*.dylib
    全量补进 bundle（覆盖多媒体后端依赖）。
    """
    anchors: list[str] = []
    try:
        import PyQt6
        anchors.append(os.path.join(os.path.realpath(PyQt6.__file__), "Qt6", "lib"))
    except Exception:
        pass
    try:
        import PyQt6.QtCore as _qc
        anchors.append(os.path.join(os.path.dirname(os.path.realpath(_qc.__file__)), "Qt6", "lib"))
    except Exception:
        pass
    try:
        import site
        for s in site.getsitepackages():
            anchors.append(os.path.join(s, "PyQt6", "Qt6", "lib"))
    except Exception:
        pass
    anchors += [sys.prefix, os.path.dirname(sys.prefix)]
    seen: set[str] = set()
    dirs: list[str] = []
    for a in anchors:
        ra = os.path.realpath(a)
        if ra and ra not in seen:
            seen.add(ra)
            dirs.append(ra)

    def _is_qt_lib_dir(d: str) -> bool:
        if not os.path.isdir(d):
            return False
        try:
            names = os.listdir(d)
        except OSError:
            return False
        # 本环境 PyQt6-Qt6 6.7.3 为 Qt*.framework 目录（无 "6"），也可能为 Qt6*.framework 或扁平 libQt6*.dylib
        return any(
            (n.endswith(".framework") and os.path.isdir(os.path.join(d, n)))
            or (n.startswith("libQt6") and n.endswith(".dylib") and os.path.isfile(os.path.join(d, n)))
            for n in names
        )

    # 直接命中：含 Qt6Core.framework 目录 或 libQt6Core.dylib 文件即认定
    for d in dirs:
        if _is_qt_lib_dir(d):
            return Path(d)
    # 兜底：rglob 全树（限深，避免卡死）找含 Qt6 库的目录
    for d in dirs:
        try:
            for root, sub, _files in os.walk(d):
                if root.count(os.sep) - d.count(os.sep) > 6:
                    sub[:] = []
                    continue
                if _is_qt_lib_dir(root):
                    return Path(root)
        except Exception:
            continue
    return None


def _ensure_qt_frameworks(app_dir: Path) -> None:
    """把 PyQt6 的 Qt6 Multimedia 动态库（QtMultimedia.framework，名无 "6"）补进 bundle 每一份 Qt6 树。

    形态兼容：本环境 PyQt6-Qt6 6.7.3 为 Qt*.framework 目录（如 QtMultimedia.framework，标准
    Versions/A 布局）；部分环境为扁平 libQt6Multimedia*.dylib。两者都处理（framework 用 copytree 整目录复制）。

    为何需要：PyInstaller 的 hook-PyQt6.QtMultimedia 虽调用 add_qt6_dependencies 收集框架，
    但在本环境的最终 bundle 中 QtMultimedia.framework 时常未落地（依赖解析/去重/打包环节的
    非确定性），导致 darwinmedia 后端插件 dlopen 失败 -> 'No QtMultimedia backends found' ->
    播放无声。此处为确定性兜底：从 PyQt6 安装位置把整目录 Qt6*.framework / libQt6*.dylib
    【逐根复制】到 bundle 内每一份 PyQt6/Qt6/lib（Frameworks/Resources 多份树都覆盖），
    任一份缺就补。这样 darwinmedia 后端插件经 @rpath 必能命中 Qt6Multimedia -> 出声。
    """
    src_lib = _find_qt6_lib()
    if src_lib is None:
        print("警告：未定位到源 Qt 库目录，跳过 Qt 动态库补全（若 build.spec 已收集则无碍）")
        return
    qt6_roots = {p.resolve() for p in app_dir.rglob("PyQt6/Qt6") if p.is_dir()}
    if not qt6_roots:
        print("警告：bundle 内未找到 PyQt6/Qt6，跳过 Qt 动态库补全")
        return
    # 待复制项：仅 multimedia 家族（darwinmedia 后端仅依赖 QtMultimedia.framework；
    # QMediaPlayer 触屏/Widgets 上下文可能用到 QtMultimediaWidgets/Quick，一并纳入 Qt*Multimedia*）。
    # 形态：Qt*.framework 目录（本环境，名无 "6"）或扁平 libQt*Multimedia*.dylib（部分环境）。
    # 注意：不要全量复制所有 Qt*.framework（85 个约 40MB 会撑大包），且本环境框架名为 Qt* 非 Qt6*，
    # 旧逻辑用 "Qt6" 前缀会一个都匹配不到 -> 漏收。
    items: list[str] = []
    try:
        for n in os.listdir(str(src_lib)):
            is_fw = (("Multimedia" in n) and n.endswith(".framework") and os.path.isdir(os.path.join(str(src_lib), n)))
            is_dylib = (n.startswith("libQt") and "Multimedia" in n and n.endswith(".dylib")
                        and os.path.isfile(os.path.join(str(src_lib), n)))
            if is_fw or is_dylib:
                items.append(n)
    except OSError:
        pass
    copied = []
    for item in items:
        src = src_lib / item
        for root in sorted(qt6_roots):
            dst = root / "lib" / item
            # 判定该根是否已完整落地（避免把 build.spec 已正确收集的覆盖/误判为缺）
            complete = False
            if src.is_dir() and dst.is_dir():
                main = dst / "Versions" / "A" / item[: -len(".framework")]
                complete = main.is_file() or (dst / item[: -len(".framework")]).is_file()
            elif src.is_file() and dst.is_file():
                complete = True
            if complete:
                continue
            try:
                if src.is_dir():
                    if dst.exists():
                        shutil.rmtree(str(dst), ignore_errors=True)
                    shutil.copytree(str(src), str(dst), symlinks=True)
                else:
                    shutil.copy2(str(src), str(dst))
                copied.append(f"{item} -> {root.name}/lib")
            except Exception as e:
                print(f"警告：拷贝 {item} 到 {root} 失败：{e}")
    if copied:
        print(f"已补全缺失 Qt Multimedia 动态库 {len(copied)} 处：{'; '.join(copied)}")
    else:
        print("Qt Multimedia 动态库已齐全（PyInstaller 阶段已收集或无需补全）")


def _verify_multimedia_plugins(app_dir: Path) -> None:
    """校验 QtMultimedia 后端插件与其依赖的 Qt6Multimedia 动态库已打进包（缺失 = QMediaPlayer 静默无声）。"""
    qt6 = _qt6_root(app_dir)
    plugins_root = qt6 / "plugins" if qt6 is not None else None
    multimedia = plugins_root / "multimedia" if plugins_root else None
    if not multimedia or not multimedia.is_dir() or not any(multimedia.iterdir()):
        raise RuntimeError(
            "QtMultimedia 后端插件（plugins/multimedia/，AVFoundation 后端）未打进 .app！"
            "这将导致音乐播放彻底无声。请检查 PyInstaller 的 hook-PyQt6.QtMultimedia 是否生效。"
        )
    names = [f.name for f in sorted(multimedia.iterdir())]
    print(f"multimedia 后端插件已就位：{names}")
    # 插件存在 ≠ 后端可用：darwinmedia 插件依赖 Qt6Multimedia 动态库
    #（Qt6Multimedia.framework 或扁平 libQt6Multimedia*.dylib，两种形态都可能）。
    # bundle 可能有多份 PyQt6/Qt6 树（Frameworks/Resources）。只要【任一根】含该库，
    # 加载器即可命中含库那份并加载 AVFoundation 后端 -> 出声。故改为「至少一根含库」，
    # 但仍对「全部缺失」致命报错，避免发布无声废包。
    qt6_roots = {p.resolve() for p in app_dir.rglob("PyQt6/Qt6") if p.is_dir()}
    if not qt6_roots:
        raise RuntimeError(
            "致命：bundle 内未找到任何 PyQt6/Qt6 根目录，无法校验 QtMultimedia 动态库。"
        )
    # 先尝试兜底补全（build.spec 阶段未收集时仍有机会救回）
    _ensure_qt_frameworks(app_dir)
    good = [str(r) for r in sorted(qt6_roots) if _qt6_lib_has_multimedia(r / "lib")]
    missing = [str(r) for r in sorted(qt6_roots) if not _qt6_lib_has_multimedia(r / "lib")]
    if not good:
        raise RuntimeError(
            "致命：bundle 内所有 PyQt6/Qt6/lib 均缺失 QtMultimedia 动态库"
            "（QtMultimedia.framework 或 Qt6Multimedia.framework 或 libQt*Multimedia*.dylib）！"
            "multimedia 插件（AVFoundation 后端）将因依赖缺失无法加载，导致 QMediaPlayer 初始化失败、音乐播放无声。"
            "可能原因：① 本环境 PyQt6 wheel 未随附 libQt6Multimedia.dylib（可换用 pip 官方 wheel 或 brew install qt6 后重装 PyQt6）；"
            "② build.spec 的 Qt6 动态库收集逻辑未生效。请检查 CI 日志中 '[build.spec] 已显式收集 Qt6 动态库' 行与 _find_qt6_lib 输出。"
        )
    if missing:
        print(f"注意：以下根缺 Qt6Multimedia 动态库（不影响加载，已存在含库的根）：{missing}")
    print(f"Qt6Multimedia 动态库已就位（含库根数={len(good)}/{len(qt6_roots)}）")


def build_app() -> Path:
    _pyinstaller(ROOT / "build.spec", True)
    app = DIST / "AT小PP.app"
    if not app.exists():
        raise FileNotFoundError(f"未生成应用包：{app}")
    _ensure_python_lib(app)
    _prune_app(app)
    _ensure_qt_conf(app)
    _ensure_qt_frameworks(app)
    _verify_multimedia_plugins(app)
    _codesign(app)
    return app


def build_dmg(app_dir: Path) -> Path:
    """把真正的 AT小PP.app 直接打进 .dmg（拖进 /Applications 即用，无安装向导）。"""
    RELEASE.mkdir(parents=True, exist_ok=True)
    stage = BUILD / "dmg_stage"
    if stage.exists():
        shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    app_dest = stage / "AT小PP.app"
    # symlinks=True：忠实保留 bundle 内所有符号链接（含 Qt 的 Frameworks/Resources
    # 互为软链、以及可能的悬空链），绝不静默丢弃文件。
    # 注意：绝不能用 ignore_dangling_symlinks=True —— 它会把悬空软链直接跳过，
    # 导致 run#13 废包（Contents/Frameworks/Python 被丢弃 → [PYI-848] 启动失败，
    # 且整包体积比正常小很多）。
    shutil.copytree(app_dir, app_dest, symlinks=True)
    # 致命校验：拷贝后必须存在 Python 共享库（已由 _ensure_python_lib 物化为真实文件）。
    # 若缺失直接构建失败，绝不发布残缺包。
    py_lib = app_dest / "Contents" / "Frameworks" / "Python"
    if not py_lib.exists():
        raise RuntimeError(
            f"致命：dmg 拷贝后缺失 {py_lib}（Python 共享库）。"
            "构建产物不完整，已中止发布。请检查 _ensure_python_lib / copytree 逻辑。"
        )

    # Applications 快捷方式（拖放安装入口：把 .app 拖进这里即装到 /Applications）
    os.symlink("/Applications", str(stage / "Applications"))

    dmg = RELEASE / "AT小PP-macos.dmg"
    if dmg.exists():
        dmg.unlink()
    _run([
        "hdiutil", "create",
        "-volname", "AT小PP",
        "-srcfolder", str(stage),
        "-ov", "-format", "UDZO",
        str(dmg),
    ])
    # 对 .dmg 也做自签名，进一步降低挂载时的拦截
    _codesign(dmg)
    print(f"已生成安装包：{dmg}")
    return dmg


def main() -> int:
    parser = argparse.ArgumentParser(description="Build AT小PP macOS installer (.dmg).")
    parser.add_argument("--clean", action="store_true", help="强制完整重建")
    parser.add_argument("--skip-assets", action="store_true", help="复用已有 app_icon.icns")
    parser.add_argument(
        "--universal", action="store_true",
        help="产出通用二进制 universal2（Intel+Apple Silicon）。需宿主机 Python 为 universal2 且依赖含通用切片。",
    )
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("错误：本脚本只能在 macOS 上运行（PyInstaller 无法跨平台编译 .app/.dmg）。", file=sys.stderr)
        print("提示：请在 macOS 本机（或 macOS 虚拟机）中执行本脚本，全程免费、无需 GitHub 配额。", file=sys.stderr)
        return 2

    if args.universal:
        if not _python_is_universal():
            print(
                "警告：当前 Python 不是 universal2 构建，无法产出通用二进制；"
                "将回退为宿主机架构（仍可用）。若需 universal2，请改用 python.org 的 universal2 安装包。",
                file=sys.stderr,
            )
        else:
            os.environ["ATPP_TARGET_ARCH"] = "universal2"
            print("已启用 universal2 通用二进制构建。")

    if not args.skip_assets:
        ensure_icns()

    app = build_app()
    dmg = build_dmg(app)
    print(f"\nmacOS 发行包构建完成：{dmg}")
    print("使用：挂载 .dmg 后把 AT小PP.app 拖进 /Applications（或 ~/Applications）即可；卸载 = 拖进废纸篓。")
    if args.universal:
        print("（注：universal2 实际成败取决于 PyQt6/Qt 等依赖是否提供通用切片；"
              "若 .app 仅含单架构，请用 Intel 宿主机构建以获得最广覆盖。）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
