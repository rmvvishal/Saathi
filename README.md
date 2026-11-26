# 🩺 ReportSaathi

**Understand your family's lab reports without trusting an AI blindly.**

ReportSaathi reads blood-test PDFs from any Indian lab, explains them in plain language, and tracks every value across years, so you notice a number drifting toward trouble *before* it turns red. Every number it shows can be traced to the exact line of the report it came from. If an AI step proposes something it can't prove, the claim is blocked and logged.

![ReportSaathi – latest report view](docs/screenshot_app.png)

---

## The problem

In most Indian families, lab reports pile up as PDFs on WhatsApp. Each lab uses a different layout, a different name for the same test (*FBS*, *Glucose Fasting*, *Fasting Blood Sugar*) and sometimes different units (mg/dL vs mmol/L). So:

1. **Nobody compares reports over time.** A single report only says "normal" or "high". It can't say "your HbA1c has risen for three years in a row and is about 8 months from the prediabetic line."
2. **Pasting a report into a chatbot is risky.** LLMs are good at explaining, but they can misread a value, mix up units, or invent a number. In health, one wrong number is worse than no answer.

## What makes it different

**The AI is never the source of truth.** Language models propose, deterministic code verifies, and only verified facts reach the user.

![Architecture](docs/architecture.png)

| Stage | What it does |
|---|---|
| **Extractors** | A rule-based parser handles known layouts offline. An optional LLM extractor (Claude or Gemini) handles unseen layouts and must cite the line number each value came from. |
| **Verifier** | Every proposed result must pass six checks: the cited line exists · the test name is on it (and not hidden inside another name like "HDL **Cholesterol**") · the value is printed on that line *outside* the reference-range text · the unit is printed and recognised · the value is physiologically possible · there's no conflicting duplicate. Status (low/normal/high) is plain arithmetic, never the LLM. |
| **Timeline** | Converts units, aligns reports by date, fits a trend line, and raises **early warnings** for values still in range but steadily heading out of it. |
| **Explainer + Number guard** | The LLM may only *phrase* verified facts, in English, Tamil, Hindi, Kannada, Telugu or Malayalam. Every number in its answer is checked against the verified facts. Any unknown number means the whole answer is discarded and a safe template is shown instead. |
| **Trust log** | Every blocked claim is shown with the reason, so nothing is silently dropped or silently shown. |

## Results

Evaluated on **60 synthetic reports (571 test results)** in three lab layouts, including SI units, alias names, H/L flags, missing ranges, and interpretation tables that repeat test names with other numbers. Run `python eval/run_eval.py` to reproduce.

**Verifier stress test.** I took the 571 correct extractions and corrupted them the way LLMs typically fail, then counted how many the verifier blocked:

| Corruption (simulating an LLM error) | Cases | Blocked |
|---|---:|---:|
| Value changed (×0.7 – ×1.5) | 571 | **100%** |
| Decimal slip (×10) | 571 | **100%** |
| Cites the wrong line | 571 | **100%** |
| Invents a test that isn't on the report | 441 | **100%** |
| Wrong unit (e.g. mg/dL ↔ mmol/L) | 438 | **100%** |
| *Correct results wrongly blocked* | 571 | **0%** |

**The first version was not perfect.** v1 blocked only 570/571 changed values and 437/441 invented tests. The evaluation exposed two real failure modes, and both are now fixed and covered by unit tests:
- A model could "read" the reference limit as the patient's value (`HbA1c : 7.1 % (Ref: < 5.7)` → 5.7). Fix: the value must appear *outside* the range text.
- "Cholesterol" matched inside "HDL Cholesterol", so an invented *Total Cholesterol* passed. Fix: mask other tests' longer names before matching.

**Number guard.** It blocked **179/200 (89.5%)** explanations with an invented number added, and passed all 40 clean explanations. The 21 misses are cases where the invented number happened to equal a number that *is* in the facts (e.g. "8" from "8-10 hours"). The guard checks that a number *exists* in the verified facts, not that it's used in the *right context*. Claim-level grounding is the next step (see roadmap).

**Rule-based extraction.** 100% precision and recall on these three layouts. That's expected, because they're the layouts it was written for. Real-world layout variety is exactly why the LLM extractor exists, and why everything it produces still goes through the verifier.

![Trends and early warnings](docs/screenshot_trends.png)

## Run it

```bash
pip install -r requirements.txt
python samples/generate.py demo      # 4 years of synthetic reports for one person
streamlit run app.py
```

It works fully offline. For AI extraction of new layouts and explanations in Indian languages, set one key:

```bash
export GEMINI_API_KEY=...        # free tier works
# or
export ANTHROPIC_API_KEY=...
```

Tests and evaluation:

```bash
pytest -q
python samples/generate.py eval 60 && python eval/run_eval.py
```

## Project structure

```
reportsaathi/
  catalog.py   13 tests: aliases, unit conversions, plausibility bounds, plain-language notes
  extract.py   PDF → numbered lines → candidates (rules or LLM)
  verify.py    the trust layer (6 checks, deterministic status)
  trends.py    timeline, streaks, early warnings
  explain.py   template + LLM explanations, number guard, doctor questions
  llm.py       tiny HTTP wrapper for Claude / Gemini (no SDKs)
app.py         Streamlit UI
samples/       synthetic report generator (3 lab layouts, ground truth)
eval/          evaluation harness + results.json
tests/         unit tests for every verifier rule
```

## Limitations (honest list)

- **Synthetic data.** Real patient reports can't be published, so the evaluation uses generated reports. The next step is testing on real (de-identified) reports from family and friends, with consent.
- **Text PDFs only.** Scanned or phone-photo reports need OCR first.
- **13 common tests.** Adding a test means adding a reviewed catalog entry, by design.
- **Reference ranges** come from the report when printed; the defaults are generic adult ranges and are not sex- or age-specific.
- **Not a medical device.** It explains and organises. It never diagnoses or suggests treatment.

## Roadmap

1. OCR for photographed reports (the most common format in India).
2. Claim-level grounding: check that each sentence pairs the right number with the right test, not just that the number exists.
3. Measure the LLM extractor on real, consented, de-identified reports from different labs.
4. Family profiles and a WhatsApp-forward workflow, since that's where the reports already live.

## How AI was used

ReportSaathi was built in November 2026 with **Claude (Anthropic)** as a pair-programmer. Most of the code was generated in that collaboration. The evaluation harness is what turned it from a demo into something trustworthy: it found the two verifier bugs described above, which were then fixed and locked in with tests. The project's thesis is the same as how it was built: **use AI for what it's good at, and verify everything that matters.**

---

*ReportSaathi explains reports; it does not diagnose. Always discuss results with a doctor.*
