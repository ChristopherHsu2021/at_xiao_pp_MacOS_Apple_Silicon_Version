"""回归探针：本轮修复的可验证部分（macOS 原生层级/拖拽行为需在 Mac 真机确认）。

覆盖：
  A) 便签透明化修复：窗口类型必须是 Qt::Dialog（而非 Qt::Window）——行为验证
     「Dialog|Frameless|StaysOnTop 组合下 windowType() 确为 Dialog」。
  B) 便签基类为 QDialog（对齐可正常工作的 TodoWindow）。
  C) 覆盖安装数据保护：_is_inside_bundle 能正确判定「包内/包外」，且 get_data_dir
     的防御重定向代码到位。
  D) 便签结构重写（第三次返工）：卡片不再经 QGraphicsView/QGraphicsProxyWidget 代理
     承载 —— 代理层在 macOS 上会让内嵌控件的**不透明实底被合成成半透明**、且鼠标事件
     经「视图→场景→代理」三级路由后丢失（→ 透明 + 点不动 + 拖不动）。现与 TodoWindow
     同构：窗口根布局 → 不透明实底 QWidget(self.note) → 普通子控件层级。
  D2) 行为验证：合成鼠标事件证明「按下 + 移动」真的让窗口跟随；卡片像素 alpha=255
     且为底色 #fffaf5（不透明）；置顶（锁定）时拖拽被拒。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QDialog, QGraphicsView
from PyQt6.QtCore import Qt, QPoint, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent

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

print("[D] 便签结构重写：无 QGraphics 代理层 + 拖拽接控件自身鼠标事件")
tsrc = open(tw.__file__, encoding="utf-8").read()
# 仅统计「实际调用」self.startSystemMove( / self.grabMouse( / self.releaseMouse(，
# 注释里的历史描述不算（用括号后紧跟形参或调用特征过滤）。
import re
call_calls = re.findall(r"self\.(?:startSystemMove|grabMouse|releaseMouse)\s*\(", tsrc)
check(len(call_calls) == 0,
      f"便签拖拽路径不得再直接调用 startSystemMove/grabMouse/releaseMouse（实测 {len(call_calls)} 处）")
check("_StickyView" not in tsrc, "源码不再有 _StickyView（便签代理视图已删除）")
check("QGraphicsProxyWidget()" not in tsrc, "便签不再构造 QGraphicsProxyWidget 代理层")
check("root.addWidget(self.note)" in tsrc,
      "卡片 self.note 是窗口根布局的直接子控件（与 TodoWindow 同构）")
check("WA_StyledBackground, True" in tsrc.split("def _build_note")[1][:600],
      "卡片设 WA_StyledBackground（QSS 实底才能绘制出来 → 不透明）")
check("_w.mousePressEvent = self._drag_press" in tsrc,
      "拖拽按下事件接到 bar / note 控件自身（不再靠事件冒泡到窗口）")
check("_w.mouseMoveEvent = self._drag_move" in tsrc, "拖拽移动事件接到控件自身")
check("_w.mouseReleaseEvent = self._drag_release" in tsrc, "拖拽释放事件接到控件自身")
check("e.accept()" in tsrc.split("def _drag_press")[1].split("def _drag_move")[0],
      "_drag_press 显式 accept()（保证 Qt 隐式抓取：后续移动持续送达同一控件）")
check("self._pending_drag" not in tsrc, "旧的 _pending_drag 冒泡方案已彻底移除")

print("[D2] 行为验证：合成鼠标事件 → 拖拽真的让窗口跟随 / 卡片不透明 / 锁定拒拖")
from types import SimpleNamespace

_task = {"id": "probe-sticky-id", "title": "探针", "content": "", "done": False,
         "priority": "高", "bg": "#fffaf5"}
_fake_tw = SimpleNamespace(sticky_windows={}, _render=lambda *a, **k: None,
                           unregister_sticky=lambda *a, **k: None)


def _mev(kind, local, glob, btn=Qt.MouseButton.LeftButton):
    return QMouseEvent(kind, QPointF(*local), QPointF(*glob), btn, btn,
                       Qt.KeyboardModifier.NoModifier)


w = tw.StickyNoteWindow(_task, _fake_tw, None)
w.move(200, 200)
w.show()
app.processEvents()

# 1) 无代理层：便签内部不应有任何 QGraphicsView 子控件
check(not w.findChildren(QGraphicsView), "便签窗口内无 QGraphicsView（代理层已移除）")

# 2) 卡片不透明：取「卡片内边距正中」这个必定是卡片背景、且落在圆角内的像素，
#    alpha 必须 255 且为便签底色（注意不能取 (0,0)：那是圆角外的透明区）。
_img = w.grab().toImage()
_m = w.note.layout().contentsMargins()
_pt = (max(1, (_m.left() or 20) // 2), max(1, (_m.top() or 20) // 2))
check(w.note.childAt(*_pt) is None, f"采样点 {_pt} 应落在卡片背景（无子控件覆盖）")
_c = _img.pixelColor(*_pt)
check(_c.alpha() == 255,
      f"卡片背景像素必须完全不透明（@ {_pt} 实得 alpha={_c.alpha()}）")
check(_c.name().lower() == "#fffaf5",
      f"卡片背景像素应为便签底色 #fffaf5（实得 {_c.name()}）")

# 3) 拖拽行为：按下（记偏移）→ 移动（窗口跟随）→ 释放（清状态）
w._drag_press(_mev(QEvent.Type.MouseButtonPress, (10, 10), (210, 210)))
check(w._drag_pos is not None, "可拖区按下后记录拖拽偏移")
# 按下点 (210,210) 相对窗口 (200,200) 偏移 (10,10)；移动到 (260,240) → 窗口应为 (250,230)
w._drag_move(_mev(QEvent.Type.MouseMove, (60, 40), (260, 240)))
check(w.pos() == QPoint(250, 230), f"移动后窗口应跟随到 (250,230)（实得 {w.pos()}）")
w._drag_release(_mev(QEvent.Type.MouseButtonRelease, (60, 40), (260, 240)))
check(w._drag_pos is None, "释放后清空拖拽状态")

# 4) 置顶（锁定）后不得再被拖动
w._locked = True
_before = w.pos()
w._drag_press(_mev(QEvent.Type.MouseButtonPress, (10, 10), (210, 210)))
check(w._drag_pos is None, "锁定状态下按下不进入拖拽（_drag_pos 保持 None）")
w._drag_move(_mev(QEvent.Type.MouseMove, (80, 60), (280, 260)))
check(w.pos() == _before, f"锁定状态下移动窗口位置不变（实得 {w.pos()}）")
w._locked = False
w.hide()
w.deleteLater()
app.processEvents()

print()
if fails:
    print(f"RESULT: {len(fails)} FAIL")
    sys.exit(1)
print("RESULT: ALL PASS")
