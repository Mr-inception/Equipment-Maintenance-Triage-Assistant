import logging

import httpx

from .config import settings

logger = logging.getLogger("triage.llm")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(Exception):
    def __init__(self, message: str, code: str = "llm_error"):
        super().__init__(message)
        self.code = code


def provider() -> str:
    return settings.llm_provider.strip().lower()


def model_name() -> str:
    return settings.gemini_model if provider() == "gemini" else settings.llm_model


def is_configured() -> bool:
    key = settings.gemini_api_key if provider() == "gemini" else settings.anthropic_api_key
    return bool(key)


def complete(system: str, user: str, max_tokens: int = 2500) -> str:
    p = provider()
    if p == "gemini":
        return _gemini(system, user, max_tokens)
    if p == "anthropic":
        return _anthropic(system, user, max_tokens)
    raise LLMError(f"Unknown LLM_PROVIDER '{p}'. Use 'gemini' or 'anthropic'.", "config")


def _error_message(resp) -> str:
    try:
        return str(resp.json().get("error", {}).get("message", ""))[:300]
    except Exception:
        return ""


def _gemini(system: str, user: str, max_tokens: int) -> str:
    key = settings.gemini_api_key
    if not key:
        raise LLMError(
            "No Gemini API key is configured. Set GEMINI_API_KEY in backend/.env and restart the server.",
            code="no_api_key",
        )
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "maxOutputTokens": max(max_tokens, 8192),  # thinking models spend part of this budget
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    url = GEMINI_URL.format(model=settings.gemini_model)
    try:
        resp = httpx.post(
            url, json=body, headers={"x-goog-api-key": key}, timeout=settings.llm_timeout_seconds
        )
    except httpx.TimeoutException as exc:
        logger.error("LLM timeout: %s", exc)
        raise LLMError(
            f"The AI service did not respond within {settings.llm_timeout_seconds} seconds.", "timeout"
        ) from exc
    except httpx.HTTPError as exc:
        logger.error("LLM connection error: %s", type(exc).__name__)
        raise LLMError("Could not reach the AI service. Check your internet connection.", "connection") from exc

    if resp.status_code != 200:
        detail = _error_message(resp)
        logger.error("LLM HTTP %s: %s", resp.status_code, detail)
        if resp.status_code in (401, 403) or (resp.status_code == 400 and "api key" in detail.lower()):
            raise LLMError("The AI service rejected the API key. Check GEMINI_API_KEY.", "auth")
        if resp.status_code == 404:
            raise LLMError(
                f"Model '{settings.gemini_model}' was not found. Set GEMINI_MODEL in backend/.env to a current model name.",
                "model_not_found",
            )
        if resp.status_code == 429:
            raise LLMError("The AI service is rate limiting requests. Try again shortly.", "rate_limit")
        raise LLMError(f"The AI service returned an error (HTTP {resp.status_code}). {detail}".strip(), "api_status")

    try:
        data = resp.json()
    except Exception as exc:
        raise LLMError("The AI service returned an unreadable reply.", "bad_reply") from exc

    block = (data.get("promptFeedback") or {}).get("blockReason")
    if block:
        raise LLMError(f"The AI service blocked the request ({block}).", "blocked")
    candidates = data.get("candidates") or []
    if not candidates:
        raise LLMError("The AI service returned an empty reply.", "empty")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        finish = candidates[0].get("finishReason", "unknown")
        raise LLMError(f"The AI service returned an empty reply (finish reason: {finish}).", "empty")
    return text


def _anthropic(system: str, user: str, max_tokens: int) -> str:
    import anthropic

    if not settings.anthropic_api_key:
        raise LLMError(
            "No Anthropic API key is configured. Set ANTHROPIC_API_KEY in backend/.env and restart the server.",
            code="no_api_key",
        )
    try:
        client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds, max_retries=1
        )
        resp = client.messages.create(
            model=settings.llm_model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APITimeoutError as exc:
        raise LLMError(f"The AI service did not respond within {settings.llm_timeout_seconds} seconds.", "timeout") from exc
    except anthropic.AuthenticationError as exc:
        raise LLMError("The AI service rejected the API key. Check ANTHROPIC_API_KEY.", "auth") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError("The AI service is rate limiting requests. Try again shortly.", "rate_limit") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError("Could not reach the AI service. Check your internet connection.", "connection") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"The AI service returned an error (HTTP {exc.status_code}).", "api_status") from exc
    except anthropic.AnthropicError as exc:
        raise LLMError("The AI service call failed.", "llm_error") from exc
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    if not text.strip():
        raise LLMError("The AI service returned an empty reply.", "empty")
    return text
