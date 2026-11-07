"""Cynbit Pre-Sales Copilot: Streamlit UI.

Run locally:  streamlit run app.py
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from copilot.config import DEFAULT_MODELS, EVAL_DIR, get_secret, rubric
from copilot.guardrail import highlight_unverified
from copilot.pipeline import Copilot

st.set_page_config(page_title="Cynbit Pre-Sales Copilot", page_icon="🧭", layout="wide")

st.markdown(
    """
<style>
.block-container {padding-top: 1.6rem; max-width: 1300px;}
.pill {display:inline-block;padding:2px 10px;border-radius:999px;font-size:0.8rem;font-weight:600;margin-right:6px}
.hot {background:#fde2e1;color:#b42318} .warm {background:#fef0c7;color:#93370d} .cold {background:#e0eaff;color:#1d4ed8}
.src {border:1px solid rgba(128,128,128,.25);border-radius:10px;padding:10px 12px;margin-bottom:10px}
.small {font-size:0.85rem;opacity:.8}
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner="Loading case studies and building the vector index…")
def get_copilot() -> Copilot:
    return Copilot()


@st.cache_data
def samples() -> dict[str, str]:
    rows = [json.loads(x) for x in (EVAL_DIR / "inquiries.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    pick = {"Q01": "Telehealth AI triage (hot)", "Q13": "Cross-border payments, Dubai", "Q04": "Ticketing site crashes",
            "Q11": "Local SEO for a store chain", "Q21": "Vague: small clinic", "Q26": "Off-scope: photographer"}
    by_id = {r["id"]: r["text"] for r in rows}
    return {label: by_id[i] for i, label in pick.items()}


cp = get_copilot()

# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("⚙️ Settings")
    has_groq, has_gem = bool(get_secret("GROQ_API_KEY")), bool(get_secret("GEMINI_API_KEY"))
    options = ["Auto"] + (["Groq"] if has_groq else []) + (["Gemini"] if has_gem else []) + ["Offline (no LLM)"]
    choice = st.selectbox("LLM provider", options, help="Auto = Groq, falling back to Gemini, then offline")
    st.caption(
        f"Groq {'✅' if has_groq else '❌ no key'} · `{get_secret('GROQ_MODEL', DEFAULT_MODELS['groq'])}`  \n"
        f"Gemini {'✅' if has_gem else '❌ no key'} · `{get_secret('GEMINI_MODEL', DEFAULT_MODELS['gemini'])}`  \n"
        f"Embeddings: `{cp.retriever.backend.name}`"
    )
    if not (has_groq or has_gem):
        st.info("No API key configured, so the app runs in **offline mode**: a rule-based extractor and a template draft "
                "that copies case-study evidence verbatim.")
    top_k = st.slider("Case studies to retrieve", 1, 5, 3)
    st.divider()
    with st.expander("Lead-score rubric"):
        for f in rubric()["factors"].values():
            st.markdown(f"- **{f['label']}**: {f['max']} pts")
        st.caption("Editable in `config/rubric.yaml`; routing rules are in `config/routing.yaml`.")
    st.caption("Corpus: 13 Cynbit case studies (claims as reported on cynbit.in, not independently verified).")

provider = {"Auto": None, "Groq": "groq", "Gemini": "gemini", "Offline (no LLM)": "offline"}[choice]
cp.provider = provider

# ----------------------------------------------------------------------------- input
st.title("🧭 Cynbit Pre-Sales Copilot")
st.markdown("Paste an inbound inquiry. The copilot **extracts** the lead details, **scores and routes** the lead, "
            "**retrieves** Cynbit's most relevant case studies, and **drafts a grounded reply** that cites them.")

c1, c2 = st.columns([3, 1])
with c2:
    sample = st.selectbox("Try a sample", ["—"] + list(samples()), key="sample")
    up = st.file_uploader("…or upload (.txt / .md / .eml)", type=["txt", "md", "eml"])
default = ""
if up is not None:
    default = up.read().decode("utf-8", errors="ignore")
elif sample != "—":
    default = samples()[sample]
with c1:
    inquiry = st.text_area("Inbound inquiry", value=default, height=190, placeholder="Hi Cynbit, we are…")
    run = st.button("Analyse inquiry", type="primary", disabled=not inquiry.strip(), key="run")

if run:
    with st.spinner("Extracting → retrieving → scoring → drafting…"):
        st.session_state["result"] = cp.run(inquiry.strip(), top_k=top_k)
        st.session_state.pop("baseline", None)

res = st.session_state.get("result")
if not res:
    st.stop()

for n in res.notices:
    st.warning(n)

# ----------------------------------------------------------------------------- KPIs
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Lead score", f"{res.score.total}/100")
k1.markdown(f"<span class='pill {res.score.tier}'>{res.score.tier.upper()}</span>", unsafe_allow_html=True)
top = res.retrieved[0] if res.retrieved else None
k2.markdown(f"<span class='small'>Routed to</span><br><b style='font-size:1.15rem'>{res.route.team}</b><br>"
            f"<span class='small'>{res.route.owner}</span>", unsafe_allow_html=True)
k3.markdown(f"<span class='small'>Best match</span><br><b style='font-size:1.15rem'>{top.case_id} · {top.client}</b><br>"
            f"<span class='small'>{top.title}</span>" if top else "<span class='small'>Best match</span><br><b>—</b>",
            unsafe_allow_html=True)
g = res.guardrail
k4.metric("Guardrail", "Passed" if g.passed else f"{len(g.unverified_numbers) + len(g.invalid_citations)} flags")
k4.caption(f"Faithfulness {g.faithfulness:.0%} ({g.numbers_verified}/{g.numbers_total} numbers sourced)")
k5.metric("Latency", f"{res.latency_ms['total'] / 1000:.1f}s")
k5.caption(f"{res.mode} · {res.latency_ms['llm_calls']} LLM calls · ${res.latency_ms['cost_usd']:.4f}")

t1, t2, t3, t4, t5 = st.tabs(["📝 Draft reply", "🎯 Lead triage", "🔎 Evidence", "⚖️ RAG vs no-RAG", "📊 Evaluation"])

# ----------------------------------------------------------------------------- draft
with t1:
    left, right = st.columns([2.2, 1])
    with left:
        if not g.passed:
            st.warning("Highlighted numbers (⚠️) were not found in the retrieved sources or in the inquiry. Check them before sending.")
        st.markdown(highlight_unverified(res.proposal_markdown, g.unverified_numbers))
        st.download_button("⬇️ Download draft (.md)", res.proposal_markdown, file_name="cynbit_draft_reply.md")
    with right:
        st.subheader("Sources used")
        if not res.retrieved:
            st.caption("No sources: the request was classified as off-scope.")
        for c in res.retrieved:
            cited = "✅ cited" if c.case_id in g.citations_used else "· not cited"
            label = cp.retriever.confidence_label(c.confidence)
            metrics = "<br>".join(f"• {m}" for m in c.metrics) or "<i>no quantified outcome published</i>"
            st.markdown(
                f"<div class='src'><b>[{c.case_id}] {c.client}</b> <span class='small'>{cited}</span><br>"
                f"<span class='small'>{c.title}</span><br><span class='small'>{c.industry} · relevance: {label}</span><br>"
                f"<span class='small'>{metrics}</span><br><a href='{c.source_url}' target='_blank' class='small'>source ↗</a></div>",
                unsafe_allow_html=True,
            )

# ----------------------------------------------------------------------------- triage
with t2:
    f = res.fields
    a, b = st.columns(2)
    with a:
        st.subheader("Extracted fields")
        rows = {
            "Company": f.company_name, "Contact": f.contact_name, "Role": f.contact_role,
            "Industry": f.industry, "Need types": ", ".join(f.need_types) or None, "Need": f.need_summary,
            "Budget": f.budget_signal + (f" (~${f.budget_amount_usd:,.0f})" if f.budget_amount_usd else "") if f.budget_signal else None,
            "Timeline": f.timeline, "Urgency": f.urgency, "Company size": f.company_size,
            "Decision-maker": "yes" if f.decision_maker_present else "no", "Region": f.region, "Off-scope": "yes" if f.off_scope else "no",
        }
        st.table({"Field": list(rows), "Value": [v if v not in (None, "") else "— not stated" for v in rows.values()]})
        if f.missing_info:
            st.markdown("**Ask the client about:** " + "; ".join(f.missing_info))
    with b:
        st.subheader(f"Score breakdown: {res.score.total}/100")
        for it in res.score.breakdown:
            st.progress(it.points / it.max_points if it.max_points else 0, text=f"{it.label}: {it.points}/{it.max_points}")
            st.caption(it.reason)
        st.subheader("Routing")
        st.markdown(f"**{res.route.team}** → {res.route.owner}  \nRule matched: *{res.route.rule}*  \nSLA: {res.route.sla}")

# ----------------------------------------------------------------------------- evidence
with t3:
    st.caption("Hybrid retrieval: dense vectors in ChromaDB + BM25, fused with reciprocal-rank fusion and an industry boost.")
    for c in res.retrieved:
        with st.expander(f"{c.case_id} · {c.client}: case score {c.score:.4f}, best cosine {c.confidence:.2f} ({cp.retriever.confidence_label(c.confidence)})"):
            for ch in c.chunks:
                st.markdown(f"**{ch['section']}** · fused {ch['fused_score']:.4f} · cosine {ch['cosine']:.2f}")
                st.code(ch["text"], language=None, wrap_lines=True)
    st.subheader("Guardrail report")
    st.json(g.model_dump())
    st.subheader("Full JSON output")
    payload = res.model_dump()
    st.json(payload, expanded=False)
    st.download_button("⬇️ Download JSON", json.dumps(payload, indent=2, default=str), file_name="cynbit_copilot_result.json")

# ----------------------------------------------------------------------------- baseline
with t4:
    st.markdown("Same LLM and same inquiry, **without** retrieved context. Numbers that don't appear anywhere in Cynbit's "
                "case-study corpus or in the inquiry are flagged as unsupported.")
    if res.mode == "offline" or res.fields.off_scope:
        st.info("Needs an LLM provider (and an in-scope inquiry). Add GROQ_API_KEY or GEMINI_API_KEY to the secrets.")
    elif st.button("Generate no-RAG baseline"):
        with st.spinner("Drafting without retrieval…"):
            st.session_state["baseline"] = cp.run(res.inquiry, use_rag=False, top_k=top_k)
    base = st.session_state.get("baseline")
    if base:
        l, r = st.columns(2)
        with l:
            bg = base.guardrail
            st.markdown(f"#### ❌ No RAG: faithfulness {bg.faithfulness:.0%}, {len(bg.unverified_numbers)} unsupported numbers")
            st.markdown(highlight_unverified(base.proposal_markdown, bg.unverified_numbers))
        with r:
            st.markdown(f"#### ✅ RAG + guardrail: faithfulness {g.faithfulness:.0%}, {len(g.unverified_numbers)} unsupported numbers")
            st.markdown(highlight_unverified(res.proposal_markdown, g.unverified_numbers))

# ----------------------------------------------------------------------------- evaluation
with t5:
    for name in ("summary_llm.md", "summary_offline.md"):
        p = Path(EVAL_DIR / "results" / name)
        if p.exists():
            st.markdown(p.read_text(encoding="utf-8"))
            break
    else:
        st.info("Run `python -m eval.run_eval` to generate evaluation results.")
