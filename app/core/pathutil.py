"""AT小PP · 资源与数据路径工具

兼容两种运行方式：
1. 源码运行（python app/main.py）
2. PyInstaller 打包后运行（sys.frozen，资源随 exe 释放到 sys._MEIPASS / 同级目录）
"""

import os
import sys

# 项目根目录（源码模式下为仓库根，打包模式下为 exe 所在目录）
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _bundle_dir() -> str:
    """PyInstaller 资源目录。one-folder 下通常是 exe 同级 _internal。"""
    return getattr(sys, "_MEIPASS", APP_DIR)


def get_bundled_data_dir() -> str:
    """打包内置数据目录，只读。"""
    return os.path.join(_bundle_dir(), "data")


def get_assets_dir() -> str:
    """素材根目录。"""
    if getattr(sys, "frozen", False):
        bundled = os.path.join(_bundle_dir(), "assets")
        if os.path.isdir(bundled):
            return bundled
        return os.path.join(APP_DIR, "assets")
    return os.path.join(APP_DIR, "assets")


def _ensure_dir(path: str) -> str:
    try:
        os.makedirs(path, exist_ok=True)
    except FileExistsError:
        if not os.path.isdir(path):
            raise RuntimeError(f"数据目录路径被同名文件占用：{path}")
    return path


def _is_inside_bundle(path: str) -> bool:
    """判断路径是否落在 PyInstaller 应用包内部（.app/Contents 或 _MEIPASS）。

    打包后若数据目录被解析到包内，覆盖安装会整体替换 .app → 用户数据随之被删。
    此函数用于「覆盖安装保留用户数据」的防御性兜底。
    """
    if not getattr(sys, "frozen", False):
        return False
    p = os.path.realpath(path)
    for cand in (APP_DIR, getattr(sys, "_MEIPASS", "")):
        if not cand:
            continue
        rc = os.path.realpath(cand)
        if p == rc or p.startswith(rc + os.sep):
            return True
    return False


def get_data_dir() -> str:
    """用户数据目录（设置/待办/闹钟/上传音乐等持久化内容）。

    打包后写入系统 AppData / Application Support，**永远位于应用包之外**，
    保证覆盖安装 / 卸载重装不丢数据；源码模式下写入仓库 data 目录，便于开发调试。

    ⚠️ 覆盖安装保护：macOS 的「拖 .app 覆盖安装」会整体替换旧 .app。只要用户数据
    在包外（本函数既定行为），覆盖安装天然不碰数据。为防未来任何改动让数据目录
    意外解析进包内，下面用 _is_inside_bundle 强制作废并重定向到 Application Support。
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            # macOS：系统级应用数据目录，保证卸载重装不丢数据。
            base = os.path.expanduser("~/Library/Application Support")
            d = os.path.join(base, "AT小PP")
        else:
            base = os.environ.get("APPDATA") or os.path.expanduser("~")
            d = os.path.join(base, "AT小PP")
        # 覆盖安装兜底：数据目录绝不可落在 .app 包内，否则覆盖安装整体替换 .app
        # 会把用户数据一起删掉。强制重定向到 Application Support，保证「覆盖安装不丢数据」。
        if _is_inside_bundle(d):
            safe = os.path.join(os.path.expanduser("~/Library/Application Support"), "AT小PP")
            try:
                import sys as _s
                print(f"[pathutil] 数据目录落在应用包内（{d}），已重定向到 {safe} 以防覆盖安装丢数据")
            except Exception:  # noqa: BLE001
                pass
            d = safe
    else:
        d = os.path.join(APP_DIR, "data")
    _ensure_dir(d)
    _ensure_dir(os.path.join(d, "music"))
    return d


def asset(*parts: str) -> str:
    """拼接素材路径。"""
    return os.path.join(get_assets_dir(), *parts)


def data_file(*parts: str) -> str:
    """拼接数据文件路径，必要时创建父目录。"""
    path = os.path.join(get_data_dir(), *parts)
    parent = os.path.dirname(path)
    if parent:
        _ensure_dir(parent)
    return path
