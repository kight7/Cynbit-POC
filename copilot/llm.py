"""Minimal, provider-agnostic LLM client.

Groq and Gemini both expose OpenAI-compatible /chat/completions endpoints, so one small
`requests`-based client covers both. No vendor SDKs = fewer dependency problems on deploy.

Features: provider auto-selection, JSON mode, Pydantic validation with a repair retry,
automatic fallback (Groq -> Gemini -> offline), latency and token accounting.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

import requests
from pydantic import BaseModel, ValidationError

from .config import BASE_URLS, DEFAULT_MODELS, get_secret

# Rough public list prices (USD per 1M tokens) used only for the cost estimate shown in the UI.
PRICES = {
    "openai/gpt-oss-120b": (0.15, 0.60),
    "gemini-2.5-flash": (0.30, 2.50),
}


class LLMError(RuntimeError):
    pass


@dataclass
class LLMUsage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    log: list = field(default_factory=list)


@dataclass
class Provider:
    name: str
    api_key: str
    model: str

    @property
    def base_url(self) -> str:
        return BASE_URLS[self.name]

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model}"


def available_providers(preferred: str | None = None) -> list[Provider]:
    """Providers with keys, in priority order. `preferred` = 'groq' | 'gemini' | 'offline' | None."""
    provs = []
    for name, key_var in (("groq", "GROQ_API_KEY"), ("gemini", "GEMINI_API_KEY")):
        key = get_secret(key_var)
        if key:
            model = get_secret(f"{name.upper()}_MODEL", DEFAULT_MODELS[name])
            provs.append(Provider(name, key, model))
    if preferred == "offline":
        return []
    if preferred:
        provs.sort(key=lambda p: p.name != preferred)
    return provs


def _extract_json(text: str) -> dict:
    """Parse JSON even if the model wrapped it in ```json fences or added prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


class LLMClient:
    def __init__(self, preferred: str | None = None, timeout: int = 60):
        self.providers = available_providers(preferred)
        self.timeout = timeout
        self.usage = LLMUsage()
        self.last_provider: Provider | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.providers)

    @property
    def label(self) -> str:
        p = self.last_provider or (self.providers[0] if self.providers else None)
        return p.label if p else "offline"

    # ---------------------------------------------------------------- transport
    def _post(self, p: Provider, messages, json_mode: bool, temperature: float, max_tokens: int) -> str:
        payload = {
            "model": p.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if (p.name == "groq" and p.model.startswith("openai/gpt-oss")) or (p.name == "gemini" and "2.5" in p.model):
            # Reasoning models: keep thinking short (faster, cheaper, and leaves room in max_tokens for the answer)
            payload["reasoning_effort"] = "low"

        headers = {"Authorization": f"Bearer {p.api_key}", "Content-Type": "application/json"}
        url = f"{p.base_url}/chat/completions"
        attempts = 6
        for attempt in range(attempts):
            t0 = time.perf_counter()
            r = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            ms = (time.perf_counter() - t0) * 1000
            if r.status_code in (429, 503) and attempt < attempts - 1:  # rate limit / overload: back off
                try:
                    wait = float(r.headers.get("retry-after", 0))
                except (TypeError, ValueError):
                    wait = 0
                time.sleep(min(60.0, max(wait, 2.0 * (attempt + 1) ** 2)))
                continue
            if r.status_code == 400 and attempt == 0 and ("reasoning_effort" in payload or "response_format" in payload):
                # Some models reject optional params; retry with a minimal payload.
                payload.pop("reasoning_effort", None)
                payload.pop("response_format", None)
                continue
            if r.status_code >= 400:
                raise LLMError(f"{p.label} HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            content = (data["choices"][0]["message"].get("content") or "").strip()
            u = data.get("usage") or {}
            pt, ct = int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
            pin, pout = PRICES.get(p.model, (0.0, 0.0))
            self.usage.calls += 1
            self.usage.prompt_tokens += pt
            self.usage.completion_tokens += ct
            self.usage.cost_usd += (pt * pin + ct * pout) / 1e6
            self.usage.log.append({"provider": p.label, "ms": round(ms), "prompt_tokens": pt, "completion_tokens": ct})
            if not content:
                raise LLMError(f"{p.label} returned an empty response")
            return content
        raise LLMError(f"{p.label}: rate-limited after retries")

    def chat(self, messages, json_mode=False, temperature=0.2, max_tokens=1800) -> str:
        errors = []
        for p in self.providers:  # automatic fallback across providers
            try:
                out = self._post(p, messages, json_mode, temperature, max_tokens)
                self.last_provider = p
                return out
            except (LLMError, requests.RequestException, KeyError, ValueError) as e:
                errors.append(str(e))
        raise LLMError("All LLM providers failed: " + " | ".join(errors) if errors else "No LLM provider configured")

    def structured(self, messages, schema: type[BaseModel], max_retries: int = 2, **kw) -> BaseModel:
        """JSON-mode call validated by Pydantic; on failure, feed the error back and retry."""
        msgs = list(messages)
        last_err = None
        for _ in range(max_retries + 1):
            raw = self.chat(msgs, json_mode=True, temperature=0.0, **kw)
            try:
                return schema.model_validate(_extract_json(raw))
            except (json.JSONDecodeError, ValidationError) as e:
                last_err = e
                msgs = msgs + [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": f"That output was invalid: {str(e)[:500]}. Return ONLY one valid JSON object matching the schema.",
                    },
                ]
        raise LLMError(f"Could not get valid JSON after retries: {last_err}")
