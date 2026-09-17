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


def get_data_dir() -> str:
    """用户数据目录（设置/待办/闹钟/上传音乐等持久化内容）。

    打包后写入系统 AppData，保证卸载重装不丢数据；
    源码模式下写入仓库 data 目录，便于开发调试。
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            # macOS：系统级应用数据目录，保证卸载重装不丢数据。
            base = os.path.expanduser("~/Library/Application Support")
            d = os.path.join(base, "AT小PP")
        else:
            base = os.environ.get("APPDATA") or os.path.expanduser("~")
            d = os.path.join(base, "AT小PP")
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
