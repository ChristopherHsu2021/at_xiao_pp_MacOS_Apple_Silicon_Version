"""临时校验：便签默认尺寸工具栏 + 置顶锁定行为（跑完可删）。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent
from types import SimpleNamespace
import app.ui.todo_window as tw
import app.ui.screen_fit as sf

app = QApplication([])


def mev(kind, local, glob, btn=Qt.MouseButton.LeftButton):
    return QMouseEvent(kind, QPointF(*local), QPointF(*glob), btn, btn,
                       Qt.KeyboardModifier.NoModifier)


_task = {"id": "fit", "title": "还不", "content": "", "done": False,
         "priority": "中", "bg": "#fffaf5"}
_fake = SimpleNamespace(sticky_windows={}, _render=lambda *a, **k: None,
                        unregister_sticky=lambda *a, **k: None)
w = tw.StickyNoteWindow(_task, _fake, None)
w.move(200, 200)
w.show()
for _ in range(6):
    app.processEvents()

print("== 布局 ==")
tb = w.editor.toolbar
print("win", w.width(), w.height(), "| toolbar h", tb.height(),
      "| textedit h", w.editor.editor.height(),
      "| toolbar bottom", tb.mapTo(w, tb.rect().bottomLeft()).y())
print("lock_frame visible (should be False):", w.lock_frame.isVisible())

print("== [E] 工具栏渐进显示（默认隐藏，下拉逐步露出） ==")
inner = sf.WINDOW_DEFAULTS["sticky"][0] - 2 * sf.s(20)
wrapped = tb.flow.heightForWidth(inner)
print("设计内宽 inner =", inner, "| 换行后工具栏完整高 =", wrapped,
      "| 默认尺寸下实际 toolbar h =", tb.height())
assert (tb.height() == 0) or (not tb.isVisible()), \
    "默认尺寸 320×280 下工具栏应整条隐藏"
assert w.editor.editor.height() >= sf.s(40), "工具栏隐藏后正文区高度不足"
# 下拉 20px → 露出 20px
w.resize(320, 300)
for _ in range(4):
    app.processEvents()
print("拉高到 300 → toolbar h =", tb.height())
assert tb.height() == min(wrapped, 20), "拉高 20px 应恰好露出 20px 工具栏"
# 拉满 → 完整露出，所有按钮可见
w.resize(320, 400)
for _ in range(4):
    app.processEvents()
print("拉高到 400 → toolbar h =", tb.height())
assert tb.height() == wrapped, "拉高足够后工具栏应完整露出"
# 所有 11 个按钮是否都在窗口内
bad = []
for key, btn in w.editor._cmd_buttons.items():
    if not btn.isVisible():
        continue
    bl = btn.mapTo(w, btn.rect().bottomLeft())
    br = btn.mapTo(w, btn.rect().bottomRight())
    if bl.y() >= w.height() or br.y() >= w.height() or br.x() >= w.width():
        bad.append((key, bl.x(), br.x(), br.y()))
print("越界按钮 =", bad if bad else "无（全部可见）")
assert not bad, "存在被裁切的工具栏按钮：%s" % bad
# 缩回默认 → 重新隐藏
w.resize(320, 280)
for _ in range(4):
    app.processEvents()
assert tb.height() == 0, "缩回默认高后工具栏应重新隐藏"
assert tuple(sf.WINDOW_DEFAULTS["sticky"]) == (320, 280)
assert w.minimumHeight() == 280, "默认/最小尺寸应保持 320×280 不变"
print("[E] PASS")

print("== [F] 置顶锁定 ==")
print("pin tip before:", w.btn_pin.toolTip(), "| _pinned_top:", w._pinned_top,
      "| _locked:", w._locked)
w.toggle_pin()
app.processEvents()
print("after pin -> _pinned_top:", w._pinned_top, "| _locked:", w._locked,
      "| tip:", w.btn_pin.toolTip())
print("  grips visible:", [g.isVisible() for g in w._grips])
print("  lock_frame visible:", w.lock_frame.isVisible(),
      "| geom:", w.lock_frame.geometry().getRect())
_before = w.pos()
w._drag_press(mev(QEvent.Type.MouseButtonPress, (10, 10), (210, 210)))
w._drag_move(mev(QEvent.Type.MouseMove, (80, 60), (280, 260)))
print("  drag while pinned: _drag_pos =", w._drag_pos, "| pos moved:", w.pos() != _before)
w.toggle_pin()
app.processEvents()
print("after unpin -> _pinned_top:", w._pinned_top, "| grips:",
      [g.isVisible() for g in w._grips], "| lock_frame:", w.lock_frame.isVisible(),
      "| tip:", w.btn_pin.toolTip())
w._drag_press(mev(QEvent.Type.MouseButtonPress, (10, 10), (210, 210)))
w._drag_move(mev(QEvent.Type.MouseMove, (80, 60), (280, 260)))
print("  drag after unpin: moved:", w.pos() != _before)
w.toggle_pin()
app.processEvents()
img = w.grab().toImage()
print("  edge pixel (2, 2):", img.pixelColor(2, 2).name(), img.pixelColor(2, 2).alpha())
print("  center pixel:", img.pixelColor(w.width() // 2, w.height() - 6).name())
print("  common.is_pinned_top:", end=" ")
import app.ui.common as C
print(C.is_pinned_top(w))
w.hide()
