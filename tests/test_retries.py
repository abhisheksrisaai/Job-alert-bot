"""Retry/backoff tests. All HTTP is mocked; cwd is isolated to tmp so the
real SerpAPI quota counter is never touched.
"""
import pytest
import requests

import fetch_jobs
import rank_jobs
import notify


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.ok = 200 <= status < 300

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def fresh_usage():
    return {"month": "2026-09", "count": 0, "dork_index": 0}


# --- SerpAPI ---------------------------------------------------------------

def test_serpapi_retries_429_then_counts_once(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            return FakeResponse(429, {}, {"Retry-After": "1"})
        return FakeResponse(200, {"jobs_results": []})

    monkeypatch.setattr(requests, "get", fake_get)
    sleeps = []
    monkeypatch.setattr(fetch_jobs.time, "sleep", sleeps.append)

    usage = fresh_usage()
    data, usage = fetch_jobs._serpapi_search({"q": "x"}, usage)
    assert data == {"jobs_results": []}
    assert usage["count"] == 1  # retried call counts once, not twice
    assert len(calls) == 2
    assert sleeps == [1.0]  # Retry-After honored


def test_serpapi_retries_connection_error(monkeypatch):
    attempts = []

    def fake_get(url, params=None, timeout=None):
        attempts.append(1)
        if len(attempts) == 1:
            raise requests.ConnectionError("boom")
        return FakeResponse(200, {"organic_results": []})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(fetch_jobs.time, "sleep", lambda s: None)
    usage = fresh_usage()
    data, usage = fetch_jobs._serpapi_search({"q": "x"}, usage)
    assert data == {"organic_results": []}
    assert usage["count"] == 1


def test_serpapi_quota_error_does_not_retry_or_count(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(1)
        return FakeResponse(200, {"error": "This account has run out of searches."})

    monkeypatch.setattr(requests, "get", fake_get)
    usage = fresh_usage()
    data, usage = fetch_jobs._serpapi_search({"q": "x"}, usage)
    assert data is None
    assert usage["count"] == 0
    assert len(calls) == 1


def test_serpapi_500_gives_up_after_max_attempts(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(1)
        return FakeResponse(500, {})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(fetch_jobs.time, "sleep", lambda s: None)
    usage = fresh_usage()
    data, usage = fetch_jobs._serpapi_search({"q": "x"}, usage, max_attempts=3)
    assert data is None
    assert usage["count"] == 0
    assert len(calls) == 3


# --- Groq ------------------------------------------------------------------

class FakeGroqError(Exception):
    def __init__(self, msg, status_code):
        super().__init__(msg)
        self.status_code = status_code
        self.response = type("R", (), {"headers": {}})()


class FakeCompletions:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        action = self.script.pop(0)
        if isinstance(action, Exception):
            raise action
        content = action
        choice = type("C", (), {"message": type("M", (), {"content": content})()})()
        return type("R", (), {"choices": [choice]})()


class FakeClient:
    def __init__(self, script):
        self.chat = type("Chat", (), {"completions": FakeCompletions(script)})()


def test_groq_retries_rate_limit_then_parses(monkeypatch):
    monkeypatch.setattr(rank_jobs.time, "sleep", lambda s: None)
    client = FakeClient([
        FakeGroqError("rate limited", 429),
        '[{"index": 1, "relevant": true, "score": 9, "reason": "Bangalore intern fit"}]',
    ])
    out = rank_jobs._rank_batch(client, "m", [{"title": "T", "link": "L"}], "resume", {})
    assert out and out[0]["relevant"] is True
    assert client.chat.completions.calls == 2


def test_groq_auth_error_raises_immediately():
    client = FakeClient([FakeGroqError("bad key", 401)])
    with pytest.raises(FakeGroqError):
        rank_jobs._rank_batch(client, "m", [{"title": "T", "link": "L"}], "resume", {})
    assert client.chat.completions.calls == 1


# --- Telegram ---------------------------------------------------------------

def test_telegram_retries_connection_error(monkeypatch):
    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise requests.ConnectionError("boom")
        return FakeResponse(200, {"ok": True})

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    notify.send_telegram_digest([{"title": "T", "company": "C", "score": 9}])
    assert len(calls) == 2


def test_telegram_400_does_not_retry(monkeypatch):
    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append(1)
        return FakeResponse(400, {"ok": False})

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    notify.send_telegram_digest([{"title": "T", "company": "C", "score": 9}])
    assert len(calls) == 1
