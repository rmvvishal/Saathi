"""Turn a lab-report PDF into candidate test results.

Two extractors produce the same `Candidate` objects:
  * `extract_rules`  - deterministic parser for common Indian lab layouts (works offline)
  * `extract_llm`    - asks an LLM to read the numbered lines (handles unseen layouts)

Neither is trusted. Every candidate must cite the exact line it came from, and
`verify.py` checks that citation before anything reaches the user.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import date, datetime

import pdfplumber

from .catalog import alias_index, TESTS, normalise_unit

NUM = r"\d+(?:\.\d+)?"
KNOWN_UNITS = {t.unit for t in TESTS.values()} | {u for t in TESTS.values() for u in t.conversions}


@dataclass
class Line:
    no: int          # 1-based, across the whole document
    page: int
    text: str


@dataclass
class Document:
    name: str
    lines: list[Line]
    report_date: date | None

    def line(self, no: int) -> Line | None:
        return self.lines[no - 1] if 1 <= no <= len(self.lines) else None


@dataclass
class Candidate:
    test_key: str
    value_str: str
    unit: str
    ref_low: float | None
    ref_high: float | None
    line_no: int
    quote: str
    method: str  # "rules" or "llm"

    def to_dict(self):
        return asdict(self)


# ---------------------------------------------------------------- reading PDFs

def read_pdf(path_or_file, name: str | None = None) -> Document:
    lines: list[Line] = []
    with pdfplumber.open(path_or_file) as pdf:
        for p, page in enumerate(pdf.pages, start=1):
            for raw in (page.extract_text() or "").splitlines():
                t = " ".join(raw.split())
                if t:
                    lines.append(Line(len(lines) + 1, p, t))
    doc_name = name or getattr(path_or_file, "name", str(path_or_file))
    return Document(doc_name, lines, find_report_date(lines))


_DATE_LABEL = re.compile(r"(report(?:ed)?\s*(?:date|on)|collected\s*(?:on|date)?|sample\s*date|date)\s*[:\-]?\s*(.+)", re.I)
_DATE_FORMATS = ["%d-%b-%Y", "%d %b %Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%b %d, %Y", "%d %B %Y"]


def _parse_date(s: str) -> date | None:
    s = s.strip()
    for token in [s] + re.findall(r"[\w./,-]+(?:\s[\w,]+\s\d{4})?", s):
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(token.strip(" ,"), fmt).date()
            except ValueError:
                pass
    return None


def find_report_date(lines: list[Line]) -> date | None:
    for ln in lines[:25]:
        m = _DATE_LABEL.search(ln.text)
        if m:
            d = _parse_date(m.group(2)[:20])
            if d:
                return d
    return None


# ------------------------------------------------------------ rule extractor

_ALIASES = alias_index()
_RANGE_PATTERNS = [
    (re.compile(rf"({NUM})\s*(?:-|–|to)\s*({NUM})"), lambda m: (float(m[1]), float(m[2]))),
    (re.compile(rf"(?:<=?|≤|less than|up to|upto|below)\s*({NUM})", re.I), lambda m: (None, float(m[1]))),
    (re.compile(rf"(?:>=?|≥|more than|above)\s*({NUM})", re.I), lambda m: (float(m[1]), None)),
]
_VALUE_UNIT = re.compile(rf"^[\s:.\-–]*?({NUM})\s*([A-Za-zµμ%][A-Za-zµμ%/0-9.]*)?")


def _match_alias(text: str) -> tuple[str, str] | None:
    low = text.lower()
    for alias, key in _ALIASES:
        if low.startswith(alias) and (len(low) == len(alias) or not low[len(alias)].isalnum()):
            return alias, key
    return None


def parse_line(line: Line) -> Candidate | None:
    hit = _match_alias(line.text)
    if not hit:
        return None
    alias, key = hit
    rest = line.text[len(alias):]
    rest = re.sub(r"^\s*\([^)]*\)", "", rest)  # drop "(SGPT)" style suffixes
    m = _VALUE_UNIT.match(rest)
    if not m:
        return None
    value_str, unit = m.group(1), (m.group(2) or "")
    tail = rest[m.end():]
    if unit.upper() in {"H", "L"}:  # a high/low flag printed before the unit
        u = re.match(r"\s*([A-Za-zµμ%][A-Za-zµμ%/0-9.]*)", tail)
        if u and normalise_unit(u.group(1)) in KNOWN_UNITS:
            unit, tail = u.group(1), tail[u.end():]
        else:
            unit = ""
    lo = hi = None
    for pat, conv in _RANGE_PATTERNS:
        r = pat.search(tail)
        if r:
            lo, hi = conv(r)
            break
    return Candidate(key, value_str, unit, lo, hi, line.no, line.text, "rules")


def extract_rules(doc: Document) -> list[Candidate]:
    return [c for ln in doc.lines if (c := parse_line(ln))]


# ------------------------------------------------------------- LLM extractor

LLM_EXTRACT_PROMPT = """You are reading a medical lab report. Below are its text lines, each prefixed with a line number.
Extract every test result for these tests only: {tests}.
Return ONLY a JSON list. Each item:
  {{"test_key": one of [{keys}], "value": the number exactly as printed, "unit": unit as printed,
    "ref_low": number or null, "ref_high": number or null, "line_no": the line number it is on}}
Rules: copy numbers exactly as printed; never compute, convert or guess; if a test is not present, omit it.

LINES:
{lines}"""


def extract_llm(doc: Document, llm) -> list[Candidate]:
    tests = ", ".join(t.name for t in TESTS.values())
    keys = ", ".join(f'"{k}"' for k in TESTS)
    numbered = "\n".join(f"{ln.no}: {ln.text}" for ln in doc.lines)
    raw = llm(LLM_EXTRACT_PROMPT.format(tests=tests, keys=keys, lines=numbered))
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for it in items:
        try:
            ln = int(it.get("line_no", 0))
            line = doc.line(ln)
            out.append(Candidate(
                str(it.get("test_key", "")), str(it.get("value", "")), str(it.get("unit") or ""),
                _f(it.get("ref_low")), _f(it.get("ref_high")), ln,
                line.text if line else "", "llm"))
        except (TypeError, ValueError):
            continue
    return out


def _f(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None
