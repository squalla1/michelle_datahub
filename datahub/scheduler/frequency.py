"""Translate the Chinese `频率` column into APScheduler trigger specs.

Observed values: 实时 / 高频 / 10-15分钟 / 每15分钟 / 每5分钟 / 每日 /
每周 / 每周/每日 / 每月 / 每季 / 每年 / 不定期 / 偶尔 / 按provider / (blank).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import get_settings

_MIN_RE = re.compile(r"(\d+)\s*[-–~]?\s*(\d+)?\s*分钟")


@dataclass(frozen=True)
class TriggerSpec:
    kind: str                  # "interval" | "cron" | "manual"
    seconds: int | None = None         # for interval
    cron: dict | None = None           # kwargs for CronTrigger
    label: str = ""

    @property
    def schedulable(self) -> bool:
        return self.kind != "manual"


def parse_frequency(freq: str | None) -> TriggerSpec:
    s = get_settings()
    text = (freq or "").strip()

    if not text:
        return TriggerSpec("manual", label="unspecified")

    # Realtime / high-frequency -> short interval poll.
    if any(k in text for k in ("实时", "高频")):
        return TriggerSpec("interval", seconds=s.realtime_interval_seconds, label="realtime")

    # Explicit "N分钟" (possibly a range like 10-15分钟 -> take the lower bound).
    m = _MIN_RE.search(text)
    if m:
        minutes = int(m.group(1))
        seconds = max(minutes * 60, s.min_interval_seconds)
        return TriggerSpec("interval", seconds=seconds, label=f"{minutes}min")

    # Calendar cadences. "每周/每日" and similar slashes -> pick the finer one.
    if "每日" in text or "每天" in text:
        return TriggerSpec("cron", cron={"hour": 6, "minute": 0}, label="daily")
    if "每周" in text:
        return TriggerSpec("cron", cron={"day_of_week": "mon", "hour": 6, "minute": 0}, label="weekly")
    if "每月" in text:
        return TriggerSpec("cron", cron={"day": 1, "hour": 6, "minute": 0}, label="monthly")
    if "每季" in text:
        return TriggerSpec("cron", cron={"month": "1,4,7,10", "day": 1, "hour": 6}, label="quarterly")
    if "每年" in text:
        return TriggerSpec("cron", cron={"month": 1, "day": 1, "hour": 6}, label="yearly")

    # 不定期 / 偶尔 / 按provider -> manual (only run on demand).
    return TriggerSpec("manual", label="on-demand")
