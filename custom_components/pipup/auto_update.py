"""Quiet-window arithmetic for automatic app updates."""
from __future__ import annotations

from datetime import datetime, time, timedelta


def parse_time(value: str, default: str) -> time:
    """"HH:MM[:SS]" from the options (a TimeSelector stores HH:MM:SS)."""
    for text in (value, default):
        try:
            return time.fromisoformat(text)
        except (TypeError, ValueError):
            continue
    raise ValueError(default)


def window_start(now: datetime, start: time, end: time) -> datetime | None:
    """Start of the quiet window `now` falls in, or None outside it.

    The start identifies the night: one attempt per window, so a failure retries
    the next night instead of every few minutes. A window may cross midnight
    (23:00-02:00); start == end means the whole day.
    """
    today = now.replace(hour=start.hour, minute=start.minute, second=start.second,
                        microsecond=0)
    if start == end:
        return today if now >= today else today - timedelta(days=1)
    if start < end:
        end_today = today.replace(hour=end.hour, minute=end.minute, second=end.second)
        return today if today <= now < end_today else None
    # crosses midnight
    if now >= today:
        return today
    end_today = today.replace(hour=end.hour, minute=end.minute, second=end.second)
    return today - timedelta(days=1) if now < end_today else None
