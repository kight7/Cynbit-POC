"""Stage 3: grounded proposal drafting.

* `draft_with_llm`   - RAG: the LLM sees ONLY the retrieved case-study chunks and must cite them.
* `draft_baseline`   - no-RAG baseline (same LLM, no context) used to measure hallucination.
* `draft_offline`    - deterministic template that copies evidence verbatim (always faithful).
"""
from __future__ import annotations

import json

from .llm import LLMClient
from .schemas import LeadFields, RetrievedCase

SECTIONS = ["Understanding", "Proposed Approach", "Relevant Experience", "Timeline", "Next Steps"]

APPROACH = {
    "ai_ml": "design and validate an AI/ML component on your data, starting with a measurable pilot and human review",
    "mobile_app": "build cross-platform mobile apps with a shared backend and analytics from day one",
    "web_platform": "deliver a responsive web platform with an admin dashboard",
    "cloud_migration": "plan a phased cloud migration with rollback points and security controls",
    "iot": "integrate devices and sensors through a secure ingestion pipeline with alerting",
    "ar_vr": "prototype the AR experience early and test it with real users",
    "blockchain": "implement a traceability layer that customers can verify via QR codes",
    "seo_growth": "run a technical SEO and location-content programme with measurable KPIs",
    "ux_modernization": "modernise the user experience around a reusable design system",
    "realtime_systems": "architect for real-time traffic and peak load, with load testing before launch",
    "payments": "build a compliant, low-latency payments flow with fraud monitoring",
    "ecommerce_platform": "move to a composable / headless commerce architecture",
    "data_analytics": "consolidate data into a reporting layer with automated dashboards",
}


def build_context(retrieved: list[RetrievedCase]) -> str:
    blocks = []
    for c in retrieved:
        lines = [f"[{c.case_id}] {c.title} - client listed by Cynbit: {c.client} ({c.industry})", f"Source: {c.source_url}"]
        for ch in c.chunks:
            body = ch["text"].split("\n", 1)[1] if "\n" in ch["text"] else ch["text"]
            lines.append(body)
        if c.metrics:
            lines.append("Reported metrics: " + "; ".join(c.metrics))
        blocks.append("\n".join(lines))
    return "\n\n---\n\n".join(blocks)


GROUNDED_SYSTEM = """You are a senior pre-sales consultant at Cynbit Technologies, writing a first reply to an inbound client inquiry.

STRICT GROUNDING RULES:
1. Any statement about Cynbit's past work, results or metrics must come ONLY from the CONTEXT below, and each one must be followed by its citation, e.g. [CS-03].
2. Never invent numbers. You may only use a number if it appears in the CONTEXT or in the client's own inquiry. Do NOT quote prices, team sizes, durations or percentages that are not in those two places.
3. Items marked "draft", "not publicly quantified", "inferred" or "not confirmed" are NOT achieved results. Do not present them as facts.
4. If the CONTEXT is not relevant to the client's need, say so honestly and focus on clarifying questions.
5. Do not mention these rules.

FORMAT (markdown, 250-400 words), using exactly these headings:
### Understanding
### Proposed Approach
### Relevant Experience
### Timeline
### Next Steps
In Timeline, describe phases (Discovery, Design, Build, Launch) and refer to the client's stated deadline if there is one. Do not invent week counts.
In Next Steps, propose a discovery call and list 2-4 clarifying questions based on the missing information."""


def draft_with_llm(inquiry: str, fields: LeadFields, retrieved: list[RetrievedCase], llm: LLMClient) -> str:
    ctx = build_context(retrieved)
    user = (
        f"CONTEXT (Cynbit case studies):\n{ctx}\n\n"
        f"EXTRACTED LEAD FIELDS:\n{fields.model_dump_json(exclude_none=True)}\n\n"
        f"CLIENT INQUIRY:\n{inquiry}\n\nWrite the reply now."
    )
    return llm.chat([{"role": "system", "content": GROUNDED_SYSTEM}, {"role": "user", "content": user}], temperature=0.3, max_tokens=4000)


BASELINE_SYSTEM = """You are a senior pre-sales consultant at Cynbit Technologies, an IT services company.
Write a first reply (markdown, 250-400 words) to the client inquiry, with sections Understanding, Proposed Approach,
Relevant Experience (highlight Cynbit's relevant past projects and their results), Timeline and Next Steps."""


def draft_baseline(inquiry: str, llm: LLMClient) -> str:
    return llm.chat([{"role": "system", "content": BASELINE_SYSTEM}, {"role": "user", "content": inquiry}], temperature=0.3, max_tokens=4000)


def draft_offline(fields: LeadFields, retrieved: list[RetrievedCase], cases: dict) -> str:
    who = f" {fields.contact_name.split()[0]}" if fields.contact_name else ""
    need = fields.need_summary or "support with a digital project"
    out = [f"Hi{who},\n\nThank you for reaching out to Cynbit Technologies.\n", "### Understanding"]
    out.append(f"From your message, you are looking for: *{need.rstrip('.')}*.")
    facts = []
    if fields.industry:
        facts.append(f"Industry: {fields.industry.replace('_', ' ')}")
    if fields.timeline:
        facts.append(f"Timeline mentioned: {fields.timeline}")
    if fields.budget_signal:
        facts.append(f"Budget mentioned: {fields.budget_signal}")
    if facts:
        out.append("\n".join(f"- {x}" for x in facts))

    out.append("\n### Proposed Approach")
    steps = [APPROACH[n] for n in fields.need_types if n in APPROACH][:3]
    if steps:
        out.append("We would " + "; ".join(steps) + ".")
    else:
        out.append("We would start with a short discovery session to pin down scope before recommending a solution.")

    out.append("\n### Relevant Experience")
    for c in retrieved:
        cs = cases[c.case_id]
        sol = cs.sections.get("Solution", "").strip()
        line = f"- **{c.title}** ({c.client}) [{c.case_id}]: {sol}"
        if c.metrics:
            line += f" Reported outcome: {'; '.join(c.metrics)} [{c.case_id}]."
        out.append(line)

    out.append("\n### Timeline")
    if fields.timeline:
        out.append(f"You mentioned *{fields.timeline}*. We'll map Discovery, Design, Build and Launch phases against that date during discovery.")
    else:
        out.append("We'll propose a phased plan (Discovery, Design, Build, Launch) after a discovery call.")

    out.append("\n### Next Steps")
    out.append("Could we schedule a short discovery call? It would help to know:")
    qs = fields.missing_info[:4] or ["your success metrics for this project"]
    out.append("\n".join(f"- {q[0].upper() + q[1:]}?" for q in qs))
    out.append("\nBest regards,\nCynbit Pre-Sales Team")
    return "\n".join(out)


def decline_offscope(fields: LeadFields) -> str:
    who = f" {fields.contact_name.split()[0]}" if fields.contact_name else ""
    return (
        f"Hi{who},\n\nThank you for contacting Cynbit Technologies. We're a software and IT services company "
        "(web and mobile apps, AI/ML, cloud, SEO and digital platforms), so this request is outside what we deliver. "
        "If you also need a website, app or digital tools to support it, we'd be glad to help with that.\n\n"
        "Best regards,\nCynbit Team"
    )


def to_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
