"""Shared test setup: no test may pick up a real key or reach the network."""

import pytest

import classifier

SETTINGS = (
    "LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_RPM", "LLM_MAX_TOKENS", "LLM_TEMPERATURE",
    "GEMINI_API_KEY", "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch, tmp_path):
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(classifier, "ENV_FILE", tmp_path / "no-such.env")
    monkeypatch.setattr(classifier, "_sleep", lambda seconds: None)
    monkeypatch.setattr(classifier, "_next_start", 0.0)


@pytest.fixture
def gemini(monkeypatch):
    """Settings as a user of Gemini's free tier would have them, with a made-up key."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")


def answer(verdict="allow", rules=(), question=""):
    """What a well-behaved model replies."""
    import json

    text = json.dumps({"analysis": "checked", "verdict": verdict, "rules": list(rules), "question": question})
    return {"text": text, "input_tokens": 4000, "output_tokens": 50, "latency_ms": 800}
