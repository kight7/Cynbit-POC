"""Stage 2: transparent lead scoring (rubric in config/rubric.yaml) and rule-based routing."""
from __future__ import annotations

from .config import routing_rules, rubric
from .schemas import LeadFields, LeadScore, RetrievedCase, Route, ScoreItem


def score_lead(f: LeadFields, retrieved: list[RetrievedCase], case_industries: dict[str, list[str]]) -> LeadScore:
    rb = rubric()
    fac = rb["factors"]
    items: list[ScoreItem] = []

    # 1. Service fit
    r = fac["service_fit"]["rules"]
    if f.off_scope:
        pts, why = r["no_match"], "Request is outside Cynbit's services"
    elif f.need_types:
        pts, why = r["clear_match"], "Need maps to: " + ", ".join(n.replace("_", " ") for n in f.need_types)
    elif f.need_summary:
        pts, why = r["vague_match"], "A need is described, but it doesn't map clearly to a service line"
    else:
        pts, why = r["no_match"], "No identifiable need"
    items.append(ScoreItem(factor="service_fit", label=fac["service_fit"]["label"], points=pts, max_points=fac["service_fit"]["max"], reason=why))

    # 2. Budget
    r = fac["budget"]["rules"]
    if f.budget_amount_usd:
        pts, why = r["explicit_amount"], f"Explicit budget: {f.budget_signal} (~${f.budget_amount_usd:,.0f})"
    elif f.budget_signal:
        pts, why = r["soft_signal"], f"Soft budget signal: '{f.budget_signal}'"
    else:
        pts, why = r["none"], "No budget mentioned"
    items.append(ScoreItem(factor="budget", label=fac["budget"]["label"], points=pts, max_points=fac["budget"]["max"], reason=why))

    # 3. Timeline
    r = fac["timeline"]["rules"]
    m = f.timeline_months
    if f.urgency == "high" or (m is not None and m <= 3):
        pts, why = r["within_3_months"], f"Urgent / within 3 months ({f.timeline or 'urgency stated'})"
    elif m is not None and m <= 6:
        pts, why = r["within_6_months"], f"3-6 months ({f.timeline})"
    elif m is not None or f.urgency == "low":
        pts, why = r["longer"], f"Longer horizon ({f.timeline or 'exploring'})"
    else:
        pts, why = r["unknown"], "Timeline not stated"
    items.append(ScoreItem(factor="timeline", label=fac["timeline"]["label"], points=pts, max_points=fac["timeline"]["max"], reason=why))

    # 4. Authority + size
    r = fac["authority_size"]["rules"]
    dm = r["decision_maker"] if f.decision_maker_present else 0
    sz = r["size"].get(f.company_size, 0)
    why = (f"Decision-maker: {f.contact_role}" if dm else "No decision-maker identified") + f"; size: {f.company_size}"
    items.append(ScoreItem(factor="authority_size", label=fac["authority_size"]["label"], points=dm + sz, max_points=fac["authority_size"]["max"], reason=why))

    # 5. Industry match vs retrieved case studies
    r = fac["industry_match"]["rules"]
    if f.off_scope or not retrieved or not f.industry:
        pts, why = r["none"], "Industry unknown or off-scope"
    elif f.industry in case_industries.get(retrieved[0].case_id, []):
        pts, why = r["exact"], f"Top case {retrieved[0].case_id} ({retrieved[0].client}) is in the same industry"
    elif any(f.industry in case_industries.get(c.case_id, []) for c in retrieved):
        pts, why = r["related"], "A top-3 case study shares the industry"
    else:
        pts, why = r["none"], f"No case study in '{f.industry}'"
    items.append(ScoreItem(factor="industry_match", label=fac["industry_match"]["label"], points=pts, max_points=fac["industry_match"]["max"], reason=why))

    total = max(0, min(100, sum(i.points for i in items)))
    tiers = rb["tiers"]
    tier = "hot" if total >= tiers["hot"] else "warm" if total >= tiers["warm"] else "cold"
    return LeadScore(total=total, tier=tier, breakdown=items)


def _matches(cond: dict, f: LeadFields, s: LeadScore) -> bool:
    if "off_scope" in cond and bool(cond["off_scope"]) != f.off_scope:
        return False
    if "min_score" in cond and s.total < cond["min_score"]:
        return False
    if "max_score" in cond and s.total > cond["max_score"]:
        return False
    if "tiers" in cond and s.tier not in cond["tiers"]:
        return False
    if "industries" in cond and f.industry not in cond["industries"]:
        return False
    if "regions" in cond and f.region not in cond["regions"]:
        return False
    if "need_types" in cond and not set(cond["need_types"]) & set(f.need_types):
        return False
    return True


def route_lead(f: LeadFields, s: LeadScore) -> Route:
    for rule in routing_rules():
        if _matches(rule.get("when") or {}, f, s):
            return Route(rule=rule["name"], **rule["route"])
    raise RuntimeError("routing.yaml must end with a catch-all rule")
