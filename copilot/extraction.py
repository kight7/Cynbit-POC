"""Stage 1: turn an unstructured inquiry into validated `LeadFields`.

* LLM path: JSON-mode prompt with schema, controlled vocabularies, "null if not stated"
  rule and two few-shot examples; Pydantic validation with a repair retry (see llm.py).
* Offline path: deterministic keyword/regex extractor. It is used when no API key is
  configured or the LLM fails, and it doubles as an evaluation baseline.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from .config import taxonomy
from .llm import LLMClient
from .schemas import LeadFields

# ----------------------------------------------------------------------------- LLM prompt
FEW_SHOT = [
    (
        "Hi, I'm Priya, CTO at MediLink (120 staff, Pune). Our 15 partner clinics get hundreds of "
        "WhatsApp symptom messages a day and nurses can't keep up. We'd like an AI tool that flags the "
        "urgent ones and plugs into our EHR. Budget around 25 lakh INR, hoping to pilot within 10 weeks.",
        {
            "company_name": "MediLink", "contact_name": "Priya", "contact_role": "CTO",
            "industry": "healthcare", "need_types": ["ai_ml", "web_platform"],
            "need_summary": "AI triage tool that prioritises urgent patient symptom messages and integrates with the EHR.",
            "budget_signal": "around 25 lakh INR", "budget_amount_usd": 29762,
            "timeline": "pilot within 10 weeks", "timeline_months": 2.3, "urgency": "high",
            "company_size": "smb", "decision_maker_present": True, "region": "india", "off_scope": False,
            "missing_info": ["message volume per day", "EHR vendor", "data-privacy requirements"],
        },
    ),
    (
        "hello, we are exploring options for making our online presence better. can someone call me? - Mark",
        {
            "company_name": None, "contact_name": "Mark", "contact_role": None,
            "industry": None, "need_types": [],
            "need_summary": "Wants to improve online presence; no specific requirement stated.",
            "budget_signal": None, "budget_amount_usd": None, "timeline": None, "timeline_months": None,
            "urgency": "unknown", "company_size": "unknown", "decision_maker_present": False,
            "region": None, "off_scope": False,
            "missing_info": ["industry", "specific goal", "budget", "timeline", "company details"],
        },
    ),
]


def _system_prompt() -> str:
    tx = taxonomy()
    today = dt.date.today().isoformat()
    return f"""You are a pre-sales analyst at Cynbit Technologies, a software and IT services company
(web and mobile apps, AI/ML, cloud, IoT, AR, SEO/growth, UX modernisation, real-time systems, payments).
Extract structured lead information from an inbound client inquiry.

Return ONE JSON object with exactly these keys:
company_name, contact_name, contact_role, industry, need_types, need_summary, budget_signal,
budget_amount_usd, timeline, timeline_months, urgency, company_size, decision_maker_present,
region, off_scope, missing_info

Rules:
- Use null (or [] / false / "unknown") when a fact is NOT stated. Never guess names, numbers or budgets.
- industry: one of {list(tx['industries'])} or "other" or null.
- need_types: zero or more of {list(tx['need_types'])}.
- region: one of {list(tx['regions'])} or "other" or null (infer only from explicit place names, currency or phone codes).
- urgency: "high" (<= 2 months, ASAP, hard deadline soon), "medium" (2-6 months), "low" (> 6 months or just exploring), "unknown".
- company_size: "startup" (<20 people or pre-seed/seed), "smb" (20-199), "mid_market" (200-999), "enterprise" (1000+ or large chain), "unknown".
- decision_maker_present: true if the sender is a founder, owner, C-level, VP, director or head of a function.
- budget_amount_usd: the upper bound converted to USD (1 USD = 84 INR, 1 lakh = 100,000, 1 crore = 10,000,000; EUR x1.08; GBP x1.27; AED x0.27). null if no number.
- timeline_months: months from today ({today}) to the desired delivery/launch. null if not stated.
- off_scope: true only if the request is not something a software/IT services company delivers.
- need_summary: one neutral sentence. missing_info: the most important unstated facts a sales rep should ask about.
Output JSON only."""


def _messages(inquiry: str) -> list[dict]:
    msgs = [{"role": "system", "content": _system_prompt()}]
    for text, out in FEW_SHOT:
        msgs.append({"role": "user", "content": f"Inquiry:\n{text}"})
        msgs.append({"role": "assistant", "content": json.dumps(out)})
    msgs.append({"role": "user", "content": f"Inquiry:\n{inquiry}"})
    return msgs


def extract_with_llm(inquiry: str, llm: LLMClient) -> LeadFields:
    return llm.structured(_messages(inquiry), LeadFields, max_tokens=3000)  # headroom for reasoning tokens


# ----------------------------------------------------------------------------- offline extractor
FX = {"$": 1.0, "usd": 1.0, "us$": 1.0, "€": 1.08, "eur": 1.08, "£": 1.27, "gbp": 1.27, "aed": 0.27,
      "₹": 1 / 84, "inr": 1 / 84, "rs": 1 / 84, "rs.": 1 / 84}
MULT = {"k": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5,
        "cr": 1e7, "crore": 1e7, "crores": 1e7}
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]

_AMT = r"(\d[\d,]*(?:\.\d+)?)\s*(k|mn|m|million|lakhs?|lac|crores?|cr)?\b"
_CUR = r"(us\$|\$|usd|€|eur|£|gbp|aed|₹|inr|rs\.?)"
BUDGET_RE = re.compile(
    rf"(?:{_CUR}\s*{_AMT}(?:\s*(?:-|–|to)\s*{_CUR}?\s*{_AMT})?)|(?:{_AMT}(?:\s*(?:-|–|to)\s*{_AMT})?\s*{_CUR})",
    re.I,
)
SOFT_BUDGET = re.compile(r"budget (?:is )?(?:approved|allocated|flexible|available|set aside)|we are funded|recently raised|series [abc]|seed round|have (?:a )?budget", re.I)
DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|to)?\s*(\d+)?\s*(weeks?|months?)", re.I)


def _kw_hits(text: str, words: list[str]) -> int:
    n = 0
    for w in words:
        if re.search(rf"(?<![a-z0-9]){re.escape(w.lower())}(?![a-z0-9])", text):
            n += 1
    return n


def _to_usd(num: str, mult: str | None, cur: str | None) -> float:
    v = float(num.replace(",", ""))
    if mult:
        v *= MULT[mult.lower()]
    rate = FX.get((cur or "$").lower(), 1.0)
    return round(v * rate, 2)


def _budget(text: str) -> tuple[str | None, float | None]:
    best = None
    for m in BUDGET_RE.finditer(text):
        g = m.groups()
        if g[0]:  # currency first: cur amt mult [ - cur amt mult ]
            cur, amt, mult = g[0], g[1], g[2]
            if g[4]:
                amt, mult, cur = g[4], g[5] or mult, g[3] or cur
        else:  # amount first: amt mult [ - amt mult ] cur
            amt, mult, cur = g[6], g[7], g[10]
            if g[8]:
                amt, mult = g[8], g[9] or mult
        usd = _to_usd(amt, mult, cur)
        if usd < 500:  # ignore tiny numbers (e.g. "$5 per user")
            continue
        if best is None or usd > best[1]:
            best = (m.group(0).strip(), usd)
    if best:
        return best
    m = re.search(r"budget[^.\n]{0,30}?" + _AMT, text, re.I)
    if m and m.group(2):  # e.g. "budget of about 50k" / "budget ~ 20 lakhs" (no currency symbol)
        mult = m.group(2).lower()
        cur = "inr" if mult in ("lakh", "lakhs", "lac", "cr", "crore", "crores") else "usd"
        return m.group(0).strip(), _to_usd(m.group(1), mult, cur)
    soft = SOFT_BUDGET.search(text)
    return (soft.group(0), None) if soft else (None, None)


def _timeline(text: str, today: dt.date) -> tuple[str | None, float | None, bool]:
    low = text.lower()
    asap = bool(re.search(r"\basap\b|urgent|urgently|immediately|right away|as soon as possible|critical deadline", low))
    m = DURATION_RE.search(low)
    if m:
        a, b, unit = float(m.group(1)), m.group(2), m.group(3)
        val = float(b) if b else a
        months = val / 4.3 if unit.startswith("week") else val
        return m.group(0), round(months, 1), asap
    m = re.search(r"\b(?:by|before|in|launch(?:ing)? in|live by)\s+(?:the\s+)?(?:end of\s+)?(" + "|".join(MONTHS) + r")\b", low)
    if m:
        target = MONTHS.index(m.group(1)) + 1
        delta = (target - today.month) % 12 or 12
        return m.group(0), float(delta), asap
    m = re.search(r"\b(q[1-4])\b", low)
    if m:
        q_end = int(m.group(1)[1]) * 3
        delta = (q_end - today.month) % 12 or 3
        return m.group(0), float(delta), asap
    for phrase, months in (("next month", 1.0), ("this quarter", 2.0), ("next quarter", 4.0),
                           ("end of the year", max(1, 12 - today.month)), ("next year", 12.0)):
        if phrase in low:
            return phrase, float(months), asap
    if asap:
        return "ASAP", 1.0, True
    if re.search(r"no rush|just exploring|exploring options|long[- ]term|sometime", low):
        return "no fixed timeline", None, False
    return None, None, False


def _size(text: str) -> str:
    low = text.lower()
    m = re.search(r"(\d[\d,]*)\+?\s*(?:employees|staff|people|team members|engineers)", low)
    if m:
        n = int(m.group(1).replace(",", ""))
        return "startup" if n < 20 else "smb" if n < 200 else "mid_market" if n < 1000 else "enterprise"
    m = re.search(r"(\d[\d,]*)\+?\s*(?:[- ](?:store|outlet|clinic|hospital|branch|location|school|warehouse)s?|\s(?:stores|outlets|clinics|hospitals|branches|locations|schools|warehouses))", low)
    if m:
        n = int(m.group(1).replace(",", ""))
        if "hospital" in m.group(0):
            return "enterprise" if n >= 5 else "mid_market" if n >= 2 else "smb"
        return "enterprise" if n >= 100 else "mid_market" if n >= 20 else "smb"
    if re.search(r"fortune 500|multinational|enterprise|listed company|global (?:brand|company)", low):
        return "enterprise"
    if re.search(r"start-?up|pre-seed|seed[- ]stage|founding team|solo founder", low):
        return "startup"
    if re.search(r"small business|family business|smb|sme", low):
        return "smb"
    return "unknown"


def _signature_name(text: str) -> tuple[str | None, str | None]:
    m = re.search(r"(?:regards|thanks|thank you|best|cheers|sincerely)[,!]?\s*\n+\s*([A-Z][a-z]+(?: [A-Z][a-z]+)?)[ \t]*(?:[,\n|-]+\s*(.+))?", text, re.I)
    if m:
        return m.group(1), (m.group(2) or "").strip() or None
    m = re.search(r"\b(?:i am|i'm|this is|my name is)\s+([A-Z][a-z]+(?: [A-Z][a-z]+)?)", text)
    if m:
        return m.group(1), None
    m = re.search(r"[-–]\s*([A-Z][a-z]+)\s*$", text.strip())
    return (m.group(1), None) if m else (None, None)


NOT_COMPANIES = {"Google", "Instagram", "Facebook", "Meta", "Amazon", "Shopify", "India", "Dubai", "London", "Cynbit", "WhatsApp", "LinkedIn", "Our", "We", "The"}


def _company(text: str) -> str | None:
    m = re.search(r"\b([A-Z][\w&]*(?:\s[A-Z][\w&]*){0,3})\s+(?:Pvt\.? Ltd|Private Limited|Ltd|Inc|LLC|GmbH|Technologies|Labs|Health|Healthcare)\b", text)
    if m:
        return m.group(0).strip()
    for m in re.finditer(r"\b(?:at|from|founder of|ceo of|cto of|here at)\s+([A-Z][\w&]+(?:\s[A-Z][\w&]+){0,2})", text):
        if m.group(1).split()[0] not in NOT_COMPANIES:
            return m.group(1).strip()
    return None


def _role(low: str, titles: list[str]) -> str | None:
    """Find the sender's title, e.g. 'Head of Marketing', 'CTO', 'Founder'."""
    for t in sorted(titles, key=len, reverse=True):
        m = re.search(rf"(?<![a-z]){re.escape(t)}s?(?![a-z])((?: (?!at\b|here\b|in\b|from\b|and\b|with\b|for\b|of a\b|of the\b|of our\b)[a-z&]+){{0,2}})", low)
        if m:
            if len(t) <= 3:
                return t.upper()
            if t in ("founder", "co-founder", "cofounder", "owner", "partner"):
                return t.title()
            return (t + m.group(1)).title()
    return None


def extract_offline(inquiry: str, today: dt.date | None = None) -> LeadFields:
    today = today or dt.date.today()
    tx = taxonomy()
    low = inquiry.lower()

    ind_scores = {k: _kw_hits(low, v) for k, v in tx["industries"].items()}
    best_ind = max(ind_scores, key=ind_scores.get)
    industry = best_ind if ind_scores[best_ind] > 0 else None

    need_types = [k for k, v in tx["need_types"].items() if _kw_hits(low, v) > 0]
    reg_scores = {k: _kw_hits(low, v) for k, v in tx["regions"].items()}
    best_reg = max(reg_scores, key=reg_scores.get)
    region = best_reg if reg_scores[best_reg] > 0 else None

    budget_signal, budget_usd = _budget(inquiry)
    timeline, months, asap = _timeline(inquiry, today)
    if asap or (months is not None and months <= 2):
        urgency = "high"
    elif months is not None and months <= 6:
        urgency = "medium"
    elif months is not None or (timeline and "no fixed" in timeline):
        urgency = "low"
    else:
        urgency = "unknown"

    name, sig_role = _signature_name(inquiry)
    titles = tx["decision_maker_titles"]
    role = _role(low, titles)
    if not role and sig_role and len(sig_role) < 60:
        role = sig_role.split(",")[0].strip()
    company = _company(inquiry)
    if not company and sig_role and "," in sig_role:
        company = sig_role.split(",", 1)[1].strip() or None

    off_hits = _kw_hits(low, tx["off_scope_signals"])
    # Off-scope only when an off-scope signal appears AND nothing points to a software need or a known industry
    off_scope = off_hits > 0 and not need_types and industry is None

    body = re.sub(r"^\s*(?:hi|hello|hey|dear)\b[^\n,]*[,!]?\s*", "", inquiry.strip(), flags=re.I)
    flat = re.sub(r"\n(?=[a-z])", " ", body)  # re-join lines wrapped mid-sentence
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", flat) if x.strip()]
    need_sentence = next((x for x in sentences if re.search(r"\b(need|looking for|want|require|would like)", x, re.I)), None) \
        or next((x for x in sentences if re.search(r"\b(build|develop|create|help)", x, re.I)), sentences[0] if sentences else "")
    need_summary = need_sentence[:220] or None

    missing = []
    if not need_types:
        missing.append("specific requirement / scope")
    if not industry:
        missing.append("industry / business context")
    if not budget_signal:
        missing.append("budget range")
    if not timeline:
        missing.append("target timeline")
    size = _size(inquiry)
    if size == "unknown":
        missing.append("company size")
    if not role:
        missing.append("contact's role / decision-maker")

    return LeadFields(
        company_name=company,
        contact_name=name,
        contact_role=role,
        industry=industry,
        need_types=need_types,
        need_summary=need_summary,
        budget_signal=budget_signal,
        budget_amount_usd=budget_usd,
        timeline=timeline,
        timeline_months=months,
        urgency=urgency,
        company_size=size,
        decision_maker_present=bool(role) and any(t in (role or "").lower() for t in titles),
        region=region,
        off_scope=off_scope,
        missing_info=missing,
    )
