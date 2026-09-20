"""任务数据变更的全局信号总线（解耦三处视图：任务清单页 / TodoDock / 便签页）。

为什么需要它
------------
AT小PP 有三处都能看到同一任务的「标题渲染」（清单行 / TodoDock 行 / 便签标题）：
勾选或取消（done 状态）从**任意入口**（列表行复选框、Dock 行复选框、便签确认键）
改持久化后，另外两处的标题删除线/置灰必须**即刻同步**——否则用户在一处勾掉，
另一处还亮着，看起来像「没生效」。

旧链路是半残的：列表勾选靠 `notify_sticky` 通知便签、靠 `_render()` 重建整表顺带刷新
Dock；但 Dock 勾选时没有 `notify_sticky`，便签不会动；且整表销毁重建既不即时也
有闪动。统一用信号总线后：done 一变就广播，三处各自**就地**刷新自己那一条，互不依赖
对方的刷新路径，断哪条都不会再「漏一处」。

接入约定
--------
- 持久化入口（``todo.toggle`` / ``todo.set_done``）在 save 之后 ``bus().done_changed.emit(tid, done)``。
- 三处视图在 ``__init__`` 里 ``bus().done_changed.connect(self._on_done_changed,
  Qt.ConnectionType.UniqueConnection)``，处理器**只刷新自己这条任务**，不做整表重建。
- 信号源自己那一行也会收到信号，处理函数须幂等（done 没变就早退）。
- 视图销毁时 PyQt 自动断开连接（接收者被删），无需手动 disconnect。
"""

from PyQt6.QtCore import QObject, pyqtSignal


class TodoBus(QObject):
    # (tid, done) —— 任务完成态变化（勾选 / 取消）。
    # 注意：tid 用 ``object`` 而非 ``int`` —— 任务的 id 是 ``int(time.time()*1000)``
    # （≈1.7e12），远超 C++ ``int`` 的 32 位有符号上限，用 ``int`` 会被截断成负数，
    # 导致各视图按 tid 查找行时永远匹配不上、同步静默失效。``object`` 按 Python 对象
    # 原样透传，无截断风险。
    done_changed = pyqtSignal(object, bool)
    # (tid,) —— 任务标题/内容/优先级/提醒被编辑，需刷新对应行的展示
    task_edited = pyqtSignal(object)


_bus = None


def bus() -> TodoBus:
    """惰性取全局总线单例。

    推迟到首次使用时再实例化 ``TodoBus``，避免「QObject 早于 QApplication 创建」的
    PyQt 告警（模块被导入时往往还没建 app）。
    """
    global _bus
    if _bus is None:
        _bus = TodoBus()
    return _bus
