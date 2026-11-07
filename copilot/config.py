"""Central configuration: paths, YAML configs, and API settings.

Secrets are read from environment variables first, then from Streamlit secrets
(when running inside Streamlit). Nothing secret is ever hard-coded.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CASE_STUDY_DIR = ROOT / "Cynbit-Case-Studies" / "case-studies"
CONFIG_DIR = ROOT / "config"
CHROMA_DIR = ROOT / ".chroma"
EVAL_DIR = ROOT / "eval"

# Default models (overridable via env / secrets).
# Note: Groq retired llama-3.3-70b-versatile on 2026-08-16; gpt-oss-120b is its recommended replacement.
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "gemini": "gemini-2.5-flash",
}
BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}
EMBED_MODEL = "BAAI/bge-small-en-v1.5"


def get_secret(name: str, default: str | None = None) -> str | None:
    """Read a setting from env vars, then Streamlit secrets (if available)."""
    val = os.environ.get(name)
    if val:
        return val
    try:  # Streamlit is optional (CLI / eval / Colab don't need it)
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return default


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def taxonomy() -> dict:
    return load_yaml("taxonomy.yaml")


def rubric() -> dict:
    return load_yaml("rubric.yaml")


def routing_rules() -> list[dict]:
    return load_yaml("routing.yaml")["rules"]
