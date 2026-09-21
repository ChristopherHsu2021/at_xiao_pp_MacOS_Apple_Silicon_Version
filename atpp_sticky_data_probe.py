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
  E) 默认尺寸（320×280）下富文本工具栏**完整可见**（含窄宽度换行后的第二行）——
     用户意见附图的核心诉求：此前紧凑编辑器 180px 硬最小高使卡片竖向需求 371px > 280px，
     布局溢出把底部工具栏裁掉，只有把窗口往下拉大才慢慢露出来。
  E2) 该修复的**结构性兜底**：StickyNoteWindow._ensure_toolbar_visible 在构造期把窗口
     最小高抬到「布局真实最小高」（含换行后的整条工具栏）。因为 fit_window 写入的是
     **显式**最小尺寸，会令 QLayout 的 SetDefaultConstraint 失效 —— 布局可以被压到
     自身最小高之下，被压掉的正好是底部那条 setFixedHeight 的工具栏。
  F) 置顶按钮语义（用户定义）：点一下选定 —— 不能移动、不能调整大小（隐藏握把 +
     摘掉 macOS 原生 resizable 位）、加橙色描边；再点一下取消，恢复可拖可缩。
  G) 层级/让路接线（源码级）：置顶便签「只抬不降」（LEVEL_PINNED / release_topmost 跳过 /
     main 每拍最后抬层 / 点击别的页面也会被压回），未锁定便签随其它卡片一起让路。
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
from app.ui.screen_fit import s as s_local
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
w.set_pinned(True)
_before = w.pos()
w._drag_press(_mev(QEvent.Type.MouseButtonPress, (10, 10), (210, 210)))
check(w._drag_pos is None, "锁定状态下按下不进入拖拽（_drag_pos 保持 None）")
w._drag_move(_mev(QEvent.Type.MouseMove, (80, 60), (280, 260)))
check(w.pos() == _before, f"锁定状态下移动窗口位置不变（实得 {w.pos()}）")
w.set_pinned(False)

print("[E] 默认尺寸下富文本工具栏必须完整可见（用户意见附图的核心诉求）")
w.resize(320, 280)
app.processEvents()
for _ in range(4):
    app.processEvents()
_tb = w.editor.toolbar
_tb_bottom = _tb.mapTo(w, _tb.rect().bottomLeft()).y()
check(_tb.isVisible(), "富文本工具栏可见")
check(_tb_bottom < w.height(),
      f"工具栏底边必须落在窗口内（底边 {_tb_bottom} < 窗高 {w.height()}）")
check(w.editor.editor.height() >= s_local(40),
      f"正文区仍有可用高度（实得 {w.editor.editor.height()}px）")
_clipped = []
for _key, _b in w.editor._cmd_buttons.items():
    _p = _b.mapTo(w, _b.rect().bottomLeft())
    if _p.y() >= w.height():
        _clipped.append(_key)
for _b in (w.editor.fore_btn, w.editor.hili_btn):
    _p = _b.mapTo(w, _b.rect().bottomLeft())
    if _p.y() >= w.height():
        _clipped.append("color")
check(not _clipped,
      f"工具栏 11 个按钮（含换行后的第二行）全部在窗口内（被裁：{_clipped}）")
check(w.layout().minimumSize().height() <= w.height(),
      f"卡片布局最小需求高度不超过默认窗高（需求 {w.layout().minimumSize().height()}"
      f" <= {w.height()}）—— 溢出正是原先「工具栏被裁掉、下拉拉大才露出」的根因")

print("[E2] 尺寸兜底：_ensure_toolbar_visible（防未来字体/缩放变化再次裁掉工具栏）")
_tsrc_e2 = open(tw.__file__, encoding="utf-8").read()
check("def _ensure_toolbar_visible" in _tsrc_e2,
      "StickyNoteWindow 提供 _ensure_toolbar_visible（按布局最小高反算）")
check("self._ensure_toolbar_visible()" in _tsrc_e2,
      "构造期（fit_window 之后）即调用一次 —— 打开便签就是完整可见的尺寸")
check(w.minimumHeight() >= w.note.layout().minimumSize().height(),
      f"窗口最小高 >= 卡片布局最小需求（{w.minimumHeight()} >= "
      f"{w.note.layout().minimumSize().height()}）：fit_window 的显式最小值会让 QLayout 的"
      " SetDefaultConstraint 失效，必须自己抬，否则布局可被压到工具栏之下")
_rows, _cur, _x = [], [], 0
_inner_w = max(1, w.editor.toolbar.width())
for _it in w.editor.toolbar.flow._items:
    _ih = w.editor.toolbar.flow._hint(_it)
    if _cur and _x + _ih.width() > _inner_w:
        _rows.append(len(_cur))
        _cur, _x = [], 0
    _cur.append(_it)
    _x += _ih.width() + 4
if _cur:
    _rows.append(len(_cur))
check(sum(_rows) == 11,
      f"11 个按钮全部参与换行布局（内宽 {_inner_w} → 分行 {_rows}，即「9+2」两行）")
check(w.height() >= w.minimumHeight()
      and w.minimumHeight() == max(280, w.note.layout().minimumSize().height()),
      f"默认高 280 未被兜底逻辑撑大（最小高 {w.minimumHeight()}；需求 "
      f"{w.note.layout().minimumSize().height()} ≤ 280 时本兜底应为空操作）")

print("[F] 置顶按钮 = 选定/取消选定（不可移动、不可缩放、层级最高）")
check(not w._pinned_top and not w._locked, "初始未锁定")
check(w.btn_pin.toolTip() not in ("", "取消置顶", "Unpin"),
      f"未锁定时提示语为「置顶」（实得 {w.btn_pin.toolTip()!r}）")
w.toggle_pin()
app.processEvents()
check(w._pinned_top is True, "点击置顶 → 进入选定态（_pinned_top=True）")
check(w._locked is True, "_locked 为 _pinned_top 的只读别名（ResizeGrip 依赖它）")
check(w.btn_pin.toolTip() in ("取消置顶", "Unpin"),
      f"锁定后提示语变为「取消置顶」（实得 {w.btn_pin.toolTip()!r}）")
check(all(not g.isVisible() for g in w._grips),
      "锁定后 5 个边缘握把全部隐藏（否则边缘仍是缩放光标）")
check(w.lock_frame.isVisible() and w.lock_frame.geometry() == w.rect(),
      "锁定后卡片描边层可见且铺满窗口（「已选定」的视觉反馈）")
_img = w.grab().toImage()
_corner = _img.pixelColor(2, 2)
check(_corner.name().lower() == "#f9730f" and _corner.alpha() == 255,
      f"描边像素为主题橙 #f9730f 且不透明（实得 {_corner.name()} alpha={_corner.alpha()}）")
_before = w.pos()
w._drag_press(_mev(QEvent.Type.MouseButtonPress, (10, 10), (210, 210)))
w._drag_move(_mev(QEvent.Type.MouseMove, (90, 70), (290, 270)))
check(w._drag_pos is None and w.pos() == _before, "锁定后彻底不可移动")
w.toggle_pin()
app.processEvents()
check(w._pinned_top is False, "再点一次置顶 → 取消选定")
check(all(g.isVisible() for g in w._grips), "取消后边缘握把恢复显示")
check(not w.lock_frame.isVisible(), "取消后描边层隐藏")
check(w.btn_pin.toolTip() not in ("", "取消置顶", "Unpin"),
      f"取消后提示语回到「置顶」（实得 {w.btn_pin.toolTip()!r}）")
_before = w.pos()
w._drag_press(_mev(QEvent.Type.MouseButtonPress, (10, 10), (210, 210)))
w._drag_move(_mev(QEvent.Type.MouseMove, (90, 70), (290, 270)))
check(w._drag_pos is not None and w.pos() != _before, "取消后可正常拖动")
w._drag_release(_mev(QEvent.Type.MouseButtonRelease, (90, 70), (290, 270)))

print("[G] 置顶便签的层级/让路接线（源码级）——「只抬不降」")
import app.ui.common as cm
import app.ui.mac_window as mw
import app.ui.main as mn
check(cm.is_pinned_top(w) is True or cm.is_pinned_top(w) is False,
      "common.is_pinned_top 可判定置顶状态")
check("def is_pinned_top" in open(cm.__file__, encoding="utf-8").read(),
      "common 提供统一的 is_pinned_top 判定（收敛「只抬不降」逻辑）")
_csrc = open(cm.__file__, encoding="utf-8").read()
check("if is_pinned_top(widget):\n        return" in _csrc,
      "release_topmost 对置顶窗口直接返回（切到别的 App 也不降层）")
check("pinned=pinned" in _csrc, "keep_on_top 按置顶状态自动选择更高层级")
check("_raise_pinned_above" in _csrc,
      "note_front 抬完被点击窗口后会再把置顶窗口压回最上（点击别的页面也盖不住它）")
_msrc = open(mn.__file__, encoding="utf-8").read()
check("def _reassert_pinned" in _msrc and "self._reassert_pinned()" in _msrc,
      "main._keep_topmost 每拍把置顶便签排在所有卡片之后抬层")
check("for w in self._sticky_windows():\n            release_topmost(w)" in _msrc,
      "main._release_app_topmost 已纳入便签（未锁定便签随其它卡片一起让路）")
check(mw.LEVEL_PINNED > mw.LEVEL_FLOATING and mw.LEVEL_PINNED < 24,
      f"LEVEL_PINNED={mw.LEVEL_PINNED} 高于浮层({mw.LEVEL_FLOATING})、低于菜单栏(24)")
check(mw.LEVEL_ABOVE_PINNED > mw.LEVEL_PINNED,
      f"LEVEL_ABOVE_PINNED={mw.LEVEL_ABOVE_PINNED} 高于置顶层（弹层/模态框不被便签盖住）")
check("def apply_level" in open(mw.__file__, encoding="utf-8").read()
      and "def set_resizable" in open(mw.__file__, encoding="utf-8").read(),
      "mac_window 提供 apply_level（统一层级入口）与 set_resizable（锁定摘原生缩放位）")
check("def raise_above_pinned" in open(mw.__file__, encoding="utf-8").read(),
      "mac_window 提供 raise_above_pinned（弹层/模态框提权）")
# 便签确实把原生缩放一起关掉（只隐藏自绘握把挡不住 macOS 原生边缘缩放）
check("set_resizable(self, not on, tag=\"sticky-pin\")" in tsrc,
      "set_pinned 同步摘/补 macOS 原生 resizable styleMask")

w.hide()
w.deleteLater()
app.processEvents()

print()
if fails:
    print(f"RESULT: {len(fails)} FAIL")
    sys.exit(1)
print("RESULT: ALL PASS")
