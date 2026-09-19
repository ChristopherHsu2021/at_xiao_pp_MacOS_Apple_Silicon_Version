"""闹钟持久化与触发判定。

存储于 data/alarms.json。字段：
{ id, hour, minute, repeat("once"/"daily"/"weekdays"/"custom"),
  custom_days:[0-6], ringtone:str|None, custom_text:str|None, enabled:bool, last:str }
重复：仅一次(指定日期) / 每天 / 工作日(周一~周五) / 自定义(星期集合)。
"""

import json
import time
from datetime import datetime, timedelta

from app.core import pathutil

PATH = pathutil.data_file("alarms.json")
MIN_REMINDER_LEAD_SECONDS = 180


def load() -> list:
    try:
        with open(PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: E501
        return []


def save(alarms: list):
    try:
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(alarms, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: E501
        pass


def _parse_once_datetime(once_date: str | None, hour: int, minute: int) -> datetime | None:
    if not once_date:
        return None
    try:
        return datetime.strptime(f"{once_date} {int(hour):02d}:{int(minute):02d}", "%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return None


def next_fire_datetime(alarm: dict, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now()
    hour = int(alarm.get("hour", 7))
    minute = int(alarm.get("minute", 0))
    rep = alarm.get("repeat", "daily")
    if rep == "once":
        dt = _parse_once_datetime(alarm.get("once_date"), hour, minute)
        return dt
    base = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if rep == "daily":
        return base if base >= now else base + timedelta(days=1)
    days = []
    if rep == "weekdays":
        days = [0, 1, 2, 3, 4]
    elif rep == "custom":
        days = sorted({int(d) for d in alarm.get("custom_days", []) if 0 <= int(d) <= 6})
    else:
        return base if base >= now else base + timedelta(days=1)
    if not days:
        return None
    for offset in range(8):
        cand = base + timedelta(days=offset)
        if cand < now:
            continue
        if cand.weekday() in days:
            return cand
    return None


def validate_schedule(alarm: dict, now: datetime | None = None) -> tuple[bool, str]:
    now = now or datetime.now()
    due = next_fire_datetime(alarm, now)
    if due is None:
        return False, "提醒时间无效"
    if due < now + timedelta(seconds=MIN_REMINDER_LEAD_SECONDS):
        return False, "提醒时间至少要在系统时间3分钟后"
    return True, ""


def add(**kwargs) -> dict:
    alarms = load()
    item = {
        "id": int(time.time() * 1000),
        "hour": kwargs.get("hour", 7),
        "minute": kwargs.get("minute", 0),
        "repeat": kwargs.get("repeat", "daily"),
        "once_date": kwargs.get("once_date"),
        "custom_days": kwargs.get("custom_days", []),
        "ringtone": kwargs.get("ringtone"),
        "custom_text": kwargs.get("custom_text"),
        "source": kwargs.get("source"),
        "enabled": kwargs.get("enabled", True),
        "last": "",
    }
    alarms.append(item)
    save(alarms)
    return item


def update(alarm_id, **kwargs):
    alarms = load()
    for a in alarms:
        if a["id"] == alarm_id:
            a.update(kwargs)
            save(alarms)
            if a.get("source") == "todo":
                try:
                    from app.core import todo
                    todo.sync_from_alarm(a)
                except Exception:  # noqa: BLE001
                    pass
            return a
    return None


def delete(alarm_id):
    alarms = load()
    removed = next((a for a in alarms if a.get("id") == alarm_id), None)
    left = [a for a in alarms if a["id"] != alarm_id]
    save(left)
    if removed:
        # 关联待办的提醒同步取消，避免待办页面继续显示已失效时间。
        try:
            from app.core import todo
            tasks = todo.load()
            changed = False
            for task in tasks:
                if task.get("alarm_id") == alarm_id:
                    task["alarm_id"] = None
                    task["remind"] = None
                    task["remind_enabled"] = False
                    changed = True
            if changed:
                todo.save(tasks)
        except Exception:  # noqa: BLE001
            pass


def should_ring(alarm: dict, now: datetime) -> bool:
    if not alarm.get("enabled", True):
        return False
    rep = alarm.get("repeat", "daily")
    wd = now.weekday()
    ok = False
    if rep == "daily":
        ok = True
    elif rep == "weekdays":
        ok = wd <= 4
    elif rep == "custom":
        ok = wd in alarm.get("custom_days", [])
    elif rep == "once":
        ok = alarm.get("once_date") == now.strftime("%Y-%m-%d")
    if not ok:
        return False

    # 调度器每 20 秒检查一次，不能要求恰好落在目标分钟内，
    # 否则检查点从 12:34:50 跳到 12:35:10 时会漏掉 12:35 的闹钟。
    due = now.replace(
        hour=int(alarm["hour"]),
        minute=int(alarm["minute"]),
        second=0,
        microsecond=0,
    )
    # 只接受目标时间后 1 分钟内的检查，避免应用启动或调度延迟时
    # 把当天更早的所有闹钟一次性补播出来。
    if now < due or now >= due + timedelta(minutes=1):
        return False
    key = now.strftime("%Y-%m-%d %H:%M")
    if alarm.get("last") == key:
        return False
    return True


def mark_rung(alarm: dict, now: datetime):
    key = now.strftime("%Y-%m-%d %H:%M")
    alarm["last"] = key
    alarms = load()
    for a in alarms:
        if a["id"] == alarm["id"]:
            a["last"] = key
            break
    save(alarms)
