"""Catalog of supported lab tests.

Every test has:
  - a canonical unit that all values are converted to,
  - the aliases Indian labs commonly print,
  - unit conversions (other unit -> canonical),
  - physiological plausibility bounds (anything outside is almost certainly an
    extraction error, not a real result),
  - a default reference range, used ONLY when the report itself prints none,
  - a plain-language, non-diagnostic description.

The LLM never decides any of this. It is fixed, reviewable data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Test:
    key: str
    name: str
    unit: str                      # canonical unit
    aliases: tuple[str, ...]
    plausible: tuple[float, float]  # in canonical unit
    default_range: tuple[float | None, float | None]
    about: str
    conversions: dict[str, Callable[[float], float]] = field(default_factory=dict)


def _lin(k: float) -> Callable[[float], float]:
    return lambda x: x * k


# Units are matched after normalisation (see normalise_unit).
TESTS: dict[str, Test] = {
    t.key: t
    for t in [
        Test("hb", "Haemoglobin", "g/dl",
             ("haemoglobin", "hemoglobin", "hb", "hgb"),
             (3, 25), (13.0, 17.0),
             "The protein in red blood cells that carries oxygen. Low values are called anaemia.",
             {"g/l": _lin(0.1)}),
        Test("fbs", "Fasting Glucose", "mg/dl",
             ("fasting blood sugar", "fasting plasma glucose", "glucose fasting", "fasting glucose", "fbs"),
             (20, 800), (70, 100),
             "Blood sugar after not eating for 8-10 hours.",
             {"mmol/l": _lin(18.0)}),
        Test("hba1c", "HbA1c", "%",
             ("glycated haemoglobin", "glycated hemoglobin", "glycosylated haemoglobin", "hba1c"),
             (3, 20), (None, 5.7),
             "Average blood sugar over roughly the last three months.",
             {"mmol/mol": lambda x: 0.09148 * x + 2.152}),
        Test("tc", "Total Cholesterol", "mg/dl",
             ("total cholesterol", "cholesterol total", "s. cholesterol", "cholesterol"),
             (50, 600), (None, 200),
             "All cholesterol carried in the blood.",
             {"mmol/l": _lin(38.67)}),
        Test("ldl", "LDL Cholesterol", "mg/dl",
             ("ldl cholesterol", "ldl-c", "ldl direct", "ldl"),
             (10, 400), (None, 100),
             "Often called 'bad' cholesterol; it can build up in artery walls.",
             {"mmol/l": _lin(38.67)}),
        Test("hdl", "HDL Cholesterol", "mg/dl",
             ("hdl cholesterol", "hdl-c", "hdl"),
             (5, 150), (40, None),
             "Often called 'good' cholesterol; higher is generally better.",
             {"mmol/l": _lin(38.67)}),
        Test("tg", "Triglycerides", "mg/dl",
             ("triglycerides", "triglyceride", "tg"),
             (20, 2000), (None, 150),
             "A type of fat in the blood, strongly affected by diet.",
             {"mmol/l": _lin(88.57)}),
        Test("creat", "Creatinine", "mg/dl",
             ("serum creatinine", "s. creatinine", "creatinine"),
             (0.1, 20), (0.7, 1.3),
             "A waste product filtered by the kidneys; used to judge kidney function.",
             {"umol/l": _lin(1 / 88.4)}),
        Test("tsh", "TSH", "uiu/ml",
             ("thyroid stimulating hormone", "tsh ultrasensitive", "tsh"),
             (0.005, 150), (0.4, 4.0),
             "Hormone that controls the thyroid gland.",
             {"miu/l": _lin(1.0)}),
        Test("vitd", "Vitamin D (25-OH)", "ng/ml",
             ("25-oh vitamin d", "25 hydroxy vitamin d", "vitamin d total", "vitamin d"),
             (2, 200), (30, 100),
             "Vitamin needed for bones and muscles; deficiency is very common in India.",
             {"nmol/l": _lin(1 / 2.496)}),
        Test("b12", "Vitamin B12", "pg/ml",
             ("vitamin b12", "vit b12", "cyanocobalamin", "b12"),
             (50, 3000), (200, 900),
             "Vitamin needed for nerves and red blood cells.",
             {"pmol/l": _lin(1.355)}),
        Test("alt", "ALT (SGPT)", "u/l",
             ("alt (sgpt)", "sgpt", "alt", "alanine aminotransferase"),
             (1, 3000), (None, 41),
             "Liver enzyme; raised values can mean the liver is under stress.",
             {}),
        Test("ast", "AST (SGOT)", "u/l",
             ("ast (sgot)", "sgot", "ast", "aspartate aminotransferase"),
             (1, 3000), (None, 40),
             "Enzyme found in the liver and muscles.",
             {}),
    ]
}

_UNIT_FIXES = {
    "µ": "u", "μ": "u", "mcg": "ug", "iu": "iu",
}


def normalise_unit(u: str | None) -> str:
    if not u:
        return ""
    u = u.strip().lower()
    for a, b in _UNIT_FIXES.items():
        u = u.replace(a, b)
    u = u.replace(" ", "").replace("dl", "dl").replace("/dL", "/dl")
    # common spellings
    u = {"gm/dl": "g/dl", "gms/dl": "g/dl", "uiu/ml": "uiu/ml", "miu/ml": "uiu/ml",
         "mu/l": "miu/l", "iu/l": "u/l"}.get(u, u)
    return u


def to_canonical(test: Test, value: float, unit: str) -> float | None:
    """Convert a value to the test's canonical unit. None if unit is unknown."""
    u = normalise_unit(unit)
    if u == test.unit or u == "":
        return value
    conv = test.conversions.get(u)
    return conv(value) if conv else None


def alias_index() -> list[tuple[str, str]]:
    """(alias, key) sorted longest alias first so 'ldl cholesterol' wins over 'cholesterol'."""
    pairs = [(a, t.key) for t in TESTS.values() for a in t.aliases]
    return sorted(pairs, key=lambda p: -len(p[0]))
