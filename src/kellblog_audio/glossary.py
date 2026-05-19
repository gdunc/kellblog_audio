"""Pronunciation overrides for TTS (word-boundary aware)."""

from __future__ import annotations

import re

# Longer phrases first when applying
PRONUNCIATIONS: list[tuple[str, str]] = [
    ("SaaS", "sass"),
    ("ARR", "A. R. R."),
    ("MRR", "M. R. R."),
    ("ICP", "I. C. P."),
    ("CRO", "C. R. O."),
    ("CMO", "C. M. O."),
    ("CFO", "C. F. O."),
    ("GTM", "G. T. M."),
    ("OKR", "O. K. R."),
    ("OKRs", "O. K. R.s"),
    ("PMM", "P. M. M."),
    ("GSI", "G. S. I."),
    ("RTO", "R. T. O."),
    ("TLA", "T. L. A."),
    ("TLAs", "T. L. A.s"),
    ("GenAI", "Gen A. I."),
    ("AI", "A. I."),
    ("ML", "M. L."),
    ("CEO", "C. E. O."),
    ("CPO", "C. P. O."),
    ("VP", "V. P."),
    ("VC", "V. C."),
    ("PE", "P. E."),
    ("M&A", "M. and A."),
    ("IPO", "I. P. O."),
    ("B2B", "B. to B."),
    ("B2C", "B. to C."),
    ("API", "A. P. I."),
    ("APIs", "A. P. I.s"),
    ("ROI", "R. O. I."),
    ("KPI", "K. P. I."),
    ("KPIs", "K. P. I.s"),
    ("NPS", "N. P. S."),
    ("SDR", "S. D. R."),
    ("SDRs", "S. D. R.s"),
    ("SQL", "S. Q. L."),
    ("CRM", "C. R. M."),
    ("ERP", "E. R. P."),
    ("PLG", "P. L. G."),
    ("PLM", "P. L. M."),
    ("FAQ", "F. A. Q."),
]


def apply_glossary(text: str) -> str:
    result = text
    for term, spoken in sorted(PRONUNCIATIONS, key=lambda x: -len(x[0])):
        pattern = re.compile(r"\b" + re.escape(term) + r"\b")
        result = pattern.sub(spoken, result)
    return result
