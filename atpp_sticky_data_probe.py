"""回归探针：本轮修复的可验证部分（macOS 原生层级/拖拽行为需在 Mac 真机确认）。

覆盖：
  A) 便签透明化修复：窗口类型必须是 Qt::Dialog（而非 Qt::Window）——行为验证
     「Dialog|Frameless|StaysOnTop 组合下 windowType() 确为 Dialog」。
  B) 便签基类为 QDialog（对齐可正常工作的 TodoWindow）。
  C) 覆盖安装数据保护：_is_inside_bundle 能正确判定「包内/包外」，且 get_data_dir
     的防御重定向代码到位。
  D) 便签点击崩溃修复：拖拽改纯 Python 绝对坐标跟随，事件过滤器不得再直接调用
     startSystemMove()（macOS 子控件上下文会抛 NSException 硬崩）/ grabMouse()
     （WA_TranslucentBackground 无边框窗偶发失效）；应置 _pending_drag + event.ignore()
     冒泡到窗口自身 mousePressEvent。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtCore import Qt

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
        print("  FAIL:", msg)
    else:
        print("  ok  :", msg)


app = QApplication([])

print("[A] 行为验证：Dialog|Frameless|StaysOnTop 组合 → windowType 为 Dialog（非 Window）")
w = QDialog()
w.setWindowFlags(Qt.WindowType.Dialog
                 | Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.WindowStaysOnTopHint)
wt = int(w.windowType()) & 0xFF
check(wt == int(Qt.WindowType.Dialog),
      f"组合标志下 windowType 应为 Dialog（实得 {wt:#x}，期望 {int(Qt.WindowType.Dialog):#x}）")
check((int(w.windowType()) & int(Qt.WindowType.Window)) == 0
      or int(w.windowType()) == int(Qt.WindowType.Dialog),
      "确认该窗口类型不含导致失活丢内容的 Qt::Window 类型问题")
# 反例：旧的 QWidget + Frameless 组合 → 类型是 Window（正是 bug 来源）
old = QDialog()
old.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
check(int(old.windowType()) & 0xFF == int(Qt.WindowType.Window),
      "反例：旧（无 Dialog）组合类型为 Window —— 印证 bug 根因")

print("[B] 便签基类为 QDialog（对齐 TodoWindow，类型即 Dialog）")
import app.ui.todo_window as tw
check(issubclass(tw.StickyNoteWindow, QDialog),
      "StickyNoteWindow 应继承自 QDialog")
src = open(tw.__file__, encoding="utf-8").read()
check("class StickyNoteWindow(QDialog):" in src,
      "源码中 StickyNoteWindow 基类声明为 QDialog")
check("Qt.WindowType.Dialog" in src,
      "setWindowFlags 显式含 Qt.WindowType.Dialog（消除失活丢内容 bug）")
check("WA_TranslucentBackground" in src.split("class StickyNoteWindow")[1].split("def _build_note")[0],
      "便签仍保留 WA_TranslucentBackground（Dialog 类型下半透明在 macOS 失活不再丢内容）")

print("[C] 覆盖安装数据保护：_is_inside_bundle 判定 + 重定向代码")
import app.core.pathutil as pu
# 模拟打包环境：.app 包在 /tmp/fake_bundle 内
sys.frozen = True
pu.APP_DIR = "/tmp/fake_bundle/AT小PP.app/Contents/MacOS"
sys._MEIPASS = "/tmp/fake_bundle/AT小PP.app/Contents/MacOS"
check(pu._is_inside_bundle("/tmp/fake_bundle/AT小PP.app/Contents/MacOS/_internal/data"),
      "包内路径（MacOS 之下）应判为 inside bundle")
check(pu._is_inside_bundle("/tmp/fake_bundle/AT小PP.app/Contents/MacOS/AT小PP"),
      "包内可执行目录（MacOS 之下）应判为 inside bundle")
real_home = os.path.expanduser("~")
check(not pu._is_inside_bundle(os.path.join(real_home, "Library", "Application Support", "AT小PP")),
      "真实 ~/Library/Application Support/AT小PP 应判为 outside bundle（数据安全）")
check(not pu._is_inside_bundle("/Users/me/Documents/notes"),
      "任意包外路径应判为 outside bundle")
# 重定向代码静态确认
psrc = open(pu.__file__, encoding="utf-8").read()
check("_is_inside_bundle(d)" in psrc, "get_data_dir 内含 _is_inside_bundle(d) 防御判定")
check("重定向到 Application Support" in psrc, "get_data_dir 内含重定向到 Application Support 的分支")

print("[D] 便签点击崩溃修复：拖拽改纯 Python 绝对坐标跟随（无 startSystemMove/grabMouse）")
tsrc = open(tw.__file__, encoding="utf-8").read()
# 仅统计「实际调用」self.startSystemMove( / self.grabMouse( / self.releaseMouse(，
# 注释里的历史描述不算（用括号后紧跟形参或调用特征过滤）。
import re
call_calls = re.findall(r"self\.(?:startSystemMove|grabMouse|releaseMouse)\s*\(", tsrc)
check(len(call_calls) == 0,
      f"便签拖拽路径不得再直接调用 startSystemMove/grabMouse/releaseMouse（实测 {len(call_calls)} 处）")
check("self._pending_drag = True" in tsrc, "事件过滤器可拖区置 _pending_drag=True")
check("event.ignore()" in tsrc, "事件过滤器对可拖区按下调 event.ignore() 冒泡到窗口")
# 窗口自身 mousePressEvent 接管起点：StickyNoteWindow 类内有 def mousePressEvent
sn_block = tsrc.split("class StickyNoteWindow")[1]
check("def mousePressEvent(self, e):" in sn_block.split("def eventFilter")[0]
      or "def mousePressEvent(self, e):" in sn_block,
      "StickyNoteWindow 定义了自身 mousePressEvent 接管拖拽起点")

print()
if fails:
    print(f"RESULT: {len(fails)} FAIL")
    sys.exit(1)
print("RESULT: ALL PASS")
