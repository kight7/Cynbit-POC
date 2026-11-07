"""End-to-end orchestration: inquiry -> fields -> retrieval -> score/route -> grounded draft -> guardrail."""
from __future__ import annotations

import time

from .corpus import case_by_id
from .extraction import extract_offline, extract_with_llm
from .guardrail import check_draft
from .llm import LLMClient, LLMError
from .proposal import build_context, decline_offscope, draft_baseline, draft_offline, draft_with_llm
from .retriever import HybridRetriever, build_query
from .schemas import CopilotResult
from .scoring import route_lead, score_lead


class Copilot:
    def __init__(self, retriever: HybridRetriever | None = None, provider: str | None = None):
        self.retriever = retriever or HybridRetriever()
        self.cases = case_by_id()
        self.provider = provider
        self._case_industries = {cid: c.industries for cid, c in self.cases.items()}
        self.corpus_text = "\n".join(c.text for c in self.retriever.chunks)

    def run(self, inquiry: str, use_rag: bool = True, top_k: int = 3) -> CopilotResult:
        llm = LLMClient(self.provider)
        notices = [self.retriever.notice] if self.retriever.notice else []
        lat = {}
        t_all = time.perf_counter()

        # 1. Extraction
        t = time.perf_counter()
        fields = None
        if llm.enabled:
            try:
                fields = extract_with_llm(inquiry, llm)
            except LLMError as e:
                notices.append(f"LLM extraction failed, used offline extractor instead: {str(e)[:200]}")
        if fields is None:
            fields = extract_offline(inquiry)
        lat["extraction"] = round((time.perf_counter() - t) * 1000)

        # 2. Retrieval
        t = time.perf_counter()
        retrieved = [] if fields.off_scope else self.retriever.search(build_query(fields, inquiry), fields.industry, top_k)
        lat["retrieval"] = round((time.perf_counter() - t) * 1000)

        # 3. Score + route
        score = score_lead(fields, retrieved, self._case_industries)
        route = route_lead(fields, score)

        # 4. Draft
        t = time.perf_counter()
        mode = llm.label if llm.enabled else "offline"
        if fields.off_scope:
            draft = decline_offscope(fields)
        elif llm.enabled:
            try:
                draft = draft_with_llm(inquiry, fields, retrieved, llm) if use_rag else draft_baseline(inquiry, llm)
                mode = llm.label
            except LLMError as e:
                notices.append(f"LLM drafting failed, used the offline template: {str(e)[:200]}")
                draft, mode = draft_offline(fields, retrieved, self.cases), "offline"
        else:
            draft = draft_offline(fields, retrieved, self.cases)
        lat["drafting"] = round((time.perf_counter() - t) * 1000)

        # 5. Guardrail (baseline is checked against the whole corpus: anything outside it is fabricated)
        context = build_context(retrieved) if use_rag else self.corpus_text
        guard = check_draft(draft, context, inquiry, [c.case_id for c in retrieved] if use_rag else list(self.cases))
        lat["total"] = round((time.perf_counter() - t_all) * 1000)
        lat["llm_calls"] = llm.usage.calls
        lat["tokens"] = llm.usage.prompt_tokens + llm.usage.completion_tokens
        lat["cost_usd"] = round(llm.usage.cost_usd, 5)

        return CopilotResult(
            inquiry=inquiry,
            mode=mode if llm.enabled or mode != "offline" else "offline",
            fields=fields,
            score=score,
            route=route,
            retrieved=retrieved,
            proposal_markdown=draft,
            guardrail=guard,
            latency_ms=lat,
            notices=notices,
        )
