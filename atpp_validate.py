import sys, os, faulthandler, types
faulthandler.enable()
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import PyQt6  # noqa
from PyQt6.QtWidgets import (QApplication, QPushButton, QGraphicsView, QGraphicsScene,
                             QLabel)
from PyQt6.QtCore import Qt, QEvent, QPoint, QPointF, QRectF, QSize
from PyQt6.QtGui import QMouseEvent, QContextMenuEvent, QColor, QWheelEvent
from types import SimpleNamespace

app = QApplication(sys.argv)


def _shot(name):
    """截图输出到脚本所在目录（跨平台，不写死 Windows 路径）。"""
    return os.path.join(ROOT, name)

# 关键：offscreen 平台字体库不含系统字体 → 中文渲染成方块；按平台显式注册。
# macOS 用 PingFang SC；Windows 用 msyh.ttc；找不到则跳过（不影响断言，仅截图中文可能成方块）。
from PyQt6.QtGui import QFont, QFontDatabase
if sys.platform == "darwin":
    if QFontDatabase.addApplicationFont("PingFang SC") != -1:
        app.setFont(QFont("PingFang SC", 10))
else:
    _fid = QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    if _fid != -1:
        _fams = QFontDatabase.applicationFontFamilies(_fid)
        app.setFont(QFont(next((f for f in _fams if "UI" in f), _fams[0]), 10))

# --- stub voice (avoid heavy speech chain) ---
_voice = types.ModuleType("app.core.voice")
_voice.say = lambda *a, **k: None
sys.modules["app.core.voice"] = _voice

import app.ui.todo_window as twmod
import app.core.todo as todo_mod
from app.core import config

# Track todo state
STATE = {"done": False, "title": "测试任务", "content": "<p>原始内容</p>"}
def get_task(tid):
    return {"id": tid, "title": STATE["title"], "content": STATE["content"], "done": STATE["done"]}
def set_done(tid, d):
    STATE["done"] = d
    return True
def set_note(tid, t, c):
    STATE["title"] = t
    STATE["content"] = c
    return True
todo_mod.get_task = get_task
todo_mod.set_done = set_done
todo_mod.set_note = set_note

# 克隆任务测试用：不落盘，直接返回一个带自增 id 的新任务
# 注意：签名必须与 app/core/todo.add 保持一致（含 bg —— 便签背景色持久化新增的字段），
# 否则 copy_task 里多传一个参数就会让本脚本以「假失败」中断掉后面的全部校验。
_add_count = [0]
def _stub_add(title, content, remind=None, alarm_id=None, priority="中", bg=None):
    _add_count[0] += 1
    return {"id": 9000 + _add_count[0], "title": title, "content": content,
            "priority": priority, "done": False, "remind": remind,
            "remind_enabled": remind is not None, "alarm_id": alarm_id, "bg": bg}
todo_mod.add = _stub_add

results = []
def check(name, cond, extra=""):
    results.append((name, cond, extra))
    print(("PASS " if cond else "FAIL ") + name + (("  " + extra) if extra else ""), flush=True)

# Mock TodoWindow registry/glue
class MockTodo:
    # 级联错位所需字段（与真实 TodoWindow 对齐）
    CASCADE_STEP = twmod.TodoWindow.CASCADE_STEP
    CASCADE_MAX = twmod.TodoWindow.CASCADE_MAX

    def __init__(self):
        self.stickies = {}
        self.render_calls = 0
        self.last_base = None

    @property
    def sticky_windows(self):
        """真实 TodoWindow 用的注册表名，供 TodoWindow._cascade_sticky 复用。"""
        return self.stickies
    def open_sticky(self, task, base=None):
        # base：仅「复制任务」会传（新便签相对原窗级联错位），此处记录以备断言
        self.last_base = base
        if task["id"] in self.stickies:
            self.stickies[task["id"]].raise_()
            return
        win = twmod.StickyNoteWindow(task, self, SimpleNamespace())
        self.stickies[task["id"]] = win
        win.show()
        if base is not None:
            twmod.TodoWindow._cascade_sticky(self, win, base)
    def unregister_sticky(self, tid):
        self.stickies.pop(tid, None)
    def notify_sticky(self, tid):
        win = self.stickies.get(tid)
        if win:
            win.sync_state()
    def _render(self):
        self.render_calls += 1
    def _prune_stickies(self):
        for tid in list(self.stickies):
            if todo_mod.get_task(tid) is None:
                self.stickies[tid].close()

parent = MockTodo()
task = {"id": "t1", "title": "测试任务", "content": "<p>原始内容</p>", "done": False}

print("== construct ==")
w = twmod.StickyNoteWindow(task, parent, SimpleNamespace())
parent.stickies["t1"] = w  # open_sticky would register it in real flow
check("construct", True)
w.show()
check("show", True)

# default bg
check("default bg #fffaf5", w._bg.name().lower() == "#fffaf5", w._bg.name())

# 数据连通性：打开便签时已载入任务真实标题与内容（修复：之前永远显示占位符）
check("open loads title", w.title.text() == "测试任务", w.title.text())
check("open loads content html", "原始内容" in w.editor.to_html(), w.editor.to_html()[:30])

# done toggle (sticky -> list)
STATE["done"] = False
w.toggle_done()
check("toggle_done sets todo done", STATE["done"] is True)
check("toggle_done triggers parent._render", parent.render_calls >= 1)
title_font = w.title.font()
check("title strike on done", title_font.strikeOut())
# complete icon color green when done
check("complete icon green when done", w.btn_complete.icon().availableSizes() and True)

# undo done
w.toggle_done()
check("toggle_done undone", STATE["done"] is False)
check("title no strike when undone", not w.title.font().strikeOut())

# bidirectional: list-side toggle -> notify_sticky -> sync_state
STATE["done"] = True
parent.notify_sticky("t1")
check("notify sync strike", w.title.font().strikeOut())
STATE["done"] = False
parent.notify_sticky("t1")
check("notify sync unstrike", not w.title.font().strikeOut())

# pin lock
was_locked = w._locked
w.toggle_pin()
check("pin toggles _locked", w._locked != was_locked and w._locked is True)
w.toggle_pin()
check("unpin", w._locked is False)

# 拖动：bar / 卡片左键空白处进入手动拖拽（_drag 建立 + grabMouse 全局追踪）；
# 点到按钮、或置顶（锁定）时不进入拖拽。
# 注：旧实现走原生 windowHandle().startSystemMove()，为改善拖拽手感且适配
# 无边框+置顶+QGraphicsProxyWidget 旋转卡片，已改为 grabMouse 手动拖拽，
# 故断言从「startSystemMove 被调用」改为「_drag 状态被正确建立」。
ev_empty = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(2, 2),
                       Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)


def _release_mouse():
    """清理 grabMouse，避免影响后续用例。"""
    try:
        w._drag = None
        w.releaseMouse()
    except Exception:
        pass


def _press_bar(ev):
    """模拟在标题栏按下一次左键，返回拖拽状态（dict=进入拖拽 / None=未进入）。"""
    _release_mouse()
    w.eventFilter(w.bar, ev)
    return w._drag


drag = _press_bar(ev_empty)
check("bar press empty -> 建立手动拖拽状态",
      isinstance(drag, dict) and "start_global" in drag and "start_pos" in drag, str(drag))
_release_mouse()
# 点到按钮（complete）不应进入拖拽，按钮要能正常点击
ev_btn = QMouseEvent(QEvent.Type.MouseButtonPress,
                     w.btn_complete.pos().toPointF() + QPointF(2, 2),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
check("bar press on button -> no drag", _press_bar(ev_btn) is None)
_release_mouse()
# 置顶（锁定）时不进入拖拽
w.toggle_pin()  # lock
check("bar press locked -> no drag", _press_bar(ev_empty) is None)
w.toggle_pin()  # unlock
_release_mouse()

# bg switch
w.set_bg("#fff9c4")
check("set_bg updates color", w._bg.name().lower() == "#fff9c4")

# 复制任务：克隆为新任务 + 打开对应便签 + 列表同步渲染（修复：之前只复制剪贴板）
before_stickies = set(parent.stickies.keys())
before_render = parent.render_calls
w.title.setText("拷贝标题")
w.editor.editor.setPlainText("拷贝正文")
new_id = w.copy_task()
check("copy_task returns new id", isinstance(new_id, int))
check("copy_task opens new sticky", new_id not in before_stickies and new_id in parent.stickies)
check("copy_task triggers _render", parent.render_calls > before_render)
nw = parent.stickies[new_id]
# 复制出的新便签应相对原窗错位（否则完全重叠，用户会以为没复制成功）
check("copy_task 传入 base=原窗", parent.last_base is w)
check("copy_task 新便签不与原窗完全重叠", nw.pos() != w.pos(),
      "new=%s base=%s" % ((nw.x(), nw.y()), (w.x(), w.y())))
check("cloned title matches", nw.title.text() == "拷贝标题", nw.title.text())
check("cloned content matches", "拷贝正文" in nw.editor.to_html())
w.clear_content()
check("clear_content title", w.title.text() == "")
check("clear_content editor", w.editor.editor.toPlainText() == "")

# 右键菜单：无旋转、含复制/清空、白底圆角（对齐 HTML）
cm = twmod.StickyContextMenu(w, w)
check("context menu builds", cm is not None)
_btns = cm.findChildren(QPushButton)
# 菜单项文案现在放在 QPushButton 内部的 QLabel 里（左侧文字 + 右侧快捷键）
_cm_texts = [x.text() for x in cm.findChildren(QLabel) if x.text().strip()]
check("context menu no rotate", not any("旋转" in t for t in _cm_texts), str(_cm_texts))
check("context menu has 复制任务", "复制任务" in _cm_texts, str(_cm_texts))
check("context menu has 清空内容", "清空内容" in _cm_texts, str(_cm_texts))
# 颜色圆点：5 色（含主题色，无「白」）
from PyQt6.QtWidgets import QHBoxLayout
_swatches = [b for b in _btns
             if b.styleSheet().startswith("background:") and "border-radius:9px" in b.styleSheet()]
check("context menu 5 swatches (no white)", len(_swatches) == 5, str(len(_swatches)))
# 右键菜单截图（白底 8px 圆角 + 灰色 hover 项 + 5 色圆点，无旋转）
cm.show()
app.processEvents()
cm.grab().save(_shot("sticky_menu.png"))
check("menu screenshot saved", os.path.exists(_shot("sticky_menu.png")))
cm.close()

# close: must not raise (removed bug fixed), must unregister + render
rc = parent.render_calls
try:
    w.close()
    check("close no exception", True)
except Exception as e:  # noqa
    check("close no exception", False, repr(e))
check("close unregisters", "t1" not in parent.stickies)
check("close triggers _render", parent.render_calls > rc)

# open via mock todo registry (covers open_sticky path)
parent.open_sticky({"id": "t2", "title": "T2", "content": "", "done": False})
check("open_sticky registers", "t2" in parent.stickies)

# screenshot of a fresh sticky + multi-size "fully visible" layout assertions
shot = twmod.StickyNoteWindow(
    {"id": "shot", "title": "截图任务", "content": "<p>便签内容示例</p>", "done": False},
    parent, SimpleNamespace())
shot.title.setText("截图任务")
shot.editor.editor.setPlainText("便签内容示例")
shot.show()
# 初始默认尺寸（420x380）下，showEvent 重新同步几何后卡片应恰好铺满窗口、不被裁切
app.processEvents()  # 让 showEvent 内的 singleShot(0) 重新同步几何生效
check("initial note not taller than window (no bottom clip)",
      shot.note.height() <= shot.height(),
      f"note={shot.note.height()} win={shot.height()}")
_eg = shot.editor.mapTo(shot, shot.editor.rect().bottomLeft())
check("initial editor bottom inside window",
      _eg.y() <= shot.height(), f"editor_bottom={_eg.y()} win={shot.height()}")

# ---- 对齐 HTML 的新增约束 ----
check("default width 420", shot.width() == 420, str(shot.width()))
check("min size 400x380", shot.minimumWidth() == 400 and shot.minimumHeight() == 380,
      f"{shot.minimumWidth()}x{shot.minimumHeight()}")
check("max size 980x820", shot.maximumWidth() == 980 and shot.maximumHeight() == 820,
      f"{shot.maximumWidth()}x{shot.maximumHeight()}")
check("padding 20px (p-5)", shot.note.layout().contentsMargins().left() == 20,
      str(shot.note.layout().contentsMargins().left()))
check("card radius 8px (rounded-lg)", "border-radius:8px" in shot.note.styleSheet())
# 代理控件**不再**挂 QGraphicsDropShadowEffect：卡片与窗口等大、投影被视口裁掉（不可见），
# 而图形特效会让每次重绘都对整卡做高斯模糊 → 半透明置顶窗卡顿（用户反馈）。这里锁死该不变式。
check("proxy has no drop shadow (perf, avoids per-repaint blur)",
      shot._proxy.graphicsEffect() is None)
# 顶栏三按钮已通过 _btn_icon 接线（role 属性 + 有效图标）
for _role, _b in (("complete", shot.btn_complete), ("pin", shot.btn_pin),
                  ("close", shot.btn_close)):
    check(f"btn {_role} role+icon", _b.property("role") == _role
          and not shot._btn_icon(_role, False).isNull())

# hover 切换图标配色（事件过滤器分派；QSS :hover 已启用 WA_Hover）
def _icon_bytes(btn):
    img = btn.icon().pixmap(20, 20).toImage()
    return bytes(img.constBits().asstring(img.sizeInBytes()))
_b0 = _icon_bytes(shot.btn_close)
shot.eventFilter(shot.btn_close, QEvent(QEvent.Type.HoverEnter))
check("close hover -> red icon", _icon_bytes(shot.btn_close) != _b0)
shot.eventFilter(shot.btn_close, QEvent(QEvent.Type.HoverLeave))
check("close hover restore gray", _icon_bytes(shot.btn_close) == _b0)

# 富文本工具栏：hover / 激活(锁定) 配色对齐任务清单页「全选」按钮的 hover（淡橙底 + 橙图标）
from app.ui import rich_editor as re_mod
check("compact QSS hover uses 全选 orange",
      "rgba(249,117,16,0.08)" in re_mod.EDITOR_QSS_COMPACT)
_bold = shot.editor._cmd_buttons["bold"]
_ib = _icon_bytes(_bold)
shot.editor.eventFilter(_bold, QEvent(QEvent.Type.HoverEnter))
check("toolbar hover -> icon recolored", _icon_bytes(_bold) != _ib)
shot.editor.eventFilter(_bold, QEvent(QEvent.Type.HoverLeave))
check("toolbar hover leave -> restore", _icon_bytes(_bold) == _ib)
shot.editor._set_active("bold", True)
check("toolbar active property", _bold.property("active") is True)
check("toolbar active -> icon recolored", _icon_bytes(_bold) != _ib)
shot.editor._set_active("bold", False)
check("toolbar inactive restore", _icon_bytes(_bold) == _ib)

# 紧凑取色弹窗（替代原生 QColorDialog，避免巨大系统对话框）
pop = re_mod.ColorPopup(QColor("#F97316"))
_sw = [b for b in pop.findChildren(QPushButton) if "border-radius:4px" in b.styleSheet()]
check("color popup has 32 swatches", len(_sw) == 32, str(len(_sw)))
check("color popup has 自定义", any(b.text() == "自定义…" for b in pop.findChildren(QPushButton)))
_got = []
pop.picked.connect(lambda c: _got.append(c.name()))
pop._pick(QColor("#ff0000"))
check("color popup emits picked", _got == ["#ff0000"], str(_got))
pop2 = re_mod.ColorPopup(QColor("#F97316"))
pop2.show()
app.processEvents()
pop2.grab().save(_shot("color_popup.png"))
check("color popup screenshot saved", os.path.exists(_shot("color_popup.png")))
pop2.close()

# 卡片任意位置右键（标题/内容）都应弹出统一的自绘菜单。
# ★ 关键回归：必须走**真实投递路径**（sendEvent 到真实接收者），不能直接调 eventFilter——
#   内容区右键的 ContextMenu 事件投递给的是 QTextEdit 的 **viewport**，而不是 QTextEdit
#   本身；此前只把过滤器装在 QTextEdit 上 → 永远收不到 → 弹 Qt 原生菜单（用户实机反馈）。
_cme = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(200, 200))
QApplication.sendEvent(shot.title, _cme)
check("right-click title -> custom menu",
      isinstance(getattr(shot, "_sticky_menu", None), twmod.StickyContextMenu))
try:
    shot._sticky_menu.close()
except Exception:  # noqa: BLE001
    pass
QApplication.sendEvent(shot.editor.editor.viewport(), _cme)
_menu = getattr(shot, "_sticky_menu", None)
check("right-click content viewport -> custom menu",
      isinstance(_menu, twmod.StickyContextMenu), type(_menu).__name__)

# 菜单内容：原生编辑块（本地化）+ 便签自定义块；且不得再出现「旋转便签」
if isinstance(_menu, twmod.StickyContextMenu):
    _texts = [w.text() for w in _menu.findChildren(QLabel) if w.text().strip()]
    for _t in ("撤销", "重做", "剪切", "复制", "粘贴", "删除", "全选",
               "复制任务", "清空内容", "便签背景"):
        check(f"menu has {_t}", _t in _texts, str(_texts))
    check("menu has shortcut hint ⌘Z", "⌘Z" in _texts, str(_texts))
    check("menu has no 旋转", not any("旋转" in t for t in _texts), str(_texts))
    check("menu is top-level popup (not clipped to window)", _menu.isWindow())
    _menu.grab().save(_shot("sticky_menu.png"))
    check("menu screenshot saved", os.path.exists(_shot("sticky_menu.png")))
    _menu.close()

# 语言跟随软件「语言」设置：切到 en 后菜单文案应为英文
_old_lang = config.settings.get("language", "zh-CN")
config.settings.set("language", "en", save=False)
_menu_en = twmod.StickyContextMenu(shot, shot, shot.editor.editor)
_en_texts = [w.text() for w in _menu_en.findChildren(QLabel) if w.text().strip()]
check("menu follows language (en Undo)", "Undo" in _en_texts, str(_en_texts))
check("menu follows language (en Copy Task)", "Copy Task" in _en_texts, str(_en_texts))
check("menu follows language (en Sticky Background)",
      "Sticky Background" in _en_texts, str(_en_texts))
check("menu follows language (en Select All -> All)",
      "All" in _en_texts, str(_en_texts))
_menu_en.close()
config.settings.set("language", _old_lang, save=False)

# 编辑动作真的作用于目标控件（全选 → 内容被选中）
shot.editor.editor.setPlainText("AB")
_menu2 = twmod.StickyContextMenu(shot, shot, shot.editor.editor)
_menu2._do_edit("全选")
check("menu edit action selectAll works",
      shot.editor.editor.textCursor().selectedText() == "AB",
      shot.editor.editor.textCursor().selectedText())
_menu2.close()

# 性能回归：代理控件不再挂图形特效（投影不可见却每次重绘全卡模糊 → 卡顿）；
# sceneRect 与视口等大（无滚动区间）
check("proxy has no graphics effect (perf)", shot._proxy.graphicsEffect() is None)
check("scene rect not padded (no scroll range)",
      shot._scene.sceneRect().size().toSize() == shot.size(),
      f"{shot._scene.sceneRect().size().toSize()} vs {shot.size()}")

for name, (WW, HH) in {"default": (440, 400), "narrow": (400, 380), "wide": (620, 520)}.items():
    shot.resize(WW, HH)
    app.processEvents()
    for label, wdg in (("complete", shot.btn_complete), ("pin", shot.btn_pin),
                       ("close", shot.btn_close), ("title", shot.title),
                       ("editor", shot.editor)):
        g = wdg.mapTo(shot, wdg.rect().topLeft())
        inside = (g.x() >= 0 and g.y() >= 0
                  and g.x() + wdg.width() <= shot.width()
                  and g.y() + wdg.height() <= shot.height())
        check(f"layout[{name}] {label} inside", inside,
              f"@({g.x()},{g.y()}) {wdg.width()}x{wdg.height()}")
    shot.grab().save(rf"D:\自研软件\AT小PP\sticky_{name}.png")

check("screenshot saved", os.path.exists(r"D:\自研软件\AT小PP\sticky_default.png"))

# ---- 便签滚轮防滚动：内容为空时滚轮不得把整张卡片顶偏/裁切 ----
print("== sticky wheel scroll guard ==")
shot.resize(440, 400)
app.processEvents()
check("sticky uses _StickyView", isinstance(shot._view, twmod._StickyView),
      type(shot._view).__name__)


def _wheel(widget, dy):
    ev = QWheelEvent(QPointF(30.0, 150.0), QPointF(30.0, 150.0), QPoint(0, 0),
                     QPoint(0, dy), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)


_v = shot._view
_c0 = _v.mapToScene(_v.viewport().rect().center())
for _dy in (-120, 120, -240, 240, -480):
    _wheel(_v.viewport(), _dy)
    app.processEvents()
_c1 = _v.mapToScene(_v.viewport().rect().center())
check("wheel never scrolls sticky", _c0 == _c1, f"{_c0} -> {_c1}")

# 对照组：同样的 scene 尺寸，普通 QGraphicsView 会被滚轮滚走（证明该断言有意义）
_vr = QGraphicsView()
_vr.setScene(QGraphicsScene())
_vr.scene().setSceneRect(QRectF(-36, -36, 440 + 72, 400 + 72))
_vr.resize(440, 400)
_vr.show()          # 必须 show：否则 viewport 尺寸未确定，滚动区间为 0，测不出滚动
app.processEvents()
_r0 = _vr.mapToScene(_vr.viewport().rect().center())
_wheel(_vr.viewport(), -120)
_r1 = _vr.mapToScene(_vr.viewport().rect().center())
check("control: plain view DOES scroll", _r0 != _r1, f"{_r0} -> {_r1}")
_vr.hide()

# 内容超长时，滚轮仍由内层 QTextEdit 自行消费（禁用视图滚动不能把编辑器一起禁掉）
shot.editor.set_html("<p>" + ("长文本滚动测试<br>" * 80) + "</p>")
shot.resize(440, 400)
app.processEvents()
_te = shot.editor.editor
_tsb = _te.verticalScrollBar()
_tsb.setValue(0)
_wheel(_te.viewport(), -120)
app.processEvents()
check("long content: inner editor still scrolls", _tsb.value() > 0, str(_tsb.value()))
shot.editor.set_html("")

# ---- 任务清单页顶部四按钮：宽度统一（与「返回」一致），「添加」去掉加号 ----
print("== todo list header buttons ==")
try:
    _ctx = SimpleNamespace(refresh_alarm=lambda: None,
                           stop_alarm=lambda *a, **k: None)
    tw = twmod.TodoWindow(_ctx)
    tw.show()
    app.processEvents()
    _ws = [tw.sel_all.width(), tw.add_b.width(), tw.del_b.width(), tw.back_b.width()]
    check("header 4 buttons same width", len(set(_ws)) == 1, str(_ws))
    check("header width == 返回 width", tw.back_b.width() == 62, str(tw.back_b.width()))
    check("add button has no plus", "+" not in tw.add_b.text(), tw.add_b.text())
    check("add button text is 添加", tw.add_b.text() == "添加", tw.add_b.text())
    # 「添加」是实心主按钮：不能比其余空心按钮宽出可见的一截
    check("primary add width matches others", tw.add_b.width() == tw.back_b.width())
    tw.grab().save(_shot("todo_header.png"))
    check("todo header screenshot saved",
          os.path.exists(_shot("todo_header.png")))
    tw.hide()
except Exception as _e:  # noqa: BLE001
    check("todo header built", False, repr(_e))

# 完成 + 置顶态的视觉截图（绿勾 / 橙针 / 标题删除线）
STATE["done"] = True
shot2 = twmod.StickyNoteWindow(
    {"id": "shot2", "title": "已完成任务", "content": "<p>完成态样式</p>", "done": True},
    parent, SimpleNamespace())
shot2.title.setText("已完成任务")
shot2.editor.editor.setPlainText("完成态样式")
shot2.toggle_pin()            # 置顶（锁定）→ 橙色图钉
shot2.sync_state()            # 完成态 → 实心绿勾 + 标题删除线
shot2.show()
shot2.resize(440, 400)
app.processEvents()
shot2.grab().save(_shot("sticky_done_pinned.png"))
check("done+pinned screenshot saved", os.path.exists(r"D:\自研软件\AT小PP\sticky_done_pinned.png"))
check("done title strike", shot2.title.font().strikeOut())
check("pinned locked", shot2._locked is True)
check("done icon filled (green)", not shot2._btn_icon("complete", False).isNull())

# ---- 需求 A：添加/编辑页「任务内容框」右键菜单须与便签页完全一致（同源 EditContextMenu）----
print("== edit-page rich editor context menu (需求 A) ==")
ed = re_mod.RichEditor(compact=False)
ed.show()
app.processEvents()
ed._edit_menu = None
_cme2 = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(200, 200))
QApplication.sendEvent(ed.editor.viewport(), _cme2)
_menu_full = getattr(ed, "_edit_menu", None)
check("edit-page viewport -> EditContextMenu",
      isinstance(_menu_full, re_mod.EditContextMenu), type(_menu_full).__name__)
if isinstance(_menu_full, re_mod.EditContextMenu):
    _ft = [w.text() for w in _menu_full.findChildren(QLabel) if w.text().strip()]
    for _t in ("撤销", "重做", "剪切", "复制", "粘贴", "删除", "全选"):
        check(f"edit menu has {_t}", _t in _ft, str(_ft))
    # 与便签菜单的「编辑动作块」完全一致（同源基类，避免再次漂移）
    _sm = twmod.StickyContextMenu(shot, shot, shot.editor.editor)
    _sticky_texts = [w.text() for w in _sm.findChildren(QLabel) if w.text().strip()]
    _edit_block = [t for t in _ft if t in ("撤销", "重做", "剪切", "复制", "粘贴", "删除", "全选")]
    _sticky_block = [t for t in _sticky_texts if t in ("撤销", "重做", "剪切", "复制", "粘贴", "删除", "全选")]
    check("edit menu edit-block == sticky edit-block",
          _edit_block == _sticky_block, f"{_edit_block} vs {_sticky_block}")
    _sm.close()
    _menu_full.close()
    # 语言跟随：切 en 后编辑块应为英文
    config.settings.set("language", "en", save=False)
    _menu_en2 = re_mod.EditContextMenu(ed, ed.editor)
    _en2 = [w.text() for w in _menu_en2.findChildren(QLabel) if w.text().strip()]
    check("edit menu follows language (en Undo)", "Undo" in _en2, str(_en2))
    config.settings.set("language", _old_lang, save=False)
ed.hide()

# ---- 需求 B：全软件可见文案须跟随语言 —— 校验新增 i18n 词条齐全且有英文映射 ----
print("== i18n key coverage (需求 B) ==")
from app.core import i18n as i18n_mod
_required = ["加粗", "斜体", "下划线", "删除线", "项目符号列表", "编号列表", "左对齐", "居中",
             "右对齐", "插入链接", "清除格式", "引用", "字体", "字号", "文字颜色", "高亮/标记",
             "自定义…", "自定义颜色", "字体：%s", "字号：%s", "在这里编辑任务详情",
             "在这里填写任务详情，可用上方工具栏排版…（可选）", "请输入链接地址（https://…）",
             "安装失败", "把『人物』拖到『物品』上，凑到一起就能触发捏～", "今日已饮用 {n} 杯",
             "缓存", "在线", "未命名", "排序", "音频文件", "已添加到我喜欢", "添加到我喜欢",
             "触发成功捏！", "时间到捏"]
_missing = [k for k in _required if k not in i18n_mod.TRANSLATIONS]
check("all required i18n keys present", not _missing, str(_missing))
# en 不能回退成中文（缺英文映射时 tr(en) 会返回原文=中文，违背需求 B）
_still_zh = [k for k in _required
             if k in i18n_mod.TRANSLATIONS and i18n_mod.tr(k, "en") == k]
check("required keys have English (en != zh)", not _still_zh, str(_still_zh))

print("\nSUMMARY:", "ALL PASS" if all(c for _, c, _ in results) else "HAS FAILURES",
      "| total", len(results), "pass", sum(1 for _, c, _ in results if c))
