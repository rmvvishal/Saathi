"""The trust layer.

A candidate result is only shown to the user if it passes every check below.
Each failed check produces a human-readable reason that is logged in the UI, so
nothing is silently dropped and nothing unverified is silently shown.

Status (low / normal / high) is computed here with plain arithmetic, never by
the language model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .catalog import TESTS, to_canonical, normalise_unit, alias_index
from .extract import Candidate, Document, _RANGE_PATTERNS

NUM_RE = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class Result:
    test_key: str
    name: str
    value: float              # canonical unit
    unit: str                 # canonical unit
    printed: str              # e.g. "6.9 mmol/L" as printed on the report
    ref_low: float | None     # canonical unit
    ref_high: float | None
    range_source: str         # "report" or "default"
    status: str               # "low" | "normal" | "high"
    line_no: int
    quote: str
    method: str


@dataclass
class Rejection:
    test_key: str
    line_no: int
    quote: str
    reasons: list[str]
    method: str


@dataclass
class Verified:
    results: list[Result] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)


def _numbers_in(text: str) -> set[str]:
    return set(NUM_RE.findall(text))


def _same_num(a: str, b: float) -> bool:
    try:
        return abs(float(a) - b) < 1e-9
    except ValueError:
        return False


def check(c: Candidate, doc: Document) -> tuple[Result | None, list[str]]:
    reasons: list[str] = []
    test = TESTS.get(c.test_key)
    if test is None:
        return None, [f"unknown test '{c.test_key}'"]

    # 1. Provenance: the cited line must exist and be the real text of the report.
    line = doc.line(c.line_no)
    if line is None:
        return None, [f"cites line {c.line_no}, which does not exist in the report"]
    if c.quote and c.quote != line.text:
        reasons.append("quoted text does not match the report")

    # 2. The test name must actually be on that line.
    #    Mask longer names of OTHER tests first, so "cholesterol" does not match
    #    inside "HDL cholesterol" and "Hb" does not match inside "HbA1c".
    low = line.text.lower()
    masked = low
    for alias, key in alias_index():
        if key != test.key and any(a in alias for a in test.aliases):
            masked = masked.replace(alias, " ")
    if not any(re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", masked) for a in test.aliases):
        reasons.append(f"'{test.name}' is not mentioned on line {c.line_no}")

    # 3. The value must be printed on that line, exactly.
    try:
        raw_val = float(c.value_str)
    except ValueError:
        return None, reasons + [f"value '{c.value_str}' is not a number"]
    # Ignore digits that belong to the test's own name ("HbA1c", "Vitamin B12", "25-OH").
    stripped = low
    for a in sorted(test.aliases, key=len, reverse=True):
        stripped = stripped.replace(a, " ")
    nums = _numbers_in(stripped)
    # The result itself must appear OUTSIDE the reference-range text, otherwise a
    # model could "read" the limit (e.g. "< 5.7") as the patient's value.
    value_zone = stripped
    for pat, _ in _RANGE_PATTERNS:
        hits = list(pat.finditer(value_zone))
        if hits:
            m = hits[-1]
            value_zone = value_zone[:m.start()] + " " + value_zone[m.end():]
            break
    value_nums = _numbers_in(value_zone)
    if not any(_same_num(n, raw_val) for n in value_nums):
        reasons.append(f"value {c.value_str} is not printed on line {c.line_no}")

    # 4. Reference range numbers (if any) must also be printed on that line.
    for bound in (c.ref_low, c.ref_high):
        if bound is not None and not any(_same_num(n, bound) for n in nums):
            reasons.append(f"reference bound {bound:g} is not printed on line {c.line_no}")

    # 5. Unit must be printed on the line and known, so we compare like with like.
    if c.unit and normalise_unit(c.unit) not in normalise_unit(line.text):
        reasons.append(f"unit '{c.unit}' is not printed on line {c.line_no}")
    canon = to_canonical(test, raw_val, c.unit)
    if canon is None:
        reasons.append(f"unit '{c.unit}' is not recognised for {test.name}")

    # 6. Physiological plausibility (catches misreads like 140 -> 1400).
    if canon is not None and not (test.plausible[0] <= canon <= test.plausible[1]):
        reasons.append(f"{canon:.4g} {test.unit} is outside what is physiologically possible")

    if reasons:
        return None, reasons

    # Reference range: prefer the report's own; fall back to catalog default.
    if c.ref_low is not None or c.ref_high is not None:
        lo = to_canonical(test, c.ref_low, c.unit) if c.ref_low is not None else None
        hi = to_canonical(test, c.ref_high, c.unit) if c.ref_high is not None else None
        source = "report"
    else:
        lo, hi = test.default_range
        source = "default"

    status = "normal"
    if lo is not None and canon < lo - 1e-9:
        status = "low"
    elif hi is not None and canon > hi + 1e-9:
        status = "high"

    printed = f"{c.value_str} {c.unit}".strip()
    return Result(test.key, test.name, round(canon, 3), test.unit, printed, lo, hi, source,
                  status, c.line_no, line.text, c.method), []


def verify(cands: list[Candidate], doc: Document) -> Verified:
    out = Verified()
    seen: set[str] = set()
    for c in cands:
        res, reasons = check(c, doc)
        if res is None:
            out.rejections.append(Rejection(c.test_key, c.line_no, c.quote, reasons, c.method))
            continue
        if res.test_key in seen:
            # Keep the first; a second, different value for the same test is suspicious.
            prev = next(r for r in out.results if r.test_key == res.test_key)
            if abs(prev.value - res.value) > 1e-6:
                out.rejections.append(Rejection(c.test_key, c.line_no, c.quote,
                                                [f"second value for {res.name} conflicts with line {prev.line_no}"],
                                                c.method))
            continue
        seen.add(res.test_key)
        out.results.append(res)
    return out


def unit_label(u: str) -> str:
    return {"g/dl": "g/dL", "mg/dl": "mg/dL", "uiu/ml": "µIU/mL", "ng/ml": "ng/mL",
            "pg/ml": "pg/mL", "u/l": "U/L", "%": "%"}.get(normalise_unit(u), u)
