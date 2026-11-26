"""ReportSaathi - Streamlit app.   Run:  streamlit run app.py"""
from __future__ import annotations

import io
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from reportsaathi import read_pdf, analyse, build_trends
from reportsaathi.explain import (DISCLAIMER, doctor_questions, fmt, llm_explain, range_text,
                                  template_lines)
from reportsaathi.llm import get_llm
from reportsaathi.verify import unit_label

ROOT = Path(__file__).parent
st.set_page_config(page_title="ReportSaathi", page_icon="🩺", layout="wide")

llm, llm_name = get_llm()

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Reports")
    use_demo = st.toggle("Use 4-year sample reports (synthetic)", value=True)
    uploads = st.file_uploader("…or upload lab-report PDFs", type="pdf", accept_multiple_files=True)
    language = st.selectbox("Explain in", ["English", "Tamil", "Hindi", "Kannada", "Telugu", "Malayalam"])
    st.caption(f"AI engine: **{llm_name}**")
    if llm is None:
        st.caption("Set GEMINI_API_KEY or ANTHROPIC_API_KEY to enable AI extraction for new layouts "
                   "and explanations in Indian languages. Verification works either way.")


@st.cache_data(show_spinner=False)
def load_demo():
    return [(p.name, p.read_bytes()) for p in sorted((ROOT / "samples" / "demo").glob("*.pdf"))]


files = [(u.name, u.getvalue()) for u in uploads] if uploads else (load_demo() if use_demo else [])

st.title("🩺 ReportSaathi")
st.markdown("**Understand your family's lab reports without trusting an AI blindly.** "
            "Every number shown is traced to the exact line of the report it came from.")

if not files:
    st.info("Upload one or more lab-report PDFs, or switch on the sample reports.")
    st.stop()

# ------------------------------------------------------------------ analyse
reports, logs = [], []
with st.spinner("Reading and verifying reports…"):
    for name, data in files:
        doc = read_pdf(io.BytesIO(data), name=name)
        v = analyse(doc, llm)
        when = doc.report_date
        if when is None:
            st.warning(f"No report date found in {name}; it is left out of trends.")
            continue
        reports.append((name, when, v.results, doc))
        logs.append((name, v))

if not reports:
    st.stop()
reports.sort(key=lambda r: r[1])
trends = build_trends([(n, d, res) for n, d, res, _ in reports])
latest_name, latest_date, latest, _ = reports[-1]

blocked = sum(len(v.rejections) for _, v in logs)
warnings = [t for t in trends.values() if t.months_to_limit is not None]
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Reports", len(reports))
c2.metric("Verified results", sum(len(r[2]) for r in reports))
c3.metric("Out of range now", sum(r.status != "normal" for r in latest))
c4.metric("Early warnings", len(warnings))
c5.metric("Claims blocked", blocked, help="Extractions that failed verification. See the Trust log tab.")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Latest report", "Trends", "Explain", "Ask your doctor", "Trust log"])

ICON = {"high": "🔺 high", "low": "🔻 low", "normal": "✅ normal"}

with tab1:
    st.subheader(f"{latest_name}  ·  {latest_date:%d %b %Y}")
    df = pd.DataFrame([{
        "Test": r.name, "Result": f"{fmt(r.value)} {unit_label(r.unit)}", "As printed": r.printed,
        "Normal range": range_text(r) + ("" if r.range_source == "report" else " (default)"),
        "Status": ICON[r.status], "Source": f"line {r.line_no}: “{r.quote}”",
    } for r in sorted(latest, key=lambda r: r.status == "normal")])
    st.dataframe(df, hide_index=True, width="stretch")
    st.caption("Values in SI units (mmol/L, µmol/L…) are converted to the units most Indian doctors use. "
               "'As printed' shows the original.")

with tab2:
    if warnings:
        for t in warnings:
            st.warning(f"**{t.name}** is still in range but has moved toward the {t.limit_side} limit in "
                       f"{max(t.rising_streak, t.falling_streak)} reports in a row. At this rate it reaches the "
                       f"limit in about **{fmt(round(t.months_to_limit))} months**.")
    keys = [k for k, t in trends.items() if len(t.points) > 1]
    default = [t.test_key for t in warnings][:1] or keys[:1]
    pick = st.selectbox("Test", keys, index=keys.index(default[0]) if default else 0,
                        format_func=lambda k: trends[k].name)
    t = trends[pick]
    fig, ax = plt.subplots(figsize=(8, 3.2))
    xs = [p.when for p in t.points]
    ys = [p.value for p in t.points]
    lo = t.points[-1].ref_low
    hi = t.points[-1].ref_high
    ymin, ymax = min(ys + [v for v in (lo, hi) if v is not None]), max(ys + [v for v in (lo, hi) if v is not None])
    pad = (ymax - ymin) * 0.25 or 1
    ax.axhspan(lo if lo is not None else ymin - pad, hi if hi is not None else ymax + pad,
               color="#2a9d8f", alpha=0.12, label="normal range (latest report)")
    ax.plot(xs, ys, marker="o", color="#264653")
    for p in t.points:
        if p.status != "normal":
            ax.plot(p.when, p.value, "o", color="#e76f51", ms=9)
    ax.set_ylim(ymin - pad, ymax + pad)
    ax.set_ylabel(unit_label(t.unit))
    ax.set_title(t.name)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    st.pyplot(fig)
    if t.per_year is not None:
        st.caption(f"Change since {t.points[0].when:%b %Y}: {fmt(t.change)} {unit_label(t.unit)}"
                   f" ({fmt(t.change_pct)}%). Trend: {fmt(t.per_year)} {unit_label(t.unit)} per year.")

with tab3:
    if llm is not None:
        if st.button(f"Explain in {language} with AI"):
            with st.spinner("Writing explanation…"):
                try:
                    text, guard = llm_explain(latest, trends, language, llm)
                except Exception as e:  # never break the app over an API error
                    text, guard = "", None
                    st.error(f"AI explanation failed ({e}); showing the verified summary instead.")
            if guard and guard.ok:
                st.success("Number guard passed: every number below appears in the verified results.")
                st.markdown(text)
            elif guard:
                st.error("Number guard blocked this AI explanation because it contained numbers not in "
                         f"the verified results: {', '.join(guard.unknown_numbers)}. "
                         "Showing the verified summary instead.")
                with st.expander("Blocked AI text"):
                    st.text(text)
    elif language != "English":
        st.info(f"{language} explanations need an API key (see sidebar). Showing the English summary.")
    st.markdown("\n".join(f"- {s}" for s in template_lines(latest, trends)))
    st.caption(DISCLAIMER)

with tab4:
    qs = doctor_questions(latest, trends)
    st.markdown("Questions to take to your next appointment:")
    st.markdown("\n".join(f"{i}. {q}" for i, q in enumerate(qs, 1)) or "Nothing stands out. 🎉")
    st.caption(DISCLAIMER)

with tab5:
    st.markdown("Everything the extractor proposed but the verifier **refused to show**, and why.")
    rows = [{"Report": n, "Test": r.test_key, "Line": r.line_no, "Text": r.quote,
             "Why it was blocked": "; ".join(r.reasons), "Proposed by": r.method}
            for n, v in logs for r in v.rejections]
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.success("No claims were blocked.")
    st.markdown("**Checks applied to every result:** the cited line exists · the test name is on it · "
                "the value is printed on it (outside the reference range) · the unit is printed and "
                "recognised · the value is physiologically possible · no conflicting duplicate.")
