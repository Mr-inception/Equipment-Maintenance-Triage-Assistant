import httpx
import pytest

from app import llm
from app.config import settings


class FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._p = payload if payload is not None else {}

    def json(self):
        return self._p


@pytest.fixture(autouse=True)
def gemini(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")


def ok_payload(text="{}"):
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}


def test_missing_key_message(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    with pytest.raises(llm.LLMError) as exc:
        llm.complete("s", "u")
    assert exc.value.code == "no_api_key" and "GEMINI_API_KEY" in str(exc.value)


def test_success_returns_text(monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: FakeResp(200, ok_payload('{"a": 1}')))
    assert llm.complete("s", "u") == '{"a": 1}'


def test_thought_parts_are_ignored(monkeypatch):
    payload = {"candidates": [{"content": {"parts": [
        {"text": "thinking...", "thought": True}, {"text": "answer"}]}}]}
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: FakeResp(200, payload))
    assert llm.complete("s", "u") == "answer"


def test_key_is_sent_in_header_not_url(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"], seen["headers"] = url, kwargs.get("headers", {})
        return FakeResp(200, ok_payload())

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    llm.complete("s", "u")
    assert "test-key" not in seen["url"] and seen["headers"]["x-goog-api-key"] == "test-key"


def test_rate_limit(monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: FakeResp(429, {"error": {"message": "quota"}}))
    with pytest.raises(llm.LLMError) as exc:
        llm.complete("s", "u")
    assert exc.value.code == "rate_limit"


def test_invalid_key_is_auth_error(monkeypatch):
    payload = {"error": {"message": "API key not valid. Please pass a valid API key."}}
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: FakeResp(400, payload))
    with pytest.raises(llm.LLMError) as exc:
        llm.complete("s", "u")
    assert exc.value.code == "auth"


def test_model_not_found(monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: FakeResp(404, {"error": {"message": "not found"}}))
    with pytest.raises(llm.LLMError) as exc:
        llm.complete("s", "u")
    assert exc.value.code == "model_not_found" and "GEMINI_MODEL" in str(exc.value)


def test_timeout(monkeypatch):
    def boom(*a, **k):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(llm.httpx, "post", boom)
    with pytest.raises(llm.LLMError) as exc:
        llm.complete("s", "u")
    assert exc.value.code == "timeout"


def test_blocked_prompt(monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: FakeResp(200, {"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(llm.LLMError) as exc:
        llm.complete("s", "u")
    assert exc.value.code == "blocked"


def test_empty_candidates(monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: FakeResp(200, {"candidates": []}))
    with pytest.raises(llm.LLMError) as exc:
        llm.complete("s", "u")
    assert exc.value.code == "empty"


def test_unknown_provider(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "other")
    with pytest.raises(llm.LLMError) as exc:
        llm.complete("s", "u")
    assert exc.value.code == "config"
