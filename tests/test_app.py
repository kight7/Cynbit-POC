"""Headless UI smoke test using Streamlit's AppTest (no browser needed)."""
import os

os.environ.setdefault("EMBED_BACKEND", "tfidf")
from streamlit.testing.v1 import AppTest  # noqa: E402


def test_app_runs_end_to_end():
    at = AppTest.from_file("../app.py", default_timeout=120)
    at.run()
    assert not at.exception
    at.selectbox(key="sample").select("Telehealth AI triage (hot)").run()
    at.button(key="run").click().run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert "Lead score" in labels and "Guardrail" in labels
    assert any("CS-01 · WizHealth" in m.value for m in at.markdown)
    assert len(at.tabs) == 5
