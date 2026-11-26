"""Plain-language explanations that cannot invent numbers.

The language model may only *phrase* verified facts. After it answers, every
number in its text is checked against the facts it was given ("number guard").
If any number is unaccounted for, the answer is thrown away and a safe
template explanation is shown instead, with the reason logged.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .catalog import TESTS
from .trends import Trend
from .verify import Result, unit_label

DISCLAIMER = ("This is an explanation of your report, not a diagnosis. "
              "Please discuss any out-of-range values with your doctor.")


def fmt(x: float | None) -> str:
    if x is None:
        return "-"
    return f"{x:.2f}".rstrip("0").rstrip(".") if abs(x) < 100 else f"{x:.0f}"


def range_text(r: Result) -> str:
    if r.ref_low is not None and r.ref_high is not None:
        return f"{fmt(r.ref_low)}-{fmt(r.ref_high)}"
    if r.ref_high is not None:
        return f"below {fmt(r.ref_high)}"
    if r.ref_low is not None:
        return f"above {fmt(r.ref_low)}"
    return "not given"


# ------------------------------------------------------------------- facts

def facts(results: list[Result], trends: dict[str, Trend] | None = None) -> dict:
    trends = trends or {}
    items = []
    for r in results:
        item = {
            "test": r.name,
            "value": fmt(r.value),
            "unit": unit_label(r.unit),
            "normal_range": range_text(r),
            "status": r.status,
            "what_it_is": TESTS[r.test_key].about,
        }
        t = trends.get(r.test_key)
        if t and t.change is not None:
            item["trend"] = {
                "first_value": fmt(t.points[0].value),
                "first_date": t.points[0].when.strftime("%b %Y"),
                "reports": len(t.points),
                "rising_reports_in_a_row": t.rising_streak,
                "falling_reports_in_a_row": t.falling_streak,
            }
            if t.months_to_limit is not None:
                item["trend"]["months_until_limit_at_current_rate"] = fmt(round(t.months_to_limit))
        items.append(item)
    return {"results": items}


# --------------------------------------------------------------- templates

def template_lines(results: list[Result], trends: dict[str, Trend] | None = None) -> list[str]:
    trends = trends or {}
    out = []
    order = {"high": 0, "low": 0, "normal": 1}
    for r in sorted(results, key=lambda r: order[r.status]):
        u = unit_label(r.unit)
        s = f"**{r.name}: {fmt(r.value)} {u}** (normal: {range_text(r)}) is **{r.status}**."
        t = trends.get(r.test_key)
        if t and t.months_to_limit is not None:
            s += (f" It is still in range, but has moved the same way in {t.rising_streak or t.falling_streak} "
                  f"reports in a row; at this rate it would reach the {t.limit_side} limit in about "
                  f"{fmt(round(t.months_to_limit))} months.")
        elif t and t.newly_abnormal:
            s += " It was in range on the previous report."
        if r.status != "normal":
            s += f" {TESTS[r.test_key].about}"
        out.append(s)
    return out


def doctor_questions(results: list[Result], trends: dict[str, Trend] | None = None) -> list[str]:
    trends = trends or {}
    qs = []
    for r in results:
        t = trends.get(r.test_key)
        if r.status != "normal":
            qs.append(f"My {r.name} is {r.status} ({fmt(r.value)} {unit_label(r.unit)}). "
                      f"What could be causing this, and does it need a repeat test?")
        elif t and t.months_to_limit is not None:
            qs.append(f"My {r.name} has been moving toward the {t.limit_side} limit over "
                      f"{len(t.points)} reports. Should I do anything now?")
    return qs


# --------------------------------------------------------------- LLM + guard

LLM_EXPLAIN_PROMPT = """Explain these verified blood-test results to a family member with no medical background.
Write in {language}. Use short sentences. Start with anything out of range or trending, then the rest briefly.
STRICT RULES:
- Use ONLY numbers that appear in the JSON below. Do not calculate, convert, round or add any number.
- Do not diagnose, do not name diseases the person "has", do not suggest medicines or doses.
- End by suggesting they discuss out-of-range or trending values with their doctor.

JSON:
{facts}"""

_NUM = re.compile(r"\d+(?:[.,]\d+)?")


@dataclass
class GuardResult:
    ok: bool
    text: str
    unknown_numbers: list[str]


def number_guard(text: str, fact_json: dict) -> GuardResult:
    allowed = set()
    for n in _NUM.findall(json.dumps(fact_json, ensure_ascii=False)):
        f = float(n.replace(",", ""))
        allowed.update({f, round(f, 1), round(f)})
    unknown = []
    for n in _NUM.findall(text):
        f = float(n.replace(",", "."))
        if f not in allowed and round(f, 1) not in allowed:
            unknown.append(n)
    return GuardResult(not unknown, text, unknown)


def llm_explain(results, trends, language: str, llm) -> tuple[str, GuardResult]:
    fj = facts(results, trends)
    text = llm(LLM_EXPLAIN_PROMPT.format(language=language, facts=json.dumps(fj, indent=1, ensure_ascii=False)))
    return text, number_guard(text, fj)
