"""Generate realistic synthetic lab-report PDFs with ground truth.

Real patient reports cannot be shared, so the demo and the evaluation use
synthetic reports that imitate three common Indian lab layouts:

  A  table layout        "Haemoglobin   14.2   g/dL   13.0 - 17.0"
  B  colon / ref layout  "Fasting Blood Sugar : 112 mg/dL (Ref: 70 - 100) H"
  C  SI-unit layout      "S. Creatinine   97 µmol/L   [62 - 115]"

They include the traps real reports have: H/L flags, missing reference ranges,
SI units, alias names, method/sample lines, and interpretation tables that
repeat test names with other numbers.

Usage:
  python samples/generate.py demo   -> samples/demo/*.pdf   (one family member, 4 years)
  python samples/generate.py eval N -> eval/reports/*.pdf + eval/ground_truth.json
"""
from __future__ import annotations

import json
import random
import sys
from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reportsaathi.catalog import TESTS, to_canonical  # noqa: E402

# canonical -> printed unit for the SI layout
SI = {
    "hb": ("g/L", lambda v: v * 10, 0),
    "fbs": ("mmol/L", lambda v: v / 18.0, 1),
    "hba1c": ("mmol/mol", lambda v: (v - 2.152) / 0.09148, 0),
    "tc": ("mmol/L", lambda v: v / 38.67, 2),
    "ldl": ("mmol/L", lambda v: v / 38.67, 2),
    "hdl": ("mmol/L", lambda v: v / 38.67, 2),
    "tg": ("mmol/L", lambda v: v / 88.57, 2),
    "creat": ("µmol/L", lambda v: v * 88.4, 0),
    "vitd": ("nmol/L", lambda v: v * 2.496, 0),
    "b12": ("pmol/L", lambda v: v / 1.355, 0),
}
CONV = {"hb": "g/dL", "fbs": "mg/dL", "hba1c": "%", "tc": "mg/dL", "ldl": "mg/dL", "hdl": "mg/dL",
        "tg": "mg/dL", "creat": "mg/dL", "tsh": "µIU/mL", "vitd": "ng/mL", "b12": "pg/mL",
        "alt": "U/L", "ast": "U/L"}
DEC = {"hb": 1, "fbs": 0, "hba1c": 1, "tc": 0, "ldl": 0, "hdl": 0, "tg": 0, "creat": 2, "tsh": 2,
       "vitd": 1, "b12": 0, "alt": 0, "ast": 0}
DISPLAY = {  # alias spellings a lab might print (all present in the catalog)
    "hb": ["Haemoglobin", "Hemoglobin", "Hb"], "fbs": ["Fasting Blood Sugar", "Glucose Fasting", "FBS"],
    "hba1c": ["HbA1c", "Glycated Haemoglobin"], "tc": ["Total Cholesterol", "Cholesterol Total"],
    "ldl": ["LDL Cholesterol", "LDL-C"], "hdl": ["HDL Cholesterol", "HDL-C"], "tg": ["Triglycerides"],
    "creat": ["Serum Creatinine", "S. Creatinine", "Creatinine"], "tsh": ["TSH", "TSH Ultrasensitive"],
    "vitd": ["25-OH Vitamin D", "Vitamin D Total"], "b12": ["Vitamin B12", "Vit B12"],
    "alt": ["SGPT", "ALT (SGPT)"], "ast": ["SGOT", "AST (SGOT)"],
}
DEFAULT_PRINT_RANGE = {"hb": (12.0, 15.5), "creat": (0.6, 1.1)}  # female ranges for the demo patient
LABS = {"A": "Sunrise Diagnostics, Chennai", "B": "CarePoint Labs, Bengaluru", "C": "Medisure Pathology, Pune"}


def _r(x, d):
    return f"{x:.{d}f}"


def _printed(key, canon, layout):
    if layout == "C" and key in SI:
        unit, f, d = SI[key]
        return _r(f(canon), d), unit, (lambda v, f=f, d=d: _r(f(v), d))
    d = DEC[key]
    return _r(canon, d), CONV[key], (lambda v, d=d: _r(v, d))


def make_report(path: Path, layout: str, when: date, patient: str, values: dict[str, float],
                rng: random.Random, missing_range_p=0.0, alias_random=True) -> list[dict]:
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    y = H - 60
    truth = []

    def text(x, s, size=10, font="Helvetica"):
        c.setFont(font, size)
        c.drawString(x, y, s)

    text(50, LABS[layout], 14, "Helvetica-Bold"); y -= 18
    text(50, "NABL accredited laboratory | Ph: 1800-000-000", 8); y -= 22
    text(50, f"Patient: {patient}"); text(330, "Ref. by: Self"); y -= 14
    date_line = {"A": f"Report Date: {when.strftime('%d-%b-%Y')}",
                 "B": f"Collected on: {when.isoformat()}",
                 "C": f"Date: {when.strftime('%d/%m/%Y')}"}[layout]
    text(50, date_line); text(330, "Sample: Serum / EDTA"); y -= 26

    if layout == "A":
        text(50, "Test", 10, "Helvetica-Bold"); text(250, "Result", 10, "Helvetica-Bold")
        text(320, "Unit", 10, "Helvetica-Bold"); text(400, "Reference Range", 10, "Helvetica-Bold"); y -= 16

    for key, canon in values.items():
        name = rng.choice(DISPLAY[key]) if alias_random else DISPLAY[key][0]
        val_s, unit, conv = _printed(key, canon, layout)
        lo, hi = DEFAULT_PRINT_RANGE.get(key, TESTS[key].default_range)
        has_range = rng.random() >= missing_range_p
        lo_s = conv(lo) if lo is not None else None
        hi_s = conv(hi) if hi is not None else None
        if not has_range:
            rng_s = ""
        elif lo_s and hi_s:
            rng_s = f"{lo_s} - {hi_s}"
        elif hi_s:
            rng_s = f"< {hi_s}"
        else:
            rng_s = f"> {lo_s}"

        printed_val = float(val_s)
        canon_val = to_canonical(TESTS[key], printed_val, unit)
        r_lo = float(lo_s) if (has_range and lo_s) else None
        r_hi = float(hi_s) if (has_range and hi_s) else None
        # ground-truth status using the printed range (or catalog default if none printed)
        if has_range:
            glo = to_canonical(TESTS[key], r_lo, unit) if r_lo is not None else None
            ghi = to_canonical(TESTS[key], r_hi, unit) if r_hi is not None else None
        else:
            glo, ghi = TESTS[key].default_range
        status = "low" if glo is not None and canon_val < glo - 1e-9 else \
                 "high" if ghi is not None and canon_val > ghi + 1e-9 else "normal"
        flag = {"low": "L", "high": "H"}.get(status, "")

        if layout == "A":
            text(50, name); text(250, val_s + (f" {flag}" if flag else "")); text(320, unit); text(400, rng_s)
        elif layout == "B":
            text(50, f"{name} : {val_s} {unit}" + (f" (Ref: {rng_s})" if rng_s else "") + (f" {flag}" if flag else ""))
        else:
            text(50, name); text(230, f"{val_s} {unit}"); text(360, f"[{rng_s}]" if rng_s else "")
        y -= 15
        if rng.random() < 0.25:
            text(60, f"Method: {rng.choice(['Photometry', 'HPLC', 'CLIA', 'Hexokinase', 'Enzymatic'])}", 8); y -= 13
        truth.append({"test_key": key, "value": round(canon_val, 3), "printed": val_s, "unit": unit,
                      "ref_low": r_lo, "ref_high": r_hi, "status": status})

    # Interpretation table: repeats test names with *other* numbers (a classic trap).
    if "hba1c" in values:
        y -= 10
        text(50, "Interpretation", 10, "Helvetica-Bold"); y -= 14
        if layout == "C":
            text(50, "HbA1c 39 - 46 mmol/mol : increased risk"); y -= 13
        else:
            text(50, "HbA1c 5.7 - 6.4 % : prediabetes range (ADA)"); y -= 13
            text(50, "HbA1c >= 6.5 % : diabetes range (ADA)"); y -= 13
    y -= 20
    text(50, "*** End of report ***", 8); y -= 12
    text(50, "Dr. A. Kumar, MD (Pathology)  |  Page 1 of 1", 8)
    c.save()
    return truth


# ------------------------------------------------------------------- demo

DEMO = [
    ("A", date(2023, 3, 14)), ("B", date(2024, 4, 2)), ("C", date(2025, 3, 20)), ("A", date(2026, 2, 11)),
]
DEMO_VALUES = {
    "hb":    [12.6, 12.3, 11.8, 11.6],
    "fbs":   [88, 93, 97, 104],
    "hba1c": [5.2, 5.35, 5.5, 5.6],
    "tc":    [188, 195, 203, 211],
    "ldl":   [112, 119, 127, 136],
    "hdl":   [52, 50, 47, 45],
    "tg":    [128, 139, 148, 156],
    "creat": [0.78, 0.8, 0.84, 0.86],
    "tsh":   [2.1, 2.6, 3.1, 3.6],
    "vitd":  [17.5, 23.0, 31.0, 27.5],
    "b12":   [310, 285, 262, 244],
    "alt":   [22, 26, 31, 34],
    "ast":   [24, 25, 28, 29],
}


def demo():
    out = ROOT / "samples" / "demo"
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    for i, (layout, when) in enumerate(DEMO):
        vals = {k: v[i] for k, v in DEMO_VALUES.items()}
        make_report(out / f"report_{when.isoformat()}.pdf", layout, when,
                    "Lakshmi R (synthetic), 54 F", vals, rng, alias_random=True)
    print(f"wrote {len(DEMO)} demo reports to {out}")


# ------------------------------------------------------------------- eval

def random_values(rng: random.Random) -> dict[str, float]:
    spread = {"hb": (8, 17), "fbs": (65, 220), "hba1c": (4.6, 10.5), "tc": (130, 290), "ldl": (50, 210),
              "hdl": (25, 80), "tg": (60, 400), "creat": (0.5, 2.4), "tsh": (0.1, 9), "vitd": (6, 70),
              "b12": (120, 1100), "alt": (8, 160), "ast": (10, 120)}
    keys = rng.sample(list(TESTS), rng.randint(6, len(TESTS)))
    return {k: round(rng.uniform(*spread[k]), 3) for k in keys}


def eval_set(n: int):
    out = ROOT / "eval" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    gt = {}
    for i in range(n):
        layout = rng.choice("ABC")
        when = date(rng.randint(2019, 2026), rng.randint(1, 12), rng.randint(1, 28))
        name = f"eval_{i:03d}.pdf"
        gt[name] = {"layout": layout, "date": when.isoformat(),
                    "results": make_report(out / name, layout, when, f"Synthetic Patient {i}",
                                           random_values(rng), rng, missing_range_p=0.2)}
    (ROOT / "eval" / "ground_truth.json").write_text(json.dumps(gt, indent=1))
    print(f"wrote {n} eval reports")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "eval":
        eval_set(int(sys.argv[2]) if len(sys.argv) > 2 else 60)
    else:
        demo()
