"""Turn several reports into a health timeline and early warnings.

A single report tells you where you are. A series tells you where you are
heading. The most useful signal is a value that is still "normal" but moving
steadily toward the edge of its range.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from .verify import Result


@dataclass
class Point:
    when: date
    value: float
    status: str
    ref_low: float | None
    ref_high: float | None
    source: str  # report file name


@dataclass
class Trend:
    test_key: str
    name: str
    unit: str
    points: list[Point]
    change: float | None = None          # last - first
    change_pct: float | None = None
    per_year: float | None = None         # linear-fit slope
    rising_streak: int = 0                # consecutive increases ending at latest
    falling_streak: int = 0
    newly_abnormal: bool = False
    months_to_limit: float | None = None  # early warning, if heading out of range
    limit_side: str | None = None


def build(reports: list[tuple[str, date, list[Result]]]) -> dict[str, Trend]:
    series: dict[str, Trend] = {}
    for src, when, results in sorted(reports, key=lambda r: r[1]):
        for r in results:
            t = series.setdefault(r.test_key, Trend(r.test_key, r.name, r.unit, []))
            t.points.append(Point(when, r.value, r.status, r.ref_low, r.ref_high, src))
    for t in series.values():
        _analyse(t)
    return series


def _analyse(t: Trend) -> None:
    p = t.points
    if len(p) < 2:
        return
    first, last = p[0].value, p[-1].value
    t.change = last - first
    t.change_pct = (t.change / first * 100) if first else None

    days = np.array([(x.when - p[0].when).days for x in p], dtype=float)
    vals = np.array([x.value for x in p])
    if days[-1] > 0:
        t.per_year = float(np.polyfit(days, vals, 1)[0] * 365.25)

    for i in range(len(p) - 1, 0, -1):
        if p[i].value > p[i - 1].value:
            t.rising_streak += 1
        else:
            break
    for i in range(len(p) - 1, 0, -1):
        if p[i].value < p[i - 1].value:
            t.falling_streak += 1
        else:
            break

    t.newly_abnormal = p[-1].status != "normal" and p[-2].status == "normal"

    # Early warning: currently normal, trending steadily toward a limit.
    cur = p[-1]
    if cur.status == "normal" and t.per_year:
        if t.per_year > 0 and cur.ref_high is not None and t.rising_streak >= 2:
            months = (cur.ref_high - cur.value) / t.per_year * 12
            if 0 <= months <= 24:
                t.months_to_limit, t.limit_side = months, "upper"
        elif t.per_year < 0 and cur.ref_low is not None and t.falling_streak >= 2:
            months = (cur.value - cur.ref_low) / -t.per_year * 12
            if 0 <= months <= 24:
                t.months_to_limit, t.limit_side = months, "lower"
