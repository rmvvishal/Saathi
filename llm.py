"""Tiny provider-agnostic LLM wrapper (plain HTTP, no SDKs).

Set ONE of these environment variables:
  ANTHROPIC_API_KEY  -> Claude   (model: LLM_MODEL, default claude-haiku-5-5)
  GEMINI_API_KEY     -> Gemini   (model: LLM_MODEL, default gemini-2.5-flash; has a free tier)

With no key, ReportSaathi runs fully offline: rule-based extraction and
template explanations. Verification works the same either way.
"""
from __future__ import annotations

import os
from typing import Callable

import requests


def get_llm() -> tuple[Callable[[str], str] | None, str]:
    model = os.getenv("LLM_MODEL")
    if os.getenv("ANTHROPIC_API_KEY"):
        m = model or "claude-haiku-5-5"
        return (lambda p: _anthropic(p, m)), f"Claude ({m})"
    if os.getenv("GEMINI_API_KEY"):
        m = model or "gemini-2.5-flash"
        return (lambda p: _gemini(p, m)), f"Gemini ({m})"
    return None, "offline (no API key)"


def _anthropic(prompt: str, model: str) -> str:
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": 2000, "temperature": 0,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=60)
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"])


def _gemini(prompt: str, model: str) -> str:
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": os.environ["GEMINI_API_KEY"]},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0}},
        timeout=60)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]
