"""安装向导与卸载器。

安装流程：选择语言 → 安装路径 + 桌面快捷方式 + 开机自启动 → 安装进度 → 完成（完成/打开）。
卸载：删除安装目录、桌面快捷方式、注册表自启项，并通过临时脚本清理自身。
依赖 Windows（winreg / Shell 快捷方式），仅 Windows 运行。
"""

import os
import sys
import json
import shutil
import subprocess
import tempfile

from PyQt6.QtCore import Qt, QThread, QTimer, QRectF, QPointF, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QLineEdit, QComboBox, QHBoxLayout,
    QVBoxLayout, QFileDialog, QCheckBox, QStackedWidget,
    QGraphicsDropShadowEffect, QApplication, QDialog,
    QRadioButton, QButtonGroup,
)
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

from app.core import assets, config, pathutil
from app.core.i18n import tr
from app.core.voice import say

APP_NAME = config.character.app_name
REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
MANIFEST = "install_manifest.json"
SKIP_DIRS = {"venv", "__pycache__", ".git", "build", "dist", "node_modules"}
UNINSTALL_REG_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
_MUTEX_HANDLES = []
_LOCK_FILES = []


def _with_dots(text: str) -> str:
    return text if text.endswith(("...", "…")) else text + "..."


def _norm_install_dir(path: str) -> str:
    return os.path.normpath(os.path.abspath(os.path.expandvars(os.path.expanduser(path))))


def _default_install_dir() -> str:
    if sys.platform == "darwin":
        return _macos_default_install_dir()
    base = os.environ.get("ProgramFiles") or (os.path.splitdrive(os.path.expanduser("~"))[0] + os.sep + "Program Files")
    return _norm_install_dir(os.path.join(base, APP_NAME))


def _is_windows_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def acquire_single_instance(name: str) -> bool:
    if os.name == "nt":
        locked = False
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            mutex_name = name.replace("Global\\", "Local\\", 1)
            handle = kernel32.CreateMutexW(None, True, mutex_name)
            if handle:
                _MUTEX_HANDLES.append(handle)
                if kernel32.GetLastError() == 183:
                    return False
                locked = True
        except Exception:  # noqa: BLE001
            pass
        try:
            import msvcrt
            safe = "".join(ch if ch.isalnum() else "_" for ch in name)
            lock_path = os.path.join(tempfile.gettempdir(), safe + ".lock")
            f = open(lock_path, "a+b")
            f.seek(0)
            if not f.read(1):
                f.write(b"0")
                f.flush()
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            _LOCK_FILES.append(f)
            return True
        except Exception:  # noqa: BLE001
            return locked
    # macOS / Linux：文件锁实现单例
    try:
        import fcntl
        safe = "".join(ch if ch.isalnum() else "_" for ch in name)
        lock_path = os.path.join(tempfile.gettempdir(), safe + ".lock")
        f = open(lock_path, "a+b")
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _LOCK_FILES.append(f)
        return True
    except Exception:  # noqa: BLE001
        return False


def _terminate_installed_app(install_dir: str):
    if sys.platform == "darwin":
        try:
            subprocess.run(
                ["pkill", "-f", APP_NAME + ".app"], check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:  # noqa: BLE001
            pass
        return
    exe = _installed_exe_path(install_dir)
    if not os.path.exists(exe):
        return
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["taskkill.exe", "/IM", os.path.basename(exe), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            timeout=5,
            check=False,
        )
    except Exception:  # noqa: BLE001
        pass


def show_running_warning(message: str):
    dlg = InstallNoticeDialog(None, message)
    dlg.exec()

INSTALL_QSS = """
QWidget#InstallWindow {
    background: #fffaf5;
    border: 1px solid rgba(255,255,255,0.70);
    border-radius: 20px;
}
QWidget#installChrome { background: transparent; }
QPushButton#windowMin, QPushButton#windowClose {
    background: transparent;
    border: none;
    border-radius: 8px;
    color: #a08e7a;
    font-size: 16px;
    font-weight: 700;
    padding: 0;
}
QPushButton#windowMin:hover {
    background: rgba(249,117,16,0.10);
    color: #f97510;
}
QPushButton#windowClose:hover {
    background: rgba(229,57,53,0.08);
    color: #e53935;
}
QWidget#installPage, QWidget#installBody { background: transparent; }
QLabel#stickerImage { background: transparent; }
QLabel#installLogo {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #f97510, stop:1 #e65100);
    border-radius: 16px;
    color: #ffffff;
    font-size: 30px;
    font-weight: 800;
}
QLabel#installTitle {
    color: #3d2b1f;
    font-size: 20px;
    font-weight: 800;
    background: transparent;
}
QLabel#installSub {
    color: #a08e7a;
    font-size: 12px;
    font-weight: 500;
    background: transparent;
    margin-top: 4px;
}
QLabel#fieldLabel {
    color: #6b5744;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}
QComboBox#installField, QLineEdit#installPath {
    background: rgba(249,117,16,0.04);
    border: 1.5px solid rgba(249,117,16,0.12);
    border-radius: 8px;
    color: #3d2b1f;
    font-size: 13px;
    font-weight: 500;
    min-height: 28px;
    max-height: 28px;
    padding: 3px 12px;
}
QComboBox#installField:focus, QLineEdit#installPath:focus {
    background: #ffffff;
    border-color: #f97510;
}
QComboBox#installField::drop-down {
    border: none;
    width: 28px;
}
QComboBox#installField::down-arrow { image: none; }
QComboBox#installField QAbstractItemView {
    background: #ffffff;
    border: 1px solid rgba(249,117,16,0.22);
    border-radius: 8px;
    selection-background-color: rgba(249,117,16,0.12);
    selection-color: #f97510;
    outline: 0;
}
QPushButton#pathButton {
    background: rgba(255,255,255,0.50);
    border: 1.5px solid rgba(249,117,16,0.12);
    border-radius: 18px;
    color: #6b5744;
    font-size: 12px;
    font-weight: 600;
    min-height: 28px;
    max-height: 28px;
    padding: 3px 14px;
}
QPushButton#pathButton:hover {
    border-color: #f97510;
    color: #f97510;
    background: rgba(249,117,16,0.06);
}
QCheckBox {
    color: #6b5744;
    font-size: 12px;
    font-weight: 500;
    spacing: 7px;
    background: transparent;
}
QCheckBox::indicator {
    width: 12px;
    height: 12px;
    border: 1.2px solid rgba(160,142,122,0.35);
    border-radius: 4px;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: #f97510;
    border-color: #f97510;
}
QRadioButton {
    color: #6b5744;
    font-size: 13px;
    font-weight: 600;
    spacing: 8px;
    background: transparent;
    min-height: 32px;
    max-height: 32px;
    padding: 6px 10px;
}
QRadioButton:hover {
    color: #f97510;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 1.5px solid rgba(160,142,122,0.35);
    border-radius: 9px;
    background: #ffffff;
}
QRadioButton::indicator:checked {
    background: #f97510;
    border-color: #f97510;
}
QWidget#installFooter {
    background: transparent;
    border-top: 1px solid rgba(249,117,16,0.12);
}
QWidget#stepDot {
    background: rgba(160,142,122,0.35);
    border-radius: 3px;
}
QWidget#stepDotActive {
    background: #f97510;
    border-radius: 3px;
}
QPushButton {
    background: rgba(255,255,255,0.50);
    border: 1.5px solid rgba(249,117,16,0.12);
    border-radius: 18px;
    color: #6b5744;
    font-size: 12px;
    font-weight: 600;
    min-height: 28px;
    max-height: 28px;
    padding: 3px 16px;
}
QPushButton:hover {
    background: rgba(249,117,16,0.10);
    border-color: rgba(249,117,16,0.25);
    color: #f97510;
}
QPushButton#primary {
    background: #f97510;
    border-color: #f97510;
    color: #ffffff;
    font-weight: 700;
}
QPushButton#primary:hover {
    background: #ffa940;
    border-color: #ffa940;
    color: #ffffff;
}
QPushButton#disabledButton:disabled {
    background: rgba(160,142,122,0.08);
    border-color: rgba(160,142,122,0.20);
    color: #c9bcae;
}
QLabel#progressPercent {
    color: #f97510;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 32px;
    font-weight: 800;
    background: transparent;
}
QWidget#progressTrack {
    background: rgba(249,117,16,0.08);
    border-radius: 4px;
}
QWidget#progressFill {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #f97510, stop:1 #ffa940);
    border-radius: 4px;
}
QLabel#progressText, QLabel#successText {
    color: #a08e7a;
    font-size: 12px;
    font-weight: 500;
    background: transparent;
}
QLabel#successText { font-size: 14px; }
QLabel#uninstallMessage {
    color: #3d2b1f;
    font-size: 18px;
    font-weight: 800;
    background: transparent;
}
QLabel#uninstallSubText {
    color: #a08e7a;
    font-size: 12px;
    font-weight: 500;
    background: transparent;
}
QLabel#successIcon {
    background: rgba(249,117,16,0.10);
    border: 3px solid #f97510;
    border-radius: 36px;
    color: #f97510;
    font-size: 34px;
    font-weight: 800;
}
"""


def _source_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return pathutil.APP_DIR


def _dest_exe_name() -> str:
    if getattr(sys, "frozen", False):
        return os.path.basename(sys.executable)
    return f"{APP_NAME}.bat"


def _installed_exe_path(install_dir: str) -> str:
    return os.path.join(_norm_install_dir(install_dir), APP_NAME + ".exe")


def _inno_uninstaller_path(install_dir: str) -> str:
    return os.path.join(_norm_install_dir(install_dir), "unins000.exe")


# ---------------- 快捷方式（WScript.Shell COM，无额外依赖） ----------------
def create_shortcut(target, lnk_path, work_dir="", desc=""):
    try:
        import comtypes.client
        ws = comtypes.client.CreateObject("WScript.Shell")
        sc = ws.CreateShortcut(lnk_path)
        sc.TargetPath = target
        if work_dir:
            sc.WorkingDirectory = work_dir
        if desc:
            sc.Description = desc
        sc.Save()
        return True
    except Exception:  # noqa: BLE001
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            safe_lnk = lnk_path.replace("'", "''")
            safe_target = target.replace("'", "''")
            safe_work = (work_dir or os.path.dirname(target)).replace("'", "''")
            safe_desc = (desc or APP_NAME).replace("'", "''")
            command = (
                "$ws=New-Object -ComObject WScript.Shell;"
                f"$s=$ws.CreateShortcut('{safe_lnk}');"
                f"$s.TargetPath='{safe_target}';"
                f"$s.WorkingDirectory='{safe_work}';"
                f"$s.Description='{safe_desc}';"
                "$s.Save()"
            )
            proc = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-Command", command],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creationflags,
            )
            return proc.wait(timeout=8) == 0 and os.path.exists(lnk_path)
        except Exception:  # noqa: BLE001
            return False


def set_autostart(enable: bool, exe_path: str):
    if sys.platform == "darwin":
        _macos_set_autostart(enable, exe_path)
        return
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0,
                             winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
        if enable:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception:  # noqa: BLE001
        pass


def remove_autostart():
    if sys.platform == "darwin":
        _macos_set_autostart(False, "")
        return
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(key, APP_NAME)
        except FileNotFoundError:
            pass
        winreg.CloseKey(key)
    except Exception:  # noqa: BLE001
        pass


def write_custom_uninstall_registry(install_dir: str):
    if sys.platform == "darwin":
        _write_install_receipt(install_dir)
        return
    if os.name != "nt":
        return
    exe = _installed_exe_path(install_dir)
    try:
        remove_uninstall_registry()
        import winreg
        key_path = UNINSTALL_REG_ROOT + "\\" + APP_NAME + "_is1"
        key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_SET_VALUE)
        uninstall_cmd = f'"{exe}" --custom-uninstall'
        # 保持“应用和功能”里的卸载入口始终进入自定义卸载向导。
        # 真正的静默清理由程序内部调用 --quiet 完成，不依赖这个注册表值。
        quiet_cmd = uninstall_cmd
        values = {
            "DisplayName": APP_NAME,
            "DisplayVersion": "1.0",
            "Publisher": "Christopher Hsu",
            "DisplayIcon": exe,
            "UninstallString": uninstall_cmd,
            "QuietUninstallString": quiet_cmd,
            "InstallLocation": _norm_install_dir(install_dir),
            "NoModify": 1,
            "NoRepair": 1,
        }
        for name, value in values.items():
            if isinstance(value, int):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
            else:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.CloseKey(key)
    except Exception:  # noqa: BLE001
        pass


# ---------------- 复制线程 ----------------
class CopyWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool)

    def __init__(self, src, dst):
        super().__init__()
        self.src = src
        self.dst = dst

    def _walk(self):
        files = []
        for root, dirs, fs in os.walk(self.src):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in fs:
                if f.endswith(".pyc") or f == MANIFEST:
                    continue
                files.append(os.path.join(root, f))
        return files

    def run(self):
        try:
            files = self._walk()
            total = max(1, len(files))
            os.makedirs(self.dst, exist_ok=True)
            for i, f in enumerate(files):
                rel = os.path.relpath(f, self.src)
                target = os.path.join(self.dst, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(f, target)
                self.progress.emit(int((i + 1) / total * 100),
                                  os.path.basename(f))
            self.finished.emit(True)
        except Exception as e:  # noqa: BLE001
            self.finished.emit(False)


class InnoInstallWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, setup_exe, install_dir):
        super().__init__()
        self.setup_exe = setup_exe
        self.install_dir = install_dir

    def run(self):
        try:
            if not os.path.exists(self.setup_exe):
                self.finished.emit(False, f"后台安装包不存在：{self.setup_exe}")
                return
            _terminate_installed_app(self.install_dir)
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            log_path = os.path.join(tempfile.gettempdir(), "at_xiaopp_inner_setup.log")
            proc = subprocess.Popen(
                [
                    self.setup_exe,
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    "/CLOSEAPPLICATIONS",
                    "/FORCECLOSEAPPLICATIONS",
                    "/LOG=" + log_path,
                    "/DIR=" + self.install_dir,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creationflags,
            )
            code = proc.wait()
            if code == 0:
                self.finished.emit(True, "")
            else:
                self.finished.emit(False, f"后台安装失败，返回码 {code}；日志：{log_path}")
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(False, f"后台安装异常：{exc}")


class InnoUninstallWorker(QThread):
    finished = pyqtSignal(bool)

    def __init__(self, install_dir):
        super().__init__()
        self.install_dir = install_dir

    def run(self):
        try:
            uninstaller = _inno_uninstaller_path(self.install_dir)
            if not os.path.exists(uninstaller):
                self.finished.emit(False)
                return
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(
                [uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                cwd=self.install_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creationflags,
            )
            self.finished.emit(proc.wait() == 0)
        except Exception:  # noqa: BLE001
            self.finished.emit(False)


# ---------------- macOS 安装/卸载原语（与 Windows 分支并存，仅 macOS 调用） ----------------
# 定义保持无条件，确保 Windows 下导入安全；实际使用由 sys.platform 分支控制。
_MAC_LAUNCH_AGENT_LABEL = "com.christopherhsu.atxiaopp"
_MAC_RECEIPT_DIR = os.path.join(os.path.expanduser("~/Library/Application Support"), "AT小PP")
_MAC_RECEIPT_PATH = os.path.join(_MAC_RECEIPT_DIR, "install_receipt.json")


def _macos_payload_app_path() -> str:
    """安装器 .app 内置的真实应用包路径。

    PyInstaller 在 macOS BUNDLE 中把 datas 放在 ``sys._MEIPASS``（实际为
    ``Contents/Frameworks``），因此优先从 MEIPASS 找；其余路径仅作兼容兜底。
    """
    app_dir = APP_NAME + ".app"
    candidates: list[str] = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(os.path.join(meipass, "payload", app_dir))
    if getattr(sys, "frozen", False):
        macos_dir = os.path.dirname(sys.executable)  # .../Contents/MacOS
        contents = os.path.dirname(macos_dir)
        candidates.append(os.path.join(contents, "Frameworks", "payload", app_dir))
        candidates.append(os.path.join(macos_dir, "payload", app_dir))
        candidates.append(os.path.join(contents, "Resources", "payload", app_dir))
    for cand in candidates:
        if os.path.isdir(cand):
            return cand
    return ""


def _macos_default_install_dir() -> str:
    """macOS 默认安装位置：用户级 ~/Applications（免管理员权限）。"""
    user_apps = os.path.expanduser("~/Applications")
    base = user_apps if os.path.isdir(user_apps) else "/Applications"
    return _norm_install_dir(os.path.join(base, APP_NAME + ".app"))


def _macos_launch_agent_path() -> str:
    return os.path.expanduser(f"~/Library/LaunchAgents/{_MAC_LAUNCH_AGENT_LABEL}.plist")


def _write_install_receipt(install_dir: str):
    try:
        os.makedirs(_MAC_RECEIPT_DIR, exist_ok=True)
        with open(_MAC_RECEIPT_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {"install_dir": _norm_install_dir(install_dir), "app_name": APP_NAME},
                f, ensure_ascii=False, indent=2,
            )
    except Exception:  # noqa: BLE001
        pass


def _read_install_receipt() -> str:
    try:
        if os.path.exists(_MAC_RECEIPT_PATH):
            with open(_MAC_RECEIPT_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("install_dir", "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def _remove_install_receipt():
    try:
        if os.path.exists(_MAC_RECEIPT_PATH):
            os.remove(_MAC_RECEIPT_PATH)
    except Exception:  # noqa: BLE001
        pass


def _macos_set_autostart(enable: bool, app_path: str):
    plist = _macos_launch_agent_path()
    if enable:
        content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n<dict>\n'
            f'  <key>Label</key><string>{_MAC_LAUNCH_AGENT_LABEL}</string>\n'
            '  <key>ProgramArguments</key>\n  <array>\n'
            '    <string>/usr/bin/open</string>\n'
            f'    <string>-a</string>\n    <string>{app_path}</string>\n'
            '  </array>\n'
            '  <key>RunAtLoad</key><true/>\n'
            '  <key>LimitLoadToSessionType</key><string>Aqua</string>\n'
            '</dict>\n</plist>\n'
        )
        try:
            os.makedirs(os.path.dirname(plist), exist_ok=True)
            with open(plist, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:  # noqa: BLE001
            pass
    else:
        try:
            if os.path.exists(plist):
                os.remove(plist)
        except Exception:  # noqa: BLE001
            pass


class MacInstallWorker(QThread):
    """macOS 安装 worker：将内置的 payload .app 复制到目标位置（保留符号链接）。"""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, src, dst):
        super().__init__()
        self.src = src
        self.dst = dst

    def _count(self):
        n = 0
        for _root, _dirs, files in os.walk(self.src):
            n += len(files)
        return max(1, n)

    def run(self):
        try:
            if os.path.exists(self.dst):
                shutil.rmtree(self.dst, ignore_errors=True)
            os.makedirs(os.path.dirname(self.dst), exist_ok=True)
            total = self._count()
            counter = [0]

            def _copy(src, dst):
                counter[0] += 1
                try:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                except Exception:  # noqa: BLE001
                    pass
                self.progress.emit(int(counter[0] / total * 100), os.path.basename(src))

            shutil.copytree(self.src, self.dst, copy_function=_copy, symlinks=True)
            self.finished.emit(True, "")
        except Exception as e:  # noqa: BLE001
            self.finished.emit(False, f"复制应用失败：{e}")


class WindowControlButton(QPushButton):
    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(26, 24)
        self.setText("")

    def paintEvent(self, e):  # noqa: N802
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = self.underMouse()
        color = QColor("#e53935" if hover and self.kind == "close" else "#f97510" if hover else "#a08e7a")
        pen = QPen(color, 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        if self.kind == "min":
            painter.drawLine(8, 13, 18, 13)
            return
        painter.drawLine(9, 8, 17, 16)
        painter.drawLine(17, 8, 9, 16)


class InstallNoticeDialog(QDialog):
    def __init__(self, parent, message: str):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedSize(300, 166)
        self._drag_pos = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(0)

        card = QWidget(self)
        card.setObjectName("InstallWindow")
        card.setStyleSheet(INSTALL_QSS)
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 7)
        shadow.setColor(QColor(180, 120, 50, 32))
        card.setGraphicsEffect(shadow)
        root.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)

        title = QLabel(APP_NAME)
        title.setObjectName("installTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        text = QLabel(message)
        text.setObjectName("successText")
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(text, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        ok_b = QPushButton(tr("确定"))
        ok_b.setObjectName("primary")
        ok_b.setFixedWidth(76)
        ok_b.clicked.connect(self.accept)
        row.addWidget(ok_b)
        row.addStretch(1)
        lay.addLayout(row)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag_pos is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(e)


class InstallLogo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self.pixmap = QPixmap(assets.find_image("桌面图标") or "")

    def paintEvent(self, e):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if not self.pixmap.isNull():
            clip = QPainterPath()
            clip.addRoundedRect(rect, 16, 16)
            painter.setClipPath(clip)
            scaled = self.pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            return
        painter.setBrush(QColor("#f97510"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 16, 16)
        pen = QPen(QColor("#ffffff"), 6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath()
        path.moveTo(19, 48)
        path.lineTo(32, 17)
        path.lineTo(45, 48)
        painter.drawPath(path)
        painter.drawLine(QPointF(25, 37), QPointF(39, 37))


class SuccessIcon(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(72, 72)

    def paintEvent(self, e):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2.5, 2.5, -2.5, -2.5)
        painter.setBrush(QColor(249, 117, 16, 25))
        painter.setPen(QPen(QColor("#f97510"), 3))
        painter.drawEllipse(rect)
        pen = QPen(QColor("#f97510"), 6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QPointF(22, 37), QPointF(32, 47))
        painter.drawLine(QPointF(32, 47), QPointF(51, 26))


class StickerImage(QLabel):
    def __init__(self, asset_name, size=174, parent=None):
        super().__init__(parent)
        self.asset_name = asset_name
        self.setObjectName("stickerImage")
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.refresh()

    def refresh(self):
        pixmap = QPixmap(assets.find_image(self.asset_name) or "")
        if pixmap.isNull():
            self.clear()
            return
        self.setPixmap(pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))


class UninstallerWindow(QWidget):
    def __init__(self, inno_managed=False, run_inno_uninstaller=False):
        super().__init__()
        self.inno_managed = inno_managed
        if sys.platform == "darwin":
            # macOS 无 Inno，始终走内置清理逻辑。
            self.run_inno_uninstaller = False
            if getattr(sys, "frozen", False):
                # 当前进程即被卸载的 .app：回溯到 .app 根目录。
                self.install_dir = _norm_install_dir(
                    os.path.dirname(os.path.dirname(os.path.dirname(sys.executable))))
            else:
                self.install_dir = _macos_default_install_dir()
        else:
            self.run_inno_uninstaller = run_inno_uninstaller
            self.install_dir = _installed_dir_from_manifest()
        self._uninstall_worker = None
        self._uninstall_backend_done = not self.run_inno_uninstaller
        self._uninstall_backend_ok = True
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(444, 420)
        self._drag_pos = None
        self._progress = 0
        self._progress_keys = ["正在移除快捷入口", "正在清理应用配置", "正在准备卸载文件", "正在完成卸载"]
        self._progress_message_key = self._progress_keys[0]
        self._cleanup_scheduled = False
        self._timer = QTimer(self)
        self._timer.setInterval(58)
        self._timer.timeout.connect(self._tick_uninstall)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        self.container = QWidget()
        self.container.setObjectName("InstallWindow")
        self.container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.container.setStyleSheet(INSTALL_QSS)
        shadow = QGraphicsDropShadowEffect(self.container)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(180, 120, 50, 26))
        self.container.setGraphicsEffect(shadow)
        root.addWidget(self.container)

        outer = QVBoxLayout(self.container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        chrome = QWidget()
        chrome.setObjectName("installChrome")
        chrome.setFixedHeight(34)
        chrome_lay = QHBoxLayout(chrome)
        chrome_lay.setContentsMargins(16, 6, 10, 0)
        chrome_lay.setSpacing(6)
        chrome_lay.addStretch(1)
        self.min_btn = WindowControlButton("min")
        self.min_btn.setObjectName("windowMin")
        self.min_btn.clicked.connect(self.showMinimized)
        self.close_btn = WindowControlButton("close")
        self.close_btn.setObjectName("windowClose")
        self.close_btn.clicked.connect(self._cancel_uninstall)
        chrome_lay.addWidget(self.min_btn)
        chrome_lay.addWidget(self.close_btn)
        outer.addWidget(chrome)

        self.stack = QStackedWidget(self.container)
        outer.addWidget(self.stack, 1)
        self._build_confirm()
        self._build_progress()
        self._build_done()
        self.retranslate_ui()

    def _make_page(self, active_step):
        page = QWidget()
        page.setObjectName("installPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        body = QWidget()
        body.setObjectName("installBody")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(24, 0, 24, 24)
        body_lay.setSpacing(0)
        footer = QWidget()
        footer.setObjectName("installFooter")
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(24, 14, 24, 14)
        footer_lay.setSpacing(8)
        dots = QHBoxLayout()
        dots.setSpacing(6)
        for i in range(3):
            dot = QWidget()
            dot.setObjectName("stepDotActive" if i == active_step else "stepDot")
            dot.setFixedSize(20 if i == active_step else 6, 6)
            dots.addWidget(dot)
        footer_lay.addLayout(dots)
        footer_lay.addStretch(1)
        layout.addWidget(body, 1)
        layout.addWidget(footer)
        return page, body_lay, footer_lay

    def _build_confirm(self):
        w, v, footer = self._make_page(0)
        v.addStretch(1)
        self.pleading = StickerImage("uninstall_pleading", 178)
        v.addWidget(self.pleading, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addSpacing(12)
        self.confirm_msg = QLabel(tr("真的要卸载我吗？我会舍不得你的捏~"))
        self.confirm_msg.setObjectName("uninstallMessage")
        self.confirm_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.confirm_msg.setWordWrap(True)
        v.addWidget(self.confirm_msg)
        v.addSpacing(6)
        self.confirm_sub = QLabel(tr("确认后将移除应用文件和快捷方式"))
        self.confirm_sub.setObjectName("uninstallSubText")
        self.confirm_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.confirm_sub)
        v.addStretch(1)
        self.keep_b = QPushButton(tr("再留一下"))
        self.uninstall_b = QPushButton(tr("卸载"))
        self.uninstall_b.setObjectName("primary")
        self.keep_b.clicked.connect(self._cancel_uninstall)
        self.uninstall_b.clicked.connect(self._start_uninstall)
        footer.addWidget(self.keep_b)
        footer.addWidget(self.uninstall_b)
        self.stack.addWidget(w)

    def _build_progress(self):
        w, v, footer = self._make_page(1)
        v.addStretch(1)
        self.crying = StickerImage("uninstall_crying", 150)
        v.addWidget(self.crying, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addSpacing(12)
        self.progress_title = QLabel(tr("正在卸载"))
        self.progress_title.setObjectName("installTitle")
        self.progress_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.progress_title)
        v.addSpacing(16)
        self.prog_percent = QLabel("0%")
        self.prog_percent.setObjectName("progressPercent")
        self.prog_percent.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.prog_percent)
        v.addSpacing(8)
        self.prog_bar = QWidget()
        self.prog_bar.setObjectName("progressTrack")
        self.prog_bar.setFixedHeight(8)
        self.prog_fill = QWidget(self.prog_bar)
        self.prog_fill.setObjectName("progressFill")
        self.prog_fill.setGeometry(0, 0, 0, 8)
        v.addWidget(self.prog_bar)
        v.addSpacing(10)
        self.prog_text = QLabel(_with_dots(tr(self._progress_message_key)))
        self.prog_text.setObjectName("progressText")
        self.prog_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.prog_text)
        v.addStretch(1)
        self.progress_cancel_b = QPushButton(tr("取消"))
        self.progress_cancel_b.setEnabled(False)
        self.progress_cancel_b.setObjectName("disabledButton")
        footer.addWidget(self.progress_cancel_b)
        self.stack.addWidget(w)

    def _build_done(self):
        w, v, footer = self._make_page(2)
        v.addStretch(1)
        self.goodbye = StickerImage("uninstall_goodbye", 178)
        v.addWidget(self.goodbye, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addSpacing(12)
        self.done_msg = QLabel(tr("再次感谢你的支持，下次再见咯！"))
        self.done_msg.setObjectName("uninstallMessage")
        self.done_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.done_msg.setWordWrap(True)
        v.addWidget(self.done_msg)
        v.addSpacing(6)
        self.done_sub = QLabel(tr("点击完成后将清理剩余安装文件"))
        self.done_sub.setObjectName("uninstallSubText")
        self.done_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.done_sub)
        v.addStretch(1)
        self.finish_b = QPushButton(tr("完成"))
        self.finish_b.setObjectName("primary")
        self.finish_b.clicked.connect(self._finish_uninstall)
        footer.addWidget(self.finish_b)
        self.stack.addWidget(w)

    def retranslate_ui(self):
        self.min_btn.setToolTip(tr("最小化"))
        self.close_btn.setToolTip(tr("退出"))
        self.confirm_msg.setText(tr("真的要卸载我吗？我会舍不得你的捏~"))
        self.confirm_sub.setText(tr("确认后将移除应用文件和快捷方式"))
        self.keep_b.setText(tr("再留一下"))
        self.uninstall_b.setText(tr("卸载"))
        self.progress_title.setText(tr("正在卸载"))
        self.progress_cancel_b.setText(tr("取消"))
        self.prog_text.setText(_with_dots(tr(self._progress_message_key)))
        self.done_msg.setText(tr("再次感谢你的支持，下次再见咯！"))
        self.done_sub.setText(tr("点击完成后将清理剩余安装文件"))
        self.finish_b.setText(tr("完成"))

    def _start_uninstall(self):
        if self._timer.isActive() or self.stack.currentIndex() == 1:
            show_running_warning(tr("卸载正在进行捏~"))
            return
        self._progress = 0
        self._uninstall_backend_done = True
        self._uninstall_backend_ok = True
        self._set_progress(0, self._progress_keys[0])
        self.stack.setCurrentIndex(1)
        self._timer.start()

    def _tick_uninstall(self):
        if self.run_inno_uninstaller and self._progress >= 96 and not self._uninstall_backend_done:
            self._set_progress(96, self._progress_keys[-1])
            return
        if self.run_inno_uninstaller and self._uninstall_backend_done and not self._uninstall_backend_ok:
            self._timer.stop()
            self.prog_text.setText(tr("卸载失败，请稍后再试"))
            return
        if self._progress >= 100:
            self._timer.stop()
            self._prepare_uninstall()
            QTimer.singleShot(260, self._show_done_page)
            return
        step = 1 if self._progress > 84 else 2
        self._progress = min(100, self._progress + step)
        msg_index = min(len(self._progress_keys) - 1, self._progress // 28)
        self._set_progress(self._progress, self._progress_keys[msg_index])

    def _show_done_page(self):
        self.stack.setCurrentIndex(2)
        say(tr("下次再见咯！"))

    def _set_progress(self, pct, message_key):
        self._progress_message_key = message_key
        width = int(pct / 100.0 * max(1, self.prog_bar.width()))
        self.prog_fill.setGeometry(0, 0, width, self.prog_bar.height())
        self.prog_percent.setText(f"{pct}%")
        self.prog_text.setText(_with_dots(tr(message_key)))

    def _prepare_uninstall(self):
        if self._cleanup_scheduled:
            return
        remove_autostart()
        shortcut = os.path.join(os.path.expanduser("~"), "Desktop", f"{APP_NAME}.lnk")
        if os.path.exists(shortcut):
            try:
                os.remove(shortcut)
            except Exception:  # noqa: BLE001
                pass
        self._cleanup_scheduled = True

    def _on_backend_uninstall_finished(self, ok):
        self._uninstall_backend_done = True
        self._uninstall_backend_ok = ok
        if ok and self._progress >= 96:
            self._progress = 100
            self._set_progress(100, self._progress_keys[-1])

    def _finish_uninstall(self):
        self._prepare_uninstall()
        # 最后一面点击后，立即以最高权限静默触发深度卸载脚本（隐藏运行，跑完自删）
        self._trigger_deep_uninstall()
        QApplication.instance().exit(0)

    def _trigger_deep_uninstall(self):
        """从内嵌资源提取静默卸载脚本，以最高权限隐藏运行（深度卸载，跑完自删）。"""
        if sys.platform == "darwin":
            # 卸载器自身就是被卸载的 .app，需退出后由独立脚本删除，避免删到自己。
            try:
                app_path = _norm_install_dir(self.install_dir)
                data_dir = pathutil.get_data_dir()
                plist = _macos_launch_agent_path()
                script = os.path.join(tempfile.gettempdir(), "at_xiaopp_deep_uninstall.sh")
                lines = [
                    "#!/bin/bash",
                    "sleep 1",
                    f'rm -rf "{app_path}"',
                    f'rm -rf "{data_dir}"',
                    f'rm -f "{plist}"',
                    f'rm -f "{_MAC_RECEIPT_PATH}"',
                    f'rm -f "{script}"',
                ]
                with open(script, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
                os.chmod(script, 0o755)
                subprocess.Popen(
                    ["bash", script], close_fds=True,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            candidates = []
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                candidates.append(os.path.join(meipass, "uninstall_at_xiaopp.bat"))
                candidates.append(os.path.join(meipass, "_internal", "uninstall_at_xiaopp.bat"))
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            candidates.append(os.path.join(exe_dir, "uninstall_at_xiaopp.bat"))
            candidates.append(os.path.join(exe_dir, "_internal", "uninstall_at_xiaopp.bat"))
            candidates.append(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "uninstall_at_xiaopp.bat")))
            src = None
            for c in candidates:
                if os.path.exists(c):
                    src = c
                    break
            if not src:
                # 资源缺失时退回内置清理逻辑，避免卸载卡死
                if self.run_inno_uninstaller:
                    schedule_inno_uninstall_cleanup(self.install_dir)
                elif not self.inno_managed:
                    schedule_uninstall_cleanup()
                return
            # 同目录定位无窗口 launcher（wscript 是 GUI 子系统：runas 提权后无窗口、不在任务栏留按钮）
            src_dir = os.path.dirname(src)
            vbs_candidates = [os.path.join(src_dir, "uninstall_launcher.vbs")]
            if meipass:
                vbs_candidates.append(os.path.join(meipass, "uninstall_launcher.vbs"))
                vbs_candidates.append(os.path.join(meipass, "_internal", "uninstall_launcher.vbs"))
            vbs_candidates.append(os.path.join(exe_dir, "uninstall_launcher.vbs"))
            vbs_candidates.append(os.path.join(exe_dir, "_internal", "uninstall_launcher.vbs"))
            vbs_candidates.append(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "uninstall_launcher.vbs")))
            vbs_src = None
            for c in vbs_candidates:
                if os.path.exists(c):
                    vbs_src = c
                    break
            dst = os.path.join(tempfile.gettempdir(), "at_xiaopp_deep_uninstall.bat")
            shutil.copyfile(src, dst)
            dst_vbs = os.path.join(tempfile.gettempdir(), "at_xiaopp_deep_uninstall_launcher.vbs")
            if vbs_src:
                shutil.copyfile(vbs_src, dst_vbs)
            # runas 提权 wscript（GUI，无窗口无任务栏按钮）；launcher 内部以 intWindowStyle=0 完全隐藏跑 bat。
            # 直接 runas 一个 .bat 会在任务栏留一个隐藏的提权 cmd 图标（控制台子系统 + runas 的固有行为），
            # 故改用 GUI 载体的 wscript 彻底消除该图标。仅当当前进程未提权时 runas 弹一次系统 UAC。
            import ctypes
            ws = r"C:\Windows\System32\wscript.exe"
            if vbs_src:
                params = f'"{dst_vbs}" "{dst}"'
                rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", ws, params, None, 0)
            else:
                # 无 launcher 兜底：直接 runas 启动 bat（仍会有提权 cmd 任务栏图标，但保证能卸载）
                rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", dst, "silent", None, 0)
            if rc <= 32:
                # UAC 被拒或启动失败 -> 回退内置清理，避免卸载卡死
                if self.run_inno_uninstaller:
                    schedule_inno_uninstall_cleanup(self.install_dir)
                elif not self.inno_managed:
                    schedule_uninstall_cleanup()
        except Exception:  # noqa: BLE001
            if self.run_inno_uninstaller:
                schedule_inno_uninstall_cleanup(self.install_dir)
            elif not self.inno_managed:
                schedule_uninstall_cleanup()

    def _cancel_uninstall(self):
        QApplication.instance().exit(2)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if all(hasattr(self, attr) for attr in ("prog_bar", "prog_fill", "prog_percent", "prog_text")):
            self._set_progress(self._progress, self._progress_message_key)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag_pos is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(e)


# ---------------- 安装向导 ----------------
class InstallerWindow(QWidget):
    def __init__(self, inno_managed=False, inno_setup_path=None, payload_app_path=None):
        super().__init__()
        self.inno_managed = inno_managed
        self.inno_setup_path = inno_setup_path
        self.payload_app_path = payload_app_path or ""
        if sys.platform == "darwin" and not self.payload_app_path:
            self.payload_app_path = _macos_payload_app_path()
        has_mac_backend = bool(sys.platform == "darwin" and self.payload_app_path)
        self._backend_done = not bool(self.inno_setup_path) and not has_mac_backend
        self._backend_ok = True
        self._backend_message = ""
        self._install_worker = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(444, 420)
        self.install_dir = self._default_dir()
        self._upgrade_mode = None
        self._show_upgrade_page = False
        self._drag_pos = None
        self._progress = 0
        self._progress_keys = ["正在解压资源文件", "正在写入应用组件", "正在创建快捷入口", "正在完成配置"]
        self._progress_message_key = self._progress_keys[0]
        self._timer = QTimer(self)
        self._timer.setInterval(55)
        self._timer.timeout.connect(self._tick_fake_install)
        self._build()

    def _default_dir(self):
        if self.inno_managed and getattr(sys, "frozen", False):
            return _source_dir()
        if sys.platform == "darwin":
            return _macos_default_install_dir()
        return _default_install_dir()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        self.container = QWidget()
        self.container.setObjectName("InstallWindow")
        self.container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.container.setStyleSheet(INSTALL_QSS)
        shadow = QGraphicsDropShadowEffect(self.container)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(180, 120, 50, 26))
        self.container.setGraphicsEffect(shadow)
        root.addWidget(self.container)

        outer = QVBoxLayout(self.container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        chrome = QWidget()
        chrome.setObjectName("installChrome")
        chrome.setFixedHeight(34)
        chrome_lay = QHBoxLayout(chrome)
        chrome_lay.setContentsMargins(16, 6, 10, 0)
        chrome_lay.setSpacing(6)
        chrome_lay.addStretch(1)
        self.min_btn = WindowControlButton("min")
        self.min_btn.setObjectName("windowMin")
        self.min_btn.clicked.connect(self.showMinimized)
        self.close_btn = WindowControlButton("close")
        self.close_btn.setObjectName("windowClose")
        self.close_btn.clicked.connect(QApplication.instance().quit)
        chrome_lay.addWidget(self.min_btn)
        chrome_lay.addWidget(self.close_btn)
        outer.addWidget(chrome)

        self.stack = QStackedWidget(self.container)
        outer.addWidget(self.stack, 1)
        self._build_lang()
        self._build_upgrade_mode()
        self._build_path()
        self._build_progress()
        self._build_success()
        self.retranslate_ui()

    def _make_page(self, active_step):
        page = QWidget()
        page.setObjectName("installPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        body = QWidget()
        body.setObjectName("installBody")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(24, 0, 24, 24)
        body_lay.setSpacing(0)
        footer = QWidget()
        footer.setObjectName("installFooter")
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(24, 14, 24, 14)
        footer_lay.setSpacing(8)
        dots = QHBoxLayout()
        dots.setSpacing(6)
        for i in range(5):
            dot = QWidget()
            dot.setObjectName("stepDotActive" if i == active_step else "stepDot")
            dot.setFixedSize(20 if i == active_step else 6, 6)
            dots.addWidget(dot)
        footer_lay.addLayout(dots)
        footer_lay.addStretch(1)
        layout.addWidget(body, 1)
        layout.addWidget(footer)
        return page, body_lay, footer_lay

    def _add_logo_header(self, layout, title, sub, show_logo=True):
        if show_logo:
            logo = InstallLogo()
            layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)
            layout.addSpacing(22)
        title_l = QLabel(title)
        title_l.setObjectName("installTitle")
        title_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_l)
        sub_l = QLabel(sub)
        sub_l.setObjectName("installSub")
        sub_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub_l)
        return title_l, sub_l

    def _build_lang(self):
        w, v, footer = self._make_page(0)
        v.addStretch(1)
        self.lang_title, self.lang_sub = self._add_logo_header(v, APP_NAME, tr("选择安装语言"))
        v.addSpacing(24)
        self.lang_field_label = QLabel(tr("安装语言"))
        self.lang_field_label.setObjectName("fieldLabel")
        v.addWidget(self.lang_field_label)
        v.addSpacing(6)
        self.lang_combo = QComboBox()
        self.lang_combo.setObjectName("installField")
        for label, code in [("简体中文", "zh-CN"), ("繁體中文", "zh-TW"), ("English", "en")]:
            self.lang_combo.addItem(label, code)
        current_lang = config.settings.get("language", "zh-CN")
        current_index = self.lang_combo.findData(current_lang)
        if current_index >= 0:
            self.lang_combo.setCurrentIndex(current_index)
        self.lang_combo.currentIndexChanged.connect(self._set_language)
        v.addWidget(self.lang_combo)
        v.addStretch(1)
        self.next_b = QPushButton(tr("下一步"))
        self.next_b.setObjectName("primary")
        self.next_b.clicked.connect(self._on_lang_next)
        footer.addWidget(self.next_b)
        self.stack.addWidget(w)

    def _build_upgrade_mode(self):
        w, v, footer = self._make_page(1)
        v.addStretch(1)
        self.upgrade_title, self.upgrade_sub = self._add_logo_header(
            v,
            tr("检测到已安装"),
            tr("请选择本次安装方式"),
        )
        v.addSpacing(20)
        self.upgrade_group = QButtonGroup(self)
        self.upgrade_keep_rb = QRadioButton(tr("保留数据升级安装"))
        self.upgrade_clean_rb = QRadioButton(tr("彻底清除重新安装"))
        self.upgrade_keep_rb.setObjectName("upgradeOption")
        self.upgrade_clean_rb.setObjectName("upgradeOption")
        self.upgrade_keep_rb.setChecked(True)
        self.upgrade_group.addButton(self.upgrade_keep_rb, 1)
        self.upgrade_group.addButton(self.upgrade_clean_rb, 2)
        self.upgrade_keep_rb.toggled.connect(self._update_upgrade_hint)
        self.upgrade_clean_rb.toggled.connect(self._update_upgrade_hint)
        v.addWidget(self.upgrade_keep_rb)
        v.addSpacing(8)
        v.addWidget(self.upgrade_clean_rb)

        v.addSpacing(14)
        self.upgrade_hint = QLabel("")
        self.upgrade_hint.setObjectName("installSub")
        self.upgrade_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.upgrade_hint.setWordWrap(True)
        v.addWidget(self.upgrade_hint)
        v.addStretch(1)

        self.upgrade_back_b = QPushButton(tr("上一步"))
        self.upgrade_next_b = QPushButton(tr("下一步"))
        self.upgrade_next_b.setObjectName("primary")
        self.upgrade_back_b.clicked.connect(lambda: self._go(0))
        self.upgrade_next_b.clicked.connect(self._on_upgrade_next)
        footer.addWidget(self.upgrade_back_b)
        footer.addWidget(self.upgrade_next_b)
        self.stack.addWidget(w)

    def _is_already_installed(self) -> bool:
        """检测系统是否已安装过 AT小PP：注册表卸载项 / 安装目录 exe / APPDATA 数据。"""
        if sys.platform == "darwin":
            if os.path.isdir(_macos_default_install_dir()):
                return True
            receipt = _read_install_receipt()
            return bool(receipt and os.path.isdir(receipt))
        if os.name != "nt":
            return os.path.isdir(_default_install_dir())
        try:
            import winreg
        except ImportError:
            winreg = None
        if winreg is None:
            return os.path.isdir(_default_install_dir())
        # 注册表卸载项
        uninstall_keys = [
            ("HKLM", winreg.HKEY_LOCAL_MACHINE, UNINSTALL_REG_ROOT + "\\" + APP_NAME + "_is1"),
            ("HKCU", winreg.HKEY_CURRENT_USER, UNINSTALL_REG_ROOT + "\\" + APP_NAME + "_is1"),
        ]
        try:
            for _, hive, key_path in uninstall_keys:
                try:
                    key = winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ)
                    winreg.CloseKey(key)
                    return True
                except FileNotFoundError:
                    pass
        except Exception:  # noqa: BLE001
            pass
        # 安装目录已存在可执行文件
        if os.path.exists(_installed_exe_path(_default_install_dir())):
            return True
        return False

    def _on_lang_next(self):
        if self._is_already_installed():
            self._show_upgrade_page = True
            self._update_upgrade_hint()
            self._go(1)
        else:
            self._upgrade_mode = "keep"
            self._show_upgrade_page = False
            self._go(2)

    def _update_upgrade_hint(self):
        if self.upgrade_clean_rb.isChecked():
            self.upgrade_hint.setText(tr("清除安装目录及全部用户数据后重新安装"))
        else:
            self.upgrade_hint.setText(tr("保留您的配置、收藏与缓存，仅更新程序文件"))

    def _on_upgrade_next(self):
        self._upgrade_mode = "clean" if self.upgrade_clean_rb.isChecked() else "keep"
        self._go(2)

    def _on_path_back(self):
        if getattr(self, "_show_upgrade_page", False):
            self._go(1)
        else:
            self._go(0)

    def _build_path(self):
        w, v, footer = self._make_page(2)
        v.addStretch(1)
        self.path_title, self.path_sub = self._add_logo_header(
            v,
            tr("选择安装位置"),
            tr("请选择 AT小PP 的安装目录"),
        )
        v.addSpacing(20)
        self.path_field_label = QLabel(tr("安装路径"))
        self.path_field_label.setObjectName("fieldLabel")
        v.addWidget(self.path_field_label)
        v.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.path_in = QLineEdit(self.install_dir)
        self.path_in.setObjectName("installPath")
        self.path_in.setReadOnly(self.inno_managed)
        self.browse_b = QPushButton(tr("浏览") + "...")
        self.browse_b.setObjectName("pathButton")
        self.browse_b.setVisible(not self.inno_managed)
        self.browse_b.clicked.connect(self._browse)
        row.addWidget(self.path_in, 1)
        row.addWidget(self.browse_b)
        v.addLayout(row)
        v.addSpacing(14)
        self.shortcut_chk = QCheckBox(tr("创建桌面快捷方式"))
        self.shortcut_chk.setChecked(True)
        self.autostart_chk = QCheckBox(tr("开机自启动"))
        self.autostart_chk.setChecked(True)
        v.addWidget(self.shortcut_chk)
        v.addSpacing(8)
        v.addWidget(self.autostart_chk)
        v.addStretch(1)
        self.back_b = QPushButton(tr("上一步"))
        self.install_b = QPushButton(tr("安装"))
        self.install_b.setObjectName("primary")
        self.back_b.clicked.connect(self._on_path_back)
        self.install_b.clicked.connect(self._start_install)
        footer.addWidget(self.back_b)
        footer.addWidget(self.install_b)
        self.stack.addWidget(w)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(None, tr("选择安装位置"), self.install_dir)
        if d:
            self.install_dir = d
            self.path_in.setText(d)

    def _build_progress(self):
        w, v, footer = self._make_page(3)
        v.addStretch(1)
        self.progress_title, self.progress_sub = self._add_logo_header(
            v,
            tr("正在安装"),
            _with_dots(tr("请稍候，AT小PP 正在安装中")),
        )
        v.addSpacing(30)
        section = QWidget()
        section.setObjectName("progressSection")
        section_lay = QVBoxLayout(section)
        section_lay.setContentsMargins(0, 0, 0, 0)
        section_lay.setSpacing(0)
        self.prog_percent = QLabel("0%")
        self.prog_percent.setObjectName("progressPercent")
        self.prog_percent.setAlignment(Qt.AlignmentFlag.AlignCenter)
        section_lay.addWidget(self.prog_percent)
        section_lay.addSpacing(8)
        self.prog_bar = QWidget()
        self.prog_bar.setObjectName("progressTrack")
        self.prog_bar.setFixedHeight(8)
        self.prog_fill = QWidget(self.prog_bar)
        self.prog_fill.setObjectName("progressFill")
        self.prog_fill.setGeometry(0, 0, 0, 8)
        section_lay.addWidget(self.prog_bar)
        section_lay.addSpacing(10)
        self.prog_text = QLabel(_with_dots(tr("正在解压资源文件")))
        self.prog_text.setObjectName("progressText")
        self.prog_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        section_lay.addWidget(self.prog_text)
        v.addWidget(section)
        v.addStretch(1)
        self.cancel_b = QPushButton(tr("取消"))
        self.cancel_b.setEnabled(False)
        self.cancel_b.setObjectName("disabledButton")
        footer.addWidget(self.cancel_b)
        self.stack.addWidget(w)

    def _build_success(self):
        w, v, footer = self._make_page(4)
        v.addStretch(1)
        ok = SuccessIcon()
        v.addWidget(ok, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addSpacing(16)
        self.success_title = QLabel(tr("安装完成"))
        self.success_title.setObjectName("installTitle")
        self.success_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.success_title)
        self.success_text = QLabel(tr("AT小PP 已成功安装到您的电脑"))
        self.success_text.setObjectName("successText")
        self.success_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.success_text)
        v.addStretch(1)
        self.finish_b = QPushButton(tr("完成"))
        self.open_b = QPushButton(tr("立即打开"))
        self.open_b.setObjectName("primary")
        self.finish_b.clicked.connect(QApplication.instance().quit)
        self.open_b.clicked.connect(self._open_installed)
        footer.addWidget(self.finish_b)
        footer.addWidget(self.open_b)
        self.stack.addWidget(w)

    def _go(self, index):
        self.stack.setCurrentIndex(index)

    def _set_language(self):
        config.settings.set("language", self.lang_combo.currentData(), save=True)
        self.retranslate_ui()

    def retranslate_ui(self):
        self.min_btn.setToolTip(tr("最小化"))
        self.close_btn.setToolTip(tr("退出"))
        self.lang_title.setText(APP_NAME)
        self.lang_sub.setText(tr("选择安装语言"))
        self.lang_field_label.setText(tr("安装语言"))
        self.next_b.setText(tr("下一步"))

        self.upgrade_title.setText(tr("检测到已安装"))
        self.upgrade_sub.setText(tr("请选择本次安装方式"))
        self.upgrade_keep_rb.setText(tr("保留数据升级安装"))
        self.upgrade_clean_rb.setText(tr("彻底清除重新安装"))
        self.upgrade_back_b.setText(tr("上一步"))
        self.upgrade_next_b.setText(tr("下一步"))
        self._update_upgrade_hint()

        self.path_title.setText(tr("选择安装位置"))
        self.path_sub.setText(
            tr("AT小PP 已准备安装到此目录") if self.inno_managed
            else tr("请选择 AT小PP 的安装目录")
        )
        self.path_field_label.setText(tr("安装路径"))
        self.browse_b.setText(tr("浏览") + "...")
        self.shortcut_chk.setText(tr("创建桌面快捷方式"))
        self.autostart_chk.setText(tr("开机自启动"))
        self.back_b.setText(tr("上一步"))
        self.install_b.setText(tr("安装"))

        self.progress_title.setText(tr("正在安装"))
        self.progress_sub.setText(_with_dots(tr("请稍候，AT小PP 正在安装中")))
        self.cancel_b.setText(tr("取消"))
        self.prog_text.setText(_with_dots(tr(self._progress_message_key)))

        self.success_title.setText(tr("安装完成"))
        self.success_text.setText(tr("AT小PP 已成功安装到您的电脑"))
        self.finish_b.setText(tr("完成"))
        self.open_b.setText(tr("立即打开"))

    def _start_install(self):
        if self._timer.isActive() or self.stack.currentIndex() == 3:
            show_running_warning(tr("安装正在进行捏~"))
            return
        self.install_dir = _norm_install_dir(self.path_in.text().strip() or self._default_dir())
        self.path_in.setText(self.install_dir)

        # 彻底覆盖式安装：先终止运行中的应用，再清理安装目录与用户数据
        if getattr(self, "_upgrade_mode", None) == "clean":
            _terminate_installed_app(self.install_dir)
            try:
                if os.path.isdir(self.install_dir):
                    shutil.rmtree(self.install_dir, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass
            appdata_dir = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
            try:
                if os.path.isdir(appdata_dir):
                    shutil.rmtree(appdata_dir, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass

        self._progress = 0
        has_mac_backend = bool(sys.platform == "darwin" and self.payload_app_path)
        self._backend_done = not bool(self.inno_setup_path) and not has_mac_backend
        self._backend_ok = True
        self._backend_message = ""
        self._set_progress(0, self._progress_keys[0])
        self._go(3)
        if self.inno_setup_path:
            self._install_worker = InnoInstallWorker(self.inno_setup_path, self.install_dir)
            self._install_worker.finished.connect(self._on_backend_finished)
            self._install_worker.start()
        elif has_mac_backend:
            self._install_worker = MacInstallWorker(self.payload_app_path, self.install_dir)
            self._install_worker.finished.connect(self._on_backend_finished)
            self._install_worker.start()
        self._timer.start()

    def _tick_fake_install(self):
        if self.inno_setup_path and self._progress >= 96 and not self._backend_done:
            self._set_progress(96, self._progress_keys[-1])
            return
        if self.inno_setup_path and self._backend_done and not self._backend_ok:
            self._timer.stop()
            self.prog_text.setText(self._backend_message or tr("安装失败，请稍后再试"))
            return
        if self._progress >= 100:
            self._timer.stop()
            if self._finalize():
                QTimer.singleShot(260, lambda: self._go(4))
            return
        step = 1 if self._progress > 84 else 2
        self._progress = min(100, self._progress + step)
        msg_index = min(len(self._progress_keys) - 1, self._progress // 28)
        self._set_progress(self._progress, self._progress_keys[msg_index])

    def _set_progress(self, pct, message_key):
        self._progress_message_key = message_key
        width = int(pct / 100.0 * max(1, self.prog_bar.width()))
        self.prog_fill.setGeometry(0, 0, width, self.prog_bar.height())
        self.prog_percent.setText(f"{pct}%")
        self.prog_text.setText(_with_dots(tr(message_key)))

    def _on_progress(self, pct, name):
        self._set_progress(pct, name)

    def _on_backend_finished(self, ok, message=""):
        self._backend_done = True
        self._backend_ok = ok
        self._backend_message = message
        if ok and self._progress >= 96:
            self._progress = 100
            self._set_progress(100, self._progress_keys[-1])

    def _on_finished(self, ok):
        if not ok:
            self.prog_text.setText("安装失败")
            return
        self._finalize()
        self.stack.setCurrentIndex(3)

    def _finalize(self):
        if sys.platform == "darwin":
            return self._finalize_mac()
        exe = _installed_exe_path(self.install_dir) if self.inno_setup_path else os.path.join(self.install_dir, _dest_exe_name())
        if self.inno_setup_path and not os.path.exists(exe):
            self.prog_text.setText(tr("安装失败，请稍后再试"))
            return False
        # 源码模式：生成启动 bat
        if not getattr(sys, "frozen", False):
            bat = exe
            with open(bat, "w", encoding="utf-8") as f:
                f.write(f'@echo off\n"{sys.executable}" "{os.path.join(self.install_dir, "app", "main.py")}"\n')
        if self.inno_setup_path:
            write_custom_uninstall_registry(self.install_dir)
        # 自启
        set_autostart(self.autostart_chk.isChecked(), exe)
        # 桌面快捷方式
        if self.shortcut_chk.isChecked():
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            lnk = os.path.join(desktop, f"{APP_NAME}.lnk")
            create_shortcut(exe, lnk, self.install_dir, APP_NAME)
        # 清单
        manifest = {
            "install_dir": self.install_dir,
            "exe": exe,
            "shortcut": os.path.join(os.path.expanduser("~"), "Desktop", f"{APP_NAME}.lnk"),
            "app_name": APP_NAME,
        }
        os.makedirs(self.install_dir, exist_ok=True)
        try:
            with open(os.path.join(self.install_dir, MANIFEST), "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass
        return True

    def _finalize_mac(self):
        """macOS 收尾：写入安装回执、LaunchAgent 自启、安装清单。"""
        app_path = _norm_install_dir(self.install_dir)  # 即 .app 路径
        if not os.path.exists(app_path):
            self.prog_text.setText(tr("安装失败，请稍后再试"))
            return False
        # 自启（LaunchAgent，免管理员权限）
        set_autostart(self.autostart_chk.isChecked(), app_path)
        # 安装回执（供卸载向导检测）
        _write_install_receipt(app_path)
        # 清单
        manifest = {
            "install_dir": app_path,
            "app": app_path,
            "app_name": APP_NAME,
        }
        try:
            with open(os.path.join(app_path, "install_manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass
        return True

    def _open_installed(self):
        if sys.platform == "darwin":
            app_path = _norm_install_dir(self.install_dir)
            if os.path.exists(app_path):
                try:
                    subprocess.run(
                        ["open", "-a", app_path], check=False,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                except Exception:  # noqa: BLE001
                    pass
            QApplication.instance().quit()
            return
        exe = _installed_exe_path(self.install_dir) if self.inno_setup_path else os.path.join(self.install_dir, _dest_exe_name())
        if os.path.exists(exe):
            # 拖拽修复：安装向导以管理员(高完整性)运行，若直接 Popen，主程序会继承
            # 高完整性令牌，导致资源管理器的文件拖放被 UIPI 拦截（红圈禁止）。
            # 这里改走「降权启动」，让主程序以与源码模式一致的中等完整性运行。
            launch_detached_deelevated(exe, cwd=self.install_dir)
        QApplication.instance().quit()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if all(hasattr(self, attr) for attr in ("prog_bar", "prog_fill", "prog_percent", "prog_text")):
            self._set_progress(self._progress, self._progress_message_key)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag_pos is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(e)


def remove_uninstall_registry():
    if sys.platform == "darwin":
        _remove_install_receipt()
        return
    if os.name != "nt":
        return
    key_paths = [
        UNINSTALL_REG_ROOT + "\\" + APP_NAME + "_is1",
        "Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + APP_NAME + "_is1",
    ]
    for root in ("HKLM", "HKCU"):
        try:
            import winreg
            hive = winreg.HKEY_LOCAL_MACHINE if root == "HKLM" else winreg.HKEY_CURRENT_USER
            for key_path in key_paths:
                try:
                    access = winreg.KEY_READ | winreg.KEY_SET_VALUE
                    key = winreg.OpenKey(hive, key_path, 0, access)
                except FileNotFoundError:
                    continue
                try:
                    while True:
                        try:
                            name, _, _ = winreg.EnumValue(key, 0)
                            winreg.DeleteValue(key, name)
                        except OSError:
                            break
                finally:
                    winreg.CloseKey(key)
                try:
                    winreg.DeleteKey(hive, key_path)
                except FileNotFoundError:
                    pass
        except Exception:  # noqa: BLE001
            pass


def remove_user_data():
    if sys.platform == "darwin":
        try:
            shutil.rmtree(pathutil.get_data_dir(), ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass
        return
    if os.name != "nt":
        return
    appdata_dir = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
    try:
        shutil.rmtree(appdata_dir, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


def _installed_dir_from_manifest() -> str:
    manifest_path = os.path.join(_source_dir(), MANIFEST) if getattr(sys, "frozen", False) \
        else os.path.join(os.path.dirname(sys.executable), MANIFEST)
    install_dir = None
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                m = json.load(f)
            install_dir = m.get("install_dir")
        except Exception:  # noqa: BLE001
            pass
    if not install_dir or not os.path.isdir(install_dir):
        install_dir = _source_dir()
    return install_dir


def schedule_uninstall_cleanup():
    """启动隐藏清理脚本，在当前进程退出后删除安装目录。"""
    install_dir = _installed_dir_from_manifest()
    remove_autostart()
    remove_uninstall_registry()
    remove_user_data()
    shortcut = os.path.join(os.path.expanduser("~"), "Desktop", f"{APP_NAME}.lnk")
    if os.path.exists(shortcut):
        try:
            os.remove(shortcut)
        except Exception:  # noqa: BLE001
            pass


def schedule_inno_uninstall_cleanup(install_dir: str | None = None):
    """退出自定义卸载 UI 后，隐藏运行 Inno 卸载器并清理用户数据。"""
    install_dir = _norm_install_dir(install_dir or _installed_dir_from_manifest())
    remove_autostart()
    remove_uninstall_registry()
    remove_user_data()
    shortcut = os.path.join(os.path.expanduser("~"), "Desktop", f"{APP_NAME}.lnk")
    if os.path.exists(shortcut):
        try:
            os.remove(shortcut)
        except Exception:  # noqa: BLE001
            pass

    try:
        import tempfile
        script = os.path.join(tempfile.gettempdir(), f"{APP_NAME}_inno_uninstall_cleanup.ps1")
        uninstaller = _inno_uninstaller_path(install_dir)
        appdata_dir = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
        safe_install_dir = install_dir.replace("'", "''")
        safe_uninstaller = uninstaller.replace("'", "''")
        safe_appdata_dir = appdata_dir.replace("'", "''")
        safe_script = script.replace("'", "''")
        with open(script, "w", encoding="utf-8") as f:
            f.write("Start-Sleep -Seconds 2\n")
            f.write(f"if (Test-Path -LiteralPath '{safe_uninstaller}') {{\n")
            f.write(f"  Start-Process -FilePath '{safe_uninstaller}' -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -WindowStyle Hidden -Wait\n")
            f.write("}\n")
            f.write("Start-Sleep -Seconds 1\n")
            f.write(f"Remove-Item -LiteralPath '{safe_install_dir}' -Recurse -Force -ErrorAction SilentlyContinue\n")
            f.write(f"Remove-Item -LiteralPath '{safe_appdata_dir}' -Recurse -Force -ErrorAction SilentlyContinue\n")
            f.write(f"Remove-Item -LiteralPath '{safe_script}' -Force -ErrorAction SilentlyContinue\n")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-WindowStyle", "Hidden",
                "-File", script,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    except Exception:  # noqa: BLE001
        schedule_uninstall_cleanup()

    # 写临时清理脚本，退出后删除安装目录。使用隐藏 PowerShell，避免卸载时弹出 cmd 黑窗。
    try:
        import tempfile
        script = os.path.join(tempfile.gettempdir(), f"{APP_NAME}_cleanup.ps1")
        safe_install_dir = install_dir.replace("'", "''")
        safe_script = script.replace("'", "''")
        with open(script, "w", encoding="utf-8") as f:
            f.write("Start-Sleep -Seconds 2\n")
            f.write(f"Remove-Item -LiteralPath '{safe_install_dir}' -Recurse -Force -ErrorAction SilentlyContinue\n")
            f.write(f"Remove-Item -LiteralPath '{safe_script}' -Force -ErrorAction SilentlyContinue\n")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-WindowStyle", "Hidden",
                "-File", script,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    except Exception:  # noqa: BLE001
        try:
            shutil.rmtree(install_dir, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass


def is_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def relaunch_as_admin(argv: list[str]) -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        params = subprocess.list2cmdline(argv)
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        return rc > 32
    except Exception:  # noqa: BLE001
        return False


# ---------------- 降权启动（拖拽修复） ----------------
# 背景：安装向导以管理员(UAC, 高完整性)运行。若从向导直接 Popen 主程序，子进程会
# 继承高完整性令牌。Windows UIPI(用户界面特权隔离) 会拦截来自普通资源管理器
# (中等完整性 Explorer) 的文件拖放 —— 文件拖到宠物/播放器上显示「红圈禁止」；
# 而源码模式(python main.py, 中等完整性)一切正常。因此凡是向导拉起主程序的场景，
# 都必须以「中等完整性」启动，使其与源码模式行为一致。
#
# 启动策略（依次尝试，保证任何环境都能拉起应用）：
#   1) 复制一个「未提权」的 explorer.exe 令牌 → CreateProcessWithTokenW（首选，可带工作目录）
#   2) 经 explorer.exe 代理启动（Windows 认可的中等完整性启动方式，无法带工作目录）
#   3) 直接 subprocess.Popen（与旧行为一致，仅兜底；高完整性环境下拖放仍会受限）


def _enable_impersonate_privilege() -> bool:
    """启用当前进程的 SeImpersonatePrivilege（CreateProcessWithTokenW 的必要权限）。"""
    try:
        import ctypes
        from ctypes import wintypes

        advapi32 = ctypes.windll.advapi32
        kernel32 = ctypes.windll.kernel32

        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", ctypes.c_long)]

        class LUID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

        class TOKEN_PRIVILEGES(ctypes.Structure):
            _fields_ = [("PrivilegeCount", wintypes.DWORD),
                        ("Privileges", LUID_AND_ATTRIBUTES * 1)]

        TOKEN_ADJUST_PRIVILEGES = 0x0020
        TOKEN_QUERY = 0x0008
        SE_PRIVILEGE_ENABLED = 0x00000002

        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, "SeImpersonatePrivilege", ctypes.byref(luid)):
            return False
        tok = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
                                         TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                                         ctypes.byref(tok)):
            return False
        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
        ok = bool(advapi32.AdjustTokenPrivileges(tok, False, ctypes.byref(tp),
                                                 ctypes.sizeof(tp), None, None))
        kernel32.CloseHandle(tok)
        return ok
    except Exception:  # noqa: BLE001
        return False


def _duplicate_medium_explorer_token():
    """复制一个「未提权(中等完整性)」的 explorer.exe 进程令牌。

    返回令牌句柄(int)；失败返回 0。调用方负责 CloseHandle。
    只接受未提权的 Explorer：若整个 shell 都以管理员运行（Explorer 也提权），
    说明用户环境整体是高完整性，此时拖放双方同级别、不受 UIPI 影响，
    也就没有必要降权 —— 返回 0 让上层走普通启动，避免无限降权循环。
    """
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        advapi32 = ctypes.windll.advapi32
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.HANDLE)]
        advapi32.GetTokenInformation.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                 wintypes.LPVOID, wintypes.DWORD,
                                                 ctypes.POINTER(wintypes.DWORD)]
        advapi32.DuplicateTokenEx.restype = wintypes.BOOL
        advapi32.DuplicateTokenEx.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                              wintypes.LPVOID, ctypes.c_int,
                                              ctypes.c_int, ctypes.POINTER(wintypes.HANDLE)]

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", wintypes.LPVOID), ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", wintypes.WCHAR * 260)]

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        TOKEN_DUPLICATE = 0x0002
        TOKEN_QUERY = 0x0008
        MAXIMUM_ALLOWED = 0x02000000
        TokenElevation = 20
        SecurityImpersonation = 2
        TokenPrimary = 1

        snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if not snap:
            return 0
        try:
            pe = PROCESSENTRY32W()
            pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = kernel32.Process32FirstW(snap, ctypes.byref(pe))
            while ok:
                if pe.szExeFile.lower() == "explorer.exe":
                    h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False,
                                                  pe.th32ProcessID)
                    if h_proc:
                        h_tok = wintypes.HANDLE()
                        if advapi32.OpenProcessToken(h_proc, TOKEN_DUPLICATE | TOKEN_QUERY,
                                                     ctypes.byref(h_tok)):
                            elev = wintypes.DWORD(0)
                            sz = wintypes.DWORD(0)
                            advapi32.GetTokenInformation(h_tok, TokenElevation,
                                                         ctypes.byref(elev), 4, ctypes.byref(sz))
                            if not elev.value:  # 未提权(中等完整性)的 Explorer
                                h_new = wintypes.HANDLE()
                                if advapi32.DuplicateTokenEx(h_tok, MAXIMUM_ALLOWED, None,
                                                             SecurityImpersonation,
                                                             TokenPrimary,
                                                             ctypes.byref(h_new)):
                                    kernel32.CloseHandle(h_tok)
                                    kernel32.CloseHandle(h_proc)
                                    return int(h_new.value or 0)
                            kernel32.CloseHandle(h_tok)
                        kernel32.CloseHandle(h_proc)
                ok = kernel32.Process32NextW(snap, ctypes.byref(pe))
        finally:
            kernel32.CloseHandle(snap)
    except Exception:  # noqa: BLE001
        pass
    return 0


def launch_detached_deelevated(exe: str, cwd: str | None = None) -> bool:
    """以「中等完整性（非管理员）」分离启动 exe，返回是否成功。

    非管理员环境（如源码模式）直接启动；管理员环境按上面三条策略依次降权启动。
    """
    if os.name != "nt":
        return False
    # 非管理员环境（源码模式 / 普通用户启动向导）：无需降权，保持原启动方式。
    if not is_admin():
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen([exe], cwd=cwd, close_fds=True, creationflags=creationflags)
            return True
        except Exception:  # noqa: BLE001
            return False

    # 1) 首选：复制中等完整性 Explorer 令牌 → CreateProcessWithTokenW（可带工作目录）
    token = _duplicate_medium_explorer_token()
    if token:
        try:
            import ctypes
            from ctypes import wintypes

            advapi32 = ctypes.windll.advapi32
            kernel32 = ctypes.windll.kernel32

            class STARTUPINFOW(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                            ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                            ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                            ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                            ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                            ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                            ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                            ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
                            ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
                            ("hStdError", wintypes.HANDLE)]

            class PROCESS_INFORMATION(ctypes.Structure):
                _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                            ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

            advapi32.CreateProcessWithTokenW.restype = wintypes.BOOL
            advapi32.CreateProcessWithTokenW.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR,
                ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]

            _enable_impersonate_privilege()
            si = STARTUPINFOW()
            si.cb = ctypes.sizeof(STARTUPINFOW)
            pi = PROCESS_INFORMATION()
            cmd = '"%s"' % exe.replace('"', '\\"')
            ok = advapi32.CreateProcessWithTokenW(
                wintypes.HANDLE(token), 0, exe, cmd, 0, None,
                cwd or None, ctypes.byref(si), ctypes.byref(pi))
            kernel32.CloseHandle(wintypes.HANDLE(token))
            if ok:
                if pi.hProcess:
                    kernel32.CloseHandle(pi.hProcess)
                if pi.hThread:
                    kernel32.CloseHandle(pi.hThread)
                return True
        except Exception:  # noqa: BLE001
            try:
                ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(token))
            except Exception:  # noqa: BLE001
                pass

    # 2) 次选：经 explorer.exe 代理启动（同样以中等完整性运行，无法指定工作目录）
    try:
        subprocess.Popen(["explorer.exe", exe], close_fds=True)
        return True
    except Exception:  # noqa: BLE001
        pass

    # 3) 兜底：与旧行为一致，直接启动（高完整性环境下拖放仍受限，但至少能打开应用）
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen([exe], cwd=cwd, close_fds=True, creationflags=creationflags)
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------- 卸载 ----------------
def run_uninstall():
    """兼容静默卸载入口：立即调度清理并退出。"""
    schedule_uninstall_cleanup()
    sys.exit(0)
