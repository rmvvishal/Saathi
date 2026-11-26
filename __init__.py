"""ReportSaathi: understand your family's lab reports without trusting an AI blindly."""
from .extract import read_pdf, extract_rules, extract_llm, Document, Candidate
from .verify import verify, Result, Verified
from .trends import build as build_trends


def analyse(doc: Document, llm=None):
    """Extract -> verify. Uses the LLM extractor if given, falling back to rules for anything it missed."""
    rule_cands = extract_rules(doc)
    if llm is None:
        return verify(rule_cands, doc)
    try:
        llm_cands = extract_llm(doc, llm)
    except Exception:  # network/API problems must never break the app
        return verify(rule_cands, doc)
    v = verify(llm_cands, doc)
    got = {r.test_key for r in v.results}
    rest = verify([c for c in rule_cands if c.test_key not in got], doc)
    v.results += rest.results
    v.rejections += rest.rejections
    return v
