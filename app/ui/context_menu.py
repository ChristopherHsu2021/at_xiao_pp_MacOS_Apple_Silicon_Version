"""右键多级菜单构造（纯构建，动作数据通过 QAction.data 携带）。

菜单结构完全依据开发需求文档：
喝酒(酒类) / 喝茶(茶类) / 喝饮料(咖啡, 奶（果）茶) / 换装 / 工作 / 居家 / 待办 / 闹钟 / 计时 / 隐身 / 设置 / 退出
尼格罗尼 在文档中标注『此处不显示』，故跳过。
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QMenu, QPushButton, QVBoxLayout, QWidget
from PyQt6.QtGui import QAction
from PyQt6.QtGui import QColor

from app.core import config
from app.core.i18n import tr
from app.ui.common import keep_on_top

MENU_QSS = """
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
"""


ACTION_POPUP_QSS = """
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
"""


class ActionPopupMenu(QWidget):
    def __init__(self, parent, actions):
        super().__init__(parent)
        self._actions = list(actions)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        width = max(104, max((len(text) for text, _callback in self._actions), default=2) * 16 + 34)
        height = 12 + len(self._actions) * 34
        self.setFixedSize(width, height)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.card = QWidget(self)
        self.card.setObjectName("actionPopupCard")
        self.card.setStyleSheet(ACTION_POPUP_QSS)
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(180, 120, 50, 34))
        self.card.setGraphicsEffect(shadow)
        root.addWidget(self.card)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(0)
        for text, callback in self._actions:
            btn = QPushButton(text)
            btn.setObjectName("actionPopupItem")
            btn.setFixedHeight(34)
            btn.clicked.connect(lambda _checked=False, cb=callback: self._trigger(cb))
            lay.addWidget(btn)

    def _trigger(self, callback):
        self.close()
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
        return self


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
                              ("⏱️", "计时", "timer"),
                              ("⚙️", "设置", "settings"), ("🚪", "退出", "exit")]:
        menu.addAction(_action(menu, f"{icon}  {tr(label)}", {"kind": kind}))

    return menu
