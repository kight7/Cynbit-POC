"""Stage 4 guardrail: verify that the draft does not invent numbers or citations.

1. Every number in the draft (percentages, counts, latencies, money) must appear in the
   retrieved context or in the client's own inquiry. Anything else is flagged.
2. Every [CS-xx] citation must refer to a case study that was actually retrieved.
"""
from __future__ import annotations

import re

from .schemas import GuardrailReport

CITE_RE = re.compile(r"\[(CS-\d{2})\]")
# numbers like 25%, 2.4M+, 50,000+, 200 ms, 99.9%, $80k, 15
NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(\s?(?:%|k|m|mn|million|ms|x|\+|lakhs?|crores?))?", re.I)


def _canon(num: str, unit: str | None) -> str:
    n = num.replace(",", "")
    if "." in n:
        n = n.rstrip("0").rstrip(".")
    return n


def numbers_in(text: str) -> list[tuple[str, str]]:
    """Return (display, canonical) for each numeric claim, ignoring citations and list markers."""
    text = CITE_RE.sub(" ", text)
    text = re.sub(r"CS-\d{2}", " ", text)
    text = re.sub(r"(?m)^\s*(?:#+\s*)?\d+[.)]\s", " ", text)  # "1. " list numbers / "## 2) " headings
    text = re.sub(r"(?i)\b(?:phase|step|week|weeks|stage|option|section|q)\s*\d+\b", " ", text)  # structural labels
    out = []
    for m in NUM_RE.finditer(text):
        disp = (m.group(1) + (m.group(2) or "")).strip()
        out.append((disp, _canon(m.group(1), m.group(2))))
    return out


def check_draft(draft: str, context: str, inquiry: str, retrieved_ids: list[str]) -> GuardrailReport:
    allowed = {c for _, c in numbers_in(context)} | {c for _, c in numbers_in(inquiry)}
    found = numbers_in(draft)
    unverified = sorted({d for d, c in found if c not in allowed})
    verified = sum(1 for _, c in found if c in allowed)

    cites = sorted(set(CITE_RE.findall(draft)))
    invalid = [c for c in cites if c not in retrieved_ids]
    total = len(found)
    faith = 1.0 if total == 0 else verified / total
    return GuardrailReport(
        numbers_total=total,
        numbers_verified=verified,
        unverified_numbers=unverified,
        citations_used=cites,
        invalid_citations=invalid,
        faithfulness=round(faith, 3),
        passed=not unverified and not invalid,
    )


def highlight_unverified(draft: str, unverified: list[str]) -> str:
    """Wrap unverified numbers in a visible marker for the UI."""
    for u in sorted(unverified, key=len, reverse=True):
        draft = re.sub(rf"(?<![\w.]){re.escape(u)}(?![\w])", f"**⚠️{u}**", draft)
    return draft
