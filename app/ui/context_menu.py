"""右键多级菜单构造（纯构建，动作数据通过 QAction.data 携带）。

菜单结构完全依据开发需求文档：
喝酒(酒类) / 喝茶(茶类) / 喝饮料(咖啡, 奶（果）茶) / 换装 / 工作 / 居家 / 待办 / 闹钟 / 计时 / 隐身 / 设置 / 退出
尼格罗尼 在文档中标注『此处不显示』，故跳过。
"""

from PyQt6.QtCore import Qt, QTimer, QEvent, QPoint, QRect
from PyQt6.QtWidgets import (
    QApplication, QGraphicsDropShadowEffect, QMenu, QPushButton, QVBoxLayout, QWidget,
)
from PyQt6.QtGui import QAction
from PyQt6.QtGui import QColor

from app.core import config
from app.core.i18n import tr
from app.ui.common import keep_on_top
from app.ui.screen_fit import scale_qss, s

MENU_QSS = scale_qss("""
QMenu {
    background: #fffaf5;
    border: 1px solid rgba(255,255,255,0.82);
    border-radius: 14px;
    padding: 6px;
    min-width: 150px;
}
QMenu::item {
    padding: 9px 24px 9px 12px;
    margin: 0px;
    min-width: 126px;
    border-radius: 8px;
    color: #3d2b1f;
    font-size: 13px;
    font-weight: 500;
}
QMenu::item:selected,
QMenu::item:enabled:selected,
QMenu::item:active:selected {
    background-color: rgba(249,117,16,0.14);
    color: #f97510;
}
QMenu::separator { height: 1px; background: rgba(249,117,16,0.14); margin: 4px 8px; }
QMenu::right-arrow { width: 12px; height: 12px; padding-right: 4px; }
""")


ACTION_POPUP_QSS = scale_qss("""
QWidget#actionPopupCard {
    background: #fffaf5;
    border: 1px solid rgba(255,255,255,0.82);
    border-radius: 14px;
}
QPushButton#actionPopupItem {
    background: transparent;
    border: none;
    border-radius: 8px;
    color: #3d2b1f;
    font-size: 13px;
    font-weight: 500;
    padding: 0 12px;
    text-align: left;
}
QPushButton#actionPopupItem:hover {
    background: rgba(249,117,16,0.14);
    color: #f97510;
}
""")


class ActionPopupMenu(QWidget):
    def __init__(self, parent, actions):
        super().__init__(parent)
        self._actions = list(actions)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        width = max(s(104), max((len(text) for text, _callback in self._actions), default=2) * s(16) + s(34))
        height = s(12) + len(self._actions) * s(34)
        self.setFixedSize(width, height)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.card = QWidget(self)
        self.card.setObjectName("actionPopupCard")
        self.card.setStyleSheet(ACTION_POPUP_QSS)
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(s(18))
        shadow.setOffset(0, s(6))
        shadow.setColor(QColor(180, 120, 50, 34))
        self.card.setGraphicsEffect(shadow)
        root.addWidget(self.card)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(s(6), s(6), s(6), s(6))
        lay.setSpacing(0)
        for text, callback in self._actions:
            btn = QPushButton(text)
            btn.setObjectName("actionPopupItem")
            btn.setFixedHeight(s(34))
            btn.clicked.connect(lambda _checked=False, cb=callback: self._trigger(cb))
            lay.addWidget(btn)

    def _trigger(self, callback):
        # 与 EditContextMenu._trigger 同款防护：本类若带 WA_DeleteOnClose，
        # close() 后再被触发（回调链多包一层 / Qt 已先行关闭 popup）会抛
        # RuntimeError: wrapped C/C++ object ... has been deleted，故吞掉异常、
        # 保证业务回调照常异步执行。
        try:
            self.close()
        except RuntimeError:
            pass
        QTimer.singleShot(0, callback)

    def show_at(self, global_pos):
        parent = self.parentWidget()
        if parent is not None:
            old = getattr(parent, "_active_action_popup", None)
            if old is not None and old is not self:
                try:
                    old.close()
                except RuntimeError:
                    pass
            parent._active_action_popup = self
            self.destroyed.connect(lambda _obj=None, p=parent: setattr(p, "_active_action_popup", None))
            local = parent.mapFromGlobal(global_pos)
            max_x = max(0, parent.width() - self.width() - 6)
            max_y = max(0, parent.height() - self.height() - 6)
            self.move(max(6, min(local.x(), max_x)), max(6, min(local.y(), max_y)))
        else:
            self.move(global_pos)
        self.show()
        self.raise_()
        # 安装全局事件过滤器：点菜单外部 / 按 Esc / 父窗口失活 时自动关闭
        QApplication.instance().installEventFilter(self)
        return self

    def closeEvent(self, e):  # noqa: N802
        try:
            QApplication.instance().removeEventFilter(self)
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(e)

    def eventFilter(self, obj, event):  # noqa: N802
        """让普通 QWidget 弹层获得「点击外部即消失」的能力（QMenu 原生就有，
        ActionPopupMenu 是自定义 QWidget，需要自己处理）。

        覆盖三种场景：
        - 鼠标按下/抬起落在菜单之外 → 关闭；
        - 按 Esc → 关闭，并吞掉该事件，避免被父窗口当成「关闭整个窗口」；
        - 父窗口失活（切到别的程序）→ 关闭。

        注意：本过滤器装在 QApplication 上是**全局**过滤器，部分事件的 obj 可能是
        QWindow（例如实机里 WindowDeactivate、以及点击落在非 QWidget 区域时），
        QWindow 不是 QWidget，调用 isAncestorOf 会抛 TypeError —— 必须先 isinstance 判定。
        """
        et = event.type()
        if et == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.close()
            return True
        if et in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            # 菜单内部（含卡片与按钮）的点击不关闭；obj 可能是 QWindow，先 isinstance 判定
            inside = obj is self or (isinstance(obj, QWidget) and self.isAncestorOf(obj))
            if inside:
                return False
            gp = (event.globalPosition().toPoint()
                  if hasattr(event, "globalPosition") else event.globalPos())
            rect = QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
            if not rect.contains(gp):
                self.close()
            return False
        if et == QEvent.Type.WindowDeactivate:
            # 实机里 WindowDeactivate 的 obj 是 QWindow；用「父窗口是否仍是活动窗口」判断，
            # 既绕开 obj 类型问题，又能正确覆盖「切到别的程序/别的窗口」。
            pw = self.parentWidget()
            if pw is not None and (obj is pw or QApplication.activeWindow() is not pw):
                self.close()
            return False
        return super().eventFilter(obj, event)


def _style_menu(menu):
    menu.setStyleSheet(MENU_QSS)
    menu.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
    menu.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    menu.aboutToShow.connect(lambda m=menu: keep_on_top(m, bring_to_front=True))
    return menu


def _action(parent, text, data):
    a = QAction(text, parent)
    a.setData(data)
    return a


def _submenu(parent, text):
    sub = parent.addMenu(text)
    return _style_menu(sub)


def build_menu(parent):
    menu = _style_menu(QMenu(parent))

    drinks = config.character.drinks.get("categoryList", [])

    # 喝酒 -> 酒类
    jiula = next((c for c in drinks if c["category"] == "酒类"), None)
    if jiula:
        sub = _submenu(menu, "🍺  " + tr("喝酒"))
        for it in jiula["items"]:
            if "不显示" in it.get("desc", ""):
                continue
            sub.addAction(_action(sub, tr(it["name"]),
                                  {"kind": "drink", "category": "酒类", "item": it}))

    # 喝茶 -> 茶类
    chalei = next((c for c in drinks if c["category"] == "茶类"), None)
    if chalei:
        sub = _submenu(menu, "🍵  " + tr("喝茶"))
        for it in chalei["items"]:
            sub.addAction(_action(sub, tr(it["name"]),
                                  {"kind": "drink", "category": "茶类", "item": it}))

    # 喝饮料 -> 咖啡 / 奶（果）茶
    coffee = next((c for c in drinks if c["category"] == "咖啡"), None)
    milktea = next((c for c in drinks if c["category"] == "奶（果）茶"), None)
    if coffee or milktea:
        sub = _submenu(menu, "🥤  " + tr("喝饮料"))
        if coffee:
            s2 = _submenu(sub, "☕  " + tr("咖啡"))
            for it in coffee["items"]:
                s2.addAction(_action(s2, tr(it["name"]),
                                     {"kind": "drink", "category": "咖啡", "item": it}))
        if milktea:
            s2 = _submenu(sub, "🧋  " + tr("奶（果）茶"))
            for it in milktea["items"]:
                s2.addAction(_action(s2, tr(it["name"]),
                                     {"kind": "drink", "category": "奶（果）茶", "item": it}))

    menu.addSeparator()

    # 换装
    costume_sub = _submenu(menu, "👕  " + tr("换装"))
    for c in config.character.costume.get("itemList", []):
        costume_sub.addAction(_action(costume_sub, tr(c["name"]),
                                      {"kind": "outfit", "name": c["name"]}))

    # 工作
    work_sub = _submenu(menu, "💼  " + tr("工作"))
    for w in config.character.work.get("itemList", []):
        work_sub.addAction(_action(work_sub, tr(w["name"]),
                                   {"kind": "work", "name": w["name"]}))

    # 居家
    home_sub = _submenu(menu, "🏠  " + tr("居家"))
    for h in config.character.home.get("itemList", []):
        home_sub.addAction(_action(home_sub, tr(h["name"]),
                                   {"kind": "home", "name": h["name"]}))

    menu.addSeparator()

    for icon, label, kind in [("📋", "待办", "todo"), ("⏰️", "闹钟", "alarm"),
                              ("⏱️", "计时", "timer"), ("👻", "隐身", "hide"),
                              ("⚙️", "设置", "settings"), ("🚪", "退出", "exit")]:
        menu.addAction(_action(menu, f"{icon}  {tr(label)}", {"kind": kind}))

    return menu
