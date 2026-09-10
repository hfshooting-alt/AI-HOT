"""固定北京时间窗口（保留旧函数名）；边界采用 [start, end)，相邻批次不重叠。"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import os

BJ = ZoneInfo("Asia/Shanghai")


def cutoff_time():
    """Legacy direct callers use 10:00; the unified daily CLI sets 09:30."""
    value = os.environ.get('AIHOT_CUTOFF_TIME', '10:00')
    if len(value) != 5 or value[2] != ':':
        raise ValueError('AIHOT_CUTOFF_TIME must be HH:MM')
    return time.fromisoformat(value)


def ten_am_window(end_date: str) -> dict:
    day = date.fromisoformat(end_date)
    end = datetime.combine(day, cutoff_time(), tzinfo=BJ)
    return {"start": (end - timedelta(days=1)).isoformat(), "end": end.isoformat(),
            "timezone": "Asia/Shanghai"}


def latest_cutoff_date(now: datetime | None = None) -> str:
    now = (now or datetime.now(BJ)).astimezone(BJ)
    day = now.date() if now.time().replace(tzinfo=None) >= cutoff_time() else now.date() - timedelta(days=1)
    return day.isoformat()


def timestamp(value: str) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("发布时间必须含日期、时间和时区")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("发布时间缺少时区")
    return dt.astimezone(BJ)


def contains(window: dict, value: str) -> bool:
    return timestamp(window["start"]) <= timestamp(value) < timestamp(window["end"])


def matching_item(window: dict, item: dict) -> bool:
    if item.get("publishedPrecision") == "date":
        return False
    try:
        return contains(window, item.get("publishedAt"))
    except (ValueError, TypeError):
        return False
