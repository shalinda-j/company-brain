"""Optional LLM summarization for /ingest.

OFF by default (BRAIN_SUMMARIZE=false) to preserve the local-only posture. When
enabled and an API key is configured, long conversation text is summarized
before being stored. Any failure falls back to returning the original text, so
ingest never breaks because of summarization.
"""

from __future__ import annotations

from .config import config


def maybe_summarize(text: str) -> str:
    if not config.summarize or not config.llm_api_key:
        return text
    if len(text) < 600:  # short enough to keep verbatim
        return text
    try:
        if config.llm_provider == "anthropic":
            return _anthropic_summary(text)
    except Exception:
        return text
    return text


def _anthropic_summary(text: str) -> str:
    import httpx

    prompt = (
        "Summarize the following into a concise, factual memory note (3-6 sentences). "
        "Keep concrete decisions, names, numbers, and action items. No preamble.\n\n"
        f"{text[:20000]}"
    )
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": config.llm_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": config.llm_model,
            "max_tokens": 600,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    out = "\n".join(p for p in parts if p).strip()
    return out or text
