"""Unit tests: run with `pytest -q`. They use the offline paths, so no API key is needed."""
import json
import os

import pytest

os.environ.setdefault("EMBED_BACKEND", "tfidf")  # fast and offline for CI

from copilot import llm as llm_mod  # noqa: E402
from copilot.corpus import build_chunks, load_case_studies  # noqa: E402
from copilot.extraction import extract_offline  # noqa: E402
from copilot.guardrail import check_draft, numbers_in  # noqa: E402
from copilot.pipeline import Copilot  # noqa: E402
from copilot.schemas import LeadFields  # noqa: E402
from copilot.scoring import route_lead, score_lead  # noqa: E402


@pytest.fixture(scope="module")
def copilot():
    return Copilot(provider="offline")


def test_corpus_has_13_cases_and_metrics():
    cases = load_case_studies()
    assert len(cases) == 13
    ids = {c.case_id: c for c in cases}
    assert "Improved triage efficiency by 25%" in ids["CS-01"].metrics
    assert ids["CS-13"].industries == ["fintech"]


def test_speculative_sections_not_indexed():
    sections = {c.section for c in build_chunks()}
    assert "AI/ML opportunity" not in sections and "Source notes" not in sections


def test_offline_extraction_fields():
    f = extract_offline(
        "We need a payments backend with fraud detection. Budget $80k-120k, MVP in 8 weeks.\n"
        "Regards,\nOmar Haddad\nCTO, PayBridge, Dubai"
    )
    assert f.industry == "fintech"
    assert "payments" in f.need_types
    assert f.budget_amount_usd == 120000
    assert f.urgency == "high"
    assert f.decision_maker_present
    assert f.region == "middle_east"


def test_inr_budget_conversion():
    f = extract_offline("Our budget is around 25 lakhs for a mobile app")
    assert 29000 < f.budget_amount_usd < 30500


def test_off_scope_detected():
    assert extract_offline("Looking for a wedding photographer in December").off_scope


def test_scoring_and_routing_hot_healthcare(copilot):
    r = copilot.run("I'm the CTO of a 300-person hospital group. We need AI to triage patient symptom "
                    "messages and integrate with our EHR. Budget $60k, pilot within 2 months.")
    assert r.retrieved[0].case_id == "CS-01"
    assert r.score.tier == "hot"
    assert r.route.team.startswith("Healthcare")
    assert sum(b.points for b in r.score.breakdown) == r.score.total


def test_off_scope_routes_to_inbound(copilot):
    r = copilot.run("Need 500 printed t-shirts for our company offsite")
    assert r.fields.off_scope and r.route.team == "Inbound Desk" and not r.retrieved


def test_offline_draft_is_faithful(copilot):
    r = copilot.run("Our concert ticketing site crashes during big ticket drops. Need help ASAP.")
    assert r.guardrail.passed, r.guardrail
    assert r.guardrail.invalid_citations == []


def test_guardrail_flags_invented_numbers():
    ctx = "[CS-01] Improved triage efficiency by 25%"
    rep = check_draft("We improved efficiency by 25% [CS-01] and cut costs by 70% [CS-07].", ctx, "", ["CS-01"])
    assert "70%" in rep.unverified_numbers and "CS-07" in rep.invalid_citations and not rep.passed


def test_numbers_ignore_list_markers_and_citations():
    assert [d for d, _ in numbers_in("1. Discovery [CS-03]\n2. Build\nPhase 3")] == []


def test_rubric_total_is_100():
    from copilot.config import rubric

    assert sum(f["max"] for f in rubric()["factors"].values()) == 100


def test_route_default_exists():
    f = LeadFields(need_types=["web_platform"], need_summary="x", budget_amount_usd=50000, budget_signal="$50k",
                   urgency="high", industry="logistics")
    s = score_lead(f, [], {})
    assert route_lead(f, s).team


def test_llm_structured_retry(monkeypatch):
    """First response is broken JSON, second is valid -> structured() must recover."""
    monkeypatch.setenv("GROQ_API_KEY", "test")
    replies = iter(["not json at all", json.dumps({"industry": "fintech", "need_types": ["payments"]})])

    class R:
        status_code = 200
        headers = {}

        def __init__(self, content):
            self._c = content
            self.text = content

        def json(self):
            return {"choices": [{"message": {"content": self._c}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    monkeypatch.setattr(llm_mod.requests, "post", lambda *a, **k: R(next(replies)))
    client = llm_mod.LLMClient()
    out = client.structured([{"role": "user", "content": "x"}], LeadFields)
    assert out.industry == "fintech" and client.usage.calls == 2


def test_llm_fallback_to_second_provider(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "a")
    monkeypatch.setenv("GEMINI_API_KEY", "b")

    class R:
        headers = {}

        def __init__(self, code, content=""):
            self.status_code, self._c, self.text = code, content, content

        def json(self):
            return {"choices": [{"message": {"content": self._c}}], "usage": {}}

    def fake_post(url, **kw):
        return R(500, "boom") if "groq" in url else R(200, "hello from gemini")

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    c = llm_mod.LLMClient()
    assert c.chat([{"role": "user", "content": "hi"}]) == "hello from gemini"
    assert c.last_provider.name == "gemini"
