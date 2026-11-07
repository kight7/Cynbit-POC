"""Evaluate the Pre-Sales Copilot on the 30 labelled inquiries.

Usage (from the repo root):
    python -m eval.run_eval                 # uses an LLM if GROQ_API_KEY / GEMINI_API_KEY is set, else offline
    python -m eval.run_eval --mode offline  # force the deterministic, no-key pipeline
    python -m eval.run_eval --baseline 10   # also compare no-RAG vs RAG drafts on 10 inquiries (LLM mode only)

Writes eval/results/summary_<mode>.md and eval/results/details_<mode>.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from copilot.pipeline import Copilot  # noqa: E402
from copilot.retriever import build_query  # noqa: E402

RESULTS = ROOT / "eval" / "results"


def load_set():
    with open(ROOT / "eval" / "inquiries.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def pct(x):
    return f"{100 * x:.0f}%"


def ranks(pred_ids, gold):
    for i, cid in enumerate(pred_ids):
        if cid in gold:
            return i + 1
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["auto", "offline", "groq", "gemini"], default="auto")
    ap.add_argument("--baseline", type=int, default=10, help="# inquiries for the no-RAG vs RAG comparison")
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds between LLM requests (free-tier rate limits)")
    args = ap.parse_args()

    provider = None if args.mode == "auto" else args.mode
    cp = Copilot(provider=provider)
    data = load_set()
    rows = []
    for ex in data:
        r = cp.run(ex["text"])
        f = r.fields
        ids = [c.case_id for c in r.retrieved]
        rows.append({
            "id": ex["id"], "category": ex["category"], "mode": r.mode,
            "gold": ex, "pred": f.model_dump(), "retrieved": ids,
            "rank": ranks(ids, ex["expected_cases"]) if ex["expected_cases"] else None,
            "score": r.score.total, "tier": r.score.tier, "route": r.route.team,
            "faithfulness": r.guardrail.faithfulness, "guard_passed": r.guardrail.passed,
            "unverified": r.guardrail.unverified_numbers, "invalid_citations": r.guardrail.invalid_citations,
            "latency_ms": r.latency_ms["total"], "cost_usd": r.latency_ms["cost_usd"],
            "tokens": r.latency_ms["tokens"], "notices": r.notices, "draft": r.proposal_markdown,
        })
        print(f"{ex['id']} {r.mode:28s} top3={ids} score={r.score.total:3d} faith={r.guardrail.faithfulness:.2f} {r.latency_ms['total']}ms")
        if args.sleep:
            time.sleep(args.sleep)

    mode = rows[0]["mode"] if all(rw["mode"] == rows[0]["mode"] for rw in rows) else "mixed"
    mode_tag = "offline" if mode == "offline" else "llm"

    # ---------------------------------------------------------------- extraction accuracy
    def acc(name, fn, subset=None):
        items = [rw for rw in rows if (subset is None or subset(rw))]
        ok = sum(1 for rw in items if fn(rw))
        return name, ok, len(items)

    ext = [
        acc("Industry", lambda rw: rw["pred"]["industry"] == rw["gold"]["industry"] or (rw["gold"]["industry"] is None and rw["pred"]["industry"] in (None, "other")),
            lambda rw: not rw["gold"]["off_scope"]),
        acc("Primary need type detected", lambda rw: rw["gold"]["primary_need"] in rw["pred"]["need_types"],
            lambda rw: rw["gold"]["primary_need"] is not None),
        acc("Urgency", lambda rw: rw["pred"]["urgency"] == rw["gold"]["urgency"], lambda rw: not rw["gold"]["off_scope"]),
        acc("Budget present", lambda rw: (rw["pred"]["budget_signal"] is not None) == rw["gold"]["budget_present"]),
        acc("Decision-maker present", lambda rw: rw["pred"]["decision_maker_present"] == rw["gold"]["decision_maker"]),
        acc("Off-scope flag", lambda rw: rw["pred"]["off_scope"] == rw["gold"]["off_scope"]),
    ]

    # ---------------------------------------------------------------- retrieval
    ret_rows = [rw for rw in rows if rw["gold"]["expected_cases"]]
    hit1 = sum(1 for rw in ret_rows if rw["rank"] == 1) / len(ret_rows)
    hit3 = sum(1 for rw in ret_rows if rw["rank"] is not None) / len(ret_rows)
    mrr = sum(1 / rw["rank"] for rw in ret_rows if rw["rank"]) / len(ret_rows)
    clear = [rw for rw in ret_rows if rw["category"] == "clear"]
    hit3_clear = sum(1 for rw in clear if rw["rank"] is not None) / len(clear)

    # ablation (retriever only, using the extracted fields from this run)
    ablation = []
    for name, kw in [("Dense only", dict(use_bm25=False, industry_boost=False)),
                     ("BM25 only", dict(use_dense=False, industry_boost=False)),
                     ("Hybrid (RRF)", dict(industry_boost=False)),
                     ("Hybrid + industry boost (default)", {})]:
        hits = 0
        for rw in ret_rows:
            from copilot.schemas import LeadFields
            f = LeadFields(**rw["pred"])
            res = cp.retriever.search(build_query(f, rw["gold"]["text"]), f.industry, 3, **kw)
            hits += ranks([c.case_id for c in res], rw["gold"]["expected_cases"]) is not None
        ablation.append((name, hits / len(ret_rows)))

    # ---------------------------------------------------------------- generation + ops
    drafted = [rw for rw in rows if not rw["pred"]["off_scope"]]
    faith = statistics.mean(rw["faithfulness"] for rw in drafted)
    passed = sum(rw["guard_passed"] for rw in drafted) / len(drafted)
    lat = sorted(rw["latency_ms"] for rw in rows)
    p50 = lat[len(lat) // 2]
    p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))]
    cost = statistics.mean(rw["cost_usd"] for rw in rows)
    toks = statistics.mean(rw["tokens"] for rw in rows)

    # ---------------------------------------------------------------- baseline vs RAG
    base_rows = []
    if mode_tag == "llm" and args.baseline:
        for ex in [d for d in data if d["category"] == "clear"][: args.baseline]:
            rag = next(rw for rw in rows if rw["id"] == ex["id"])
            b = cp.run(ex["text"], use_rag=False)
            base_rows.append({
                "id": ex["id"],
                "baseline_numbers": b.guardrail.numbers_total, "baseline_unverified": b.guardrail.unverified_numbers,
                "baseline_faith": b.guardrail.faithfulness,
                "rag_numbers": len(rag["unverified"]) + int(round(rag["faithfulness"] * 0)),
                "rag_unverified": rag["unverified"], "rag_faith": rag["faithfulness"],
                "baseline_draft": b.proposal_markdown,
            })
            print(f"baseline {ex['id']} faith={b.guardrail.faithfulness:.2f} unverified={b.guardrail.unverified_numbers}")
            if args.sleep:
                time.sleep(args.sleep)

    # ---------------------------------------------------------------- report
    L = [f"# Evaluation results ({mode})", "",
         f"Run: {time.strftime('%Y-%m-%d %H:%M')} | embedding backend: `{cp.retriever.backend.name}` | 30 inquiries (20 clear, 5 vague, 5 off-scope)", "",
         "## Extraction field accuracy", "", "| Field | Correct | Accuracy |", "|---|---|---|"]
    L += [f"| {n} | {ok}/{tot} | {pct(ok / tot)} |" for n, ok, tot in ext]
    L += ["", "## Retrieval (25 inquiries with a labelled best case study)", "", "| Metric | Value |", "|---|---|",
          f"| Hit@1 | {pct(hit1)} |", f"| **Hit@3** | **{pct(hit3)}** |", f"| Hit@3 (20 clear only) | {pct(hit3_clear)} |", f"| MRR | {mrr:.2f} |",
          "", "### Retrieval ablation (Hit@3)", "", "| Variant | Hit@3 |", "|---|---|"]
    L += [f"| {n} | {pct(v)} |" for n, v in ablation]
    L += ["", "## Generation & operations", "", "| Metric | Value |", "|---|---|",
          f"| Faithfulness (share of draft numbers traceable to sources or the inquiry) | {pct(faith)} |",
          f"| Drafts passing the guardrail (no unverified numbers or invalid citations) | {pct(passed)} |",
          f"| Latency p50 / p95 | {p50} ms / {p95} ms |",
          f"| Mean tokens per request | {toks:.0f} |",
          f"| Mean cost per request (list prices) | ${cost:.5f} |"]
    if base_rows:
        bf = statistics.mean(x["baseline_faith"] for x in base_rows)
        rf = statistics.mean(x["rag_faith"] for x in base_rows)
        bu = sum(len(x["baseline_unverified"]) for x in base_rows)
        ru = sum(len(x["rag_unverified"]) for x in base_rows)
        L += ["", f"## Baseline (no RAG) vs RAG on {len(base_rows)} clear inquiries", "",
              "| | No-RAG baseline | RAG + guardrail |", "|---|---|---|",
              f"| Mean faithfulness | {pct(bf)} | {pct(rf)} |",
              f"| Unsupported numbers (total) | {bu} | {ru} |", "",
              "| Inquiry | Baseline unsupported numbers | RAG unsupported numbers |", "|---|---|---|"]
        L += [f"| {x['id']} | {', '.join(x['baseline_unverified']) or '-'} | {', '.join(x['rag_unverified']) or '-'} |" for x in base_rows]
    elif mode_tag == "offline":
        L += ["", "_No-RAG baseline comparison needs an LLM: set GROQ_API_KEY and re-run `python -m eval.run_eval`._"]

    misses = [rw for rw in ret_rows if rw["rank"] is None]
    wrong_ind = [rw for rw in rows if not rw["gold"]["off_scope"] and rw["pred"]["industry"] != rw["gold"]["industry"]]
    L += ["", "## Failure cases", ""]
    for rw in misses:
        L.append(f"- **{rw['id']}** ({rw['category']}): expected {rw['gold']['expected_cases']}, got {rw['retrieved']}")
    for rw in wrong_ind[:8]:
        L.append(f"- **{rw['id']}** industry: expected `{rw['gold']['industry']}`, extracted `{rw['pred']['industry']}`")
    if not misses and not wrong_ind:
        L.append("- none")

    L += ["", "## Per-inquiry results", "", "| ID | Cat. | Top-3 retrieved | Expected | Score | Tier | Route | Faith. |", "|---|---|---|---|---|---|---|---|"]
    for rw in rows:
        L.append(f"| {rw['id']} | {rw['category']} | {', '.join(rw['retrieved']) or '-'} | {', '.join(rw['gold']['expected_cases']) or '-'} | {rw['score']} | {rw['tier']} | {rw['route']} | {rw['faithfulness']:.2f} |")

    metrics = {
        "mode": mode, "embedding": cp.retriever.backend.name,
        "extraction": {n: ok / tot for n, ok, tot in ext},
        "hit1": hit1, "hit3": hit3, "mrr": mrr, "ablation": dict(ablation),
        "faithfulness": faith, "guard_pass": passed, "p50_ms": p50, "p95_ms": p95,
        "tokens": toks, "cost_usd": cost,
        "baseline": None if not base_rows else {
            "n": len(base_rows),
            "base_faith": statistics.mean(x["baseline_faith"] for x in base_rows),
            "rag_faith": statistics.mean(x["rag_faith"] for x in base_rows),
            "base_unsupported": sum(len(x["baseline_unverified"]) for x in base_rows),
            "rag_unsupported": sum(len(x["rag_unverified"]) for x in base_rows),
        },
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"summary_{mode_tag}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (RESULTS / f"details_{mode_tag}.json").write_text(
        json.dumps({"metrics": metrics, "rows": rows, "baseline": base_rows}, indent=2, default=str), encoding="utf-8")
    update_report()
    print("\n".join(L[:40]))
    print(f"\nSaved -> eval/results/summary_{mode_tag}.md")


def update_report():
    """Write a comparison table (offline vs LLM) into docs/02_Technical_Approach_Report.md."""
    runs = {}
    for tag in ("offline", "llm"):
        f = RESULTS / f"details_{tag}.json"
        if f.exists():
            runs[tag] = json.loads(f.read_text(encoding="utf-8")).get("metrics")
    runs = {k: v for k, v in runs.items() if v}
    if not runs:
        return
    cols = [t for t in ("llm", "offline") if t in runs]
    head = {"llm": f"LLM mode (`{runs.get('llm', {}).get('mode', '')}` + `{runs.get('llm', {}).get('embedding', '')}`)",
            "offline": f"Offline mode (rules + `{runs.get('offline', {}).get('embedding', '')}`)"}
    T = ["| Metric | " + " | ".join(head[c] for c in cols) + " |", "|---|" + "---|" * len(cols)]

    def row(label, fn):
        T.append(f"| {label} | " + " | ".join(fn(runs[c]) for c in cols) + " |")

    for name in next(iter(runs.values()))["extraction"]:
        row(f"Extraction: {name}", lambda m, n=name: pct(m["extraction"][n]))
    row("**Retrieval Hit@3**", lambda m: f"**{pct(m['hit3'])}**")
    row("Retrieval Hit@1 / MRR", lambda m: f"{pct(m['hit1'])} / {m['mrr']:.2f}")
    row("Draft faithfulness (numbers traceable to sources)", lambda m: pct(m["faithfulness"]))
    row("Drafts passing guardrail", lambda m: pct(m["guard_pass"]))
    def _t(ms):
        return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:.1f} s"

    row("Latency p50 / p95", lambda m: f"{_t(m['p50_ms'])} / {_t(m['p95_ms'])}")
    row("Tokens / cost per inquiry", lambda m: f"{m['tokens']:.0f} / ${m['cost_usd']:.4f}")
    out = ["_Generated by `python -m eval.run_eval` on " + time.strftime("%Y-%m-%d") + ". Full tables: `eval/results/`._", ""] + T
    m0 = runs.get("llm") or runs["offline"]
    out += ["", "**Retrieval ablation (Hit@3, embedding backend: " + m0["embedding"] + "):** " +
            " · ".join(f"{k}: {pct(v)}" for k, v in m0["ablation"].items())]
    b = runs.get("llm", {}).get("baseline")
    if b:
        out += ["", f"**No-RAG baseline vs RAG ({b['n']} clear inquiries, same LLM):**", "",
                "| | No-RAG baseline | RAG + guardrail |", "|---|---|---|",
                f"| Mean faithfulness | {pct(b['base_faith'])} | {pct(b['rag_faith'])} |",
                f"| Unsupported numbers (total) | {b['base_unsupported']} | {b['rag_unsupported']} |"]
    else:
        out += ["", "_No-RAG vs RAG comparison: run with an API key to generate._"]
    rp = ROOT / "docs" / "02_Technical_Approach_Report.md"
    if rp.exists():
        txt = rp.read_text(encoding="utf-8")
        a, z = "<!-- EVAL:START -->", "<!-- EVAL:END -->"
        if a in txt and z in txt:
            txt = txt.split(a)[0] + a + "\n" + "\n".join(out) + "\n" + z + txt.split(z)[1]
            rp.write_text(txt, encoding="utf-8")
            print("Updated evaluation section in docs/02_Technical_Approach_Report.md")


if __name__ == "__main__":
    main()
