"""待办持久化与每周一清理。

存储于 data/todos.json。任务可带选填提醒时间（后台按时间触发，复用闹钟调度）。
每周一凌晨 0 点清理全部任务：启动时与每分钟调度时检测『本周周一』是否变化。
"""

import json
import os
import time
from datetime import datetime, timedelta

from app.core import pathutil, config
from app.core import alarm as alarm_mod

PATH = pathutil.data_file("todos.json")


def _monday_key() -> str:
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime("%Y-%m-%d")


def load() -> list:
    try:
        with open(PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return []


def save(tasks: list):
    try:
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


def add(title: str, content: str, remind: str = None, alarm_id=None,
        priority: str = "中") -> dict:
    """新增任务。title 为纯文本标题；content 为富文本 HTML；priority 为 低/中/高。"""
    tasks = load()
    item = {
        "id": int(time.time() * 1000),
        "title": title,
        "content": content,
        "priority": priority,
        "done": False,
        "remind": remind,
        "remind_enabled": remind is not None,
        "alarm_id": alarm_id,
    }
    tasks.append(item)
    save(tasks)
    return item


def toggle(tid) -> bool:
    tasks = load()
    for t in tasks:
        if t["id"] == tid:
            t["done"] = not t["done"]
            # 完成任务即结束提醒，关联闹钟直接移除，避免闹钟页残留。
            if t["done"] and t.get("alarm_id"):
                alarm_mod.delete(t["alarm_id"])
                t["alarm_id"] = None
                t["remind"] = None
            save(tasks)
            return t["done"]
    return False


def delete_done() -> int:
    tasks = load()
    for t in tasks:
        if t.get("done") and t.get("alarm_id"):
            alarm_mod.delete(t["alarm_id"])
    left = [t for t in tasks if not t["done"]]
    removed = len(tasks) - len(left)
    save(left)
    return removed


def delete_task(tid) -> bool:
    tasks = load()
    removed = None
    left = []
    for task in tasks:
        if task.get("id") == tid:
            removed = task
            continue
        left.append(task)
    if removed is None:
        return False
    if removed.get("alarm_id"):
        alarm_mod.delete(removed["alarm_id"])
    save(left)
    return True


def update_task(tid, title: str, content: str, remind: str = None, alarm_id=None,
                remind_enabled: bool | None = None, priority: str | None = None) -> dict | None:
    tasks = load()
    for task in tasks:
        if task.get("id") == tid:
            task["title"] = title
            task["content"] = content
            if priority is not None:
                task["priority"] = priority
            task["remind"] = remind
            task["alarm_id"] = alarm_id
            if remind_enabled is not None:
                task["remind_enabled"] = bool(remind_enabled)
            save(tasks)
            return task
    return None


def set_reminder_enabled(alarm_id, enabled: bool) -> bool:
    """同步关联待办的提醒开关，保留提醒时间与闹钟关联。"""
    tasks = load()
    changed = False
    for task in tasks:
        if task.get("alarm_id") == alarm_id:
            task["remind_enabled"] = bool(enabled)
            changed = True
    if changed:
        save(tasks)
    return changed


def sync_from_alarm(alarm: dict) -> bool:
    """把闹钟页的最新时间/内容回写到来源待办。"""
    if alarm.get("source") != "todo":
        return False
    tasks = load()
    changed = False
    remind = None
    if alarm.get("enabled", True):
        due = alarm_mod.next_fire_datetime(alarm)
        if due is not None:
            remind = due.strftime("%Y-%m-%d %H:%M")
    for task in tasks:
        if task.get("alarm_id") == alarm.get("id"):
            task["remind_enabled"] = bool(alarm.get("enabled", True))
            if remind is not None:
                task["remind"] = remind
            if alarm.get("custom_text"):
                # 新任务以标题为主显示，回写标题；旧任务无标题字段则回写内容。
                if "title" in task:
                    task["title"] = alarm["custom_text"]
                else:
                    task["content"] = alarm["custom_text"]
            changed = True
    if changed:
        save(tasks)
    return changed


def all_tasks() -> list:
    return load()


def get_task(tid) -> dict | None:
    """按 id 取单个任务（便签窗口双向同步时实时读取最新 done 状态用）。"""
    for t in load():
        if t["id"] == tid:
            return t
    return None


def set_done(tid, done: bool) -> bool:
    """把指定任务置为 done（便签窗口与列表项双向同步的唯一持久化入口）。

    与 toggle 不同：set_done 设定为明确的目标值，避免「列表勾选」与「便签确认」
    两个入口互相抵消。完成任务即结束提醒（移除关联闹钟），与 toggle 行为一致。
    """
    tasks = load()
    for t in tasks:
        if t["id"] == tid:
            target = bool(done)
            if t["done"] == target:
                return t["done"]
            t["done"] = target
            if t["done"] and t.get("alarm_id"):
                alarm_mod.delete(t["alarm_id"])
                t["alarm_id"] = None
                t["remind"] = None
            save(tasks)
            return t["done"]
    return False


def set_note(tid, title: str, content: str) -> bool:
    """便签窗口关闭/改标题时回写标题与富文本内容（不影响提醒/优先级/闹钟）。"""
    tasks = load()
    for t in tasks:
        if t["id"] == tid:
            t["title"] = title
            t["content"] = content
            save(tasks)
            return True
    return False


def cleanup_weekly() -> bool:
    """若跨过本周周一，清空全部任务并刷新标记。返回是否发生了清理。"""
    key = _monday_key()
    last = config.settings.get("lastCleanupWeek", "")
    if last != key:
        config.settings.set("lastCleanupWeek", key)
        if os.path.exists(PATH):
            try:
                os.remove(PATH)
            except Exception:  # noqa: BLE001
                pass
        for alarm in alarm_mod.load():
            if alarm.get("source") == "todo":
                alarm_mod.delete(alarm["id"])
        return True
    return False
