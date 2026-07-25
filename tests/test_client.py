"""Tests for the polite HTTP client.

The politeness guarantees are the terms on which this crawl is defensible, so
they are tested rather than assumed. No network is touched — httpx's
MockTransport stands in for the server.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from client import Fetched, PoliteClient, RateLimiter


def run(coro):
    return asyncio.run(coro)


def client_with(handler, **kwargs) -> PoliteClient:
    """A PoliteClient wired to a mock transport instead of the network."""
    kwargs.setdefault("backoff_scale", 0)
    return PoliteClient(transport=httpx.MockTransport(handler), **kwargs)


def test_successful_fetch_returns_raw_bytes():
    body = b'{"practice": "\xc2\xa3"}'

    def handler(request):
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    async def go():
        async with client_with(handler, rate_per_sec=0) as c:
            return await c.get("https://example.test/p/1")

    result = run(go())
    assert result.ok
    assert result.body == body
    assert result.content_type == "application/json"
    assert result.attempts == 1


def test_retries_transient_failure_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, content=b"ok")

    async def go():
        async with client_with(handler, rate_per_sec=0) as c:
            return await c.get("https://example.test/p/1")

    result = run(go())
    assert result.ok
    assert result.attempts == 3
    assert calls["n"] == 3


def test_gives_up_after_max_attempts():
    def handler(request):
        return httpx.Response(503)

    async def go():
        async with client_with(handler, rate_per_sec=0, max_attempts=2) as c:
            return await c.get("https://example.test/p/1")

    result = run(go())
    assert not result.ok
    assert result.status == 503
    assert result.error


def test_client_error_is_not_retried():
    """A 404 is a wrong request, not a bad moment — retrying is rude and useless."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404)

    async def go():
        async with client_with(handler, rate_per_sec=0) as c:
            return await c.get("https://example.test/gone")

    result = run(go())
    assert not result.ok
    assert result.status == 404
    assert calls["n"] == 1


def test_transport_error_is_captured_not_raised():
    def handler(request):
        raise httpx.ConnectError("boom")

    async def go():
        async with client_with(handler, rate_per_sec=0, max_attempts=2) as c:
            return await c.get("https://example.test/p/1")

    result = run(go())
    assert not result.ok
    assert "ConnectError" in result.error


def test_user_agent_identifies_the_project():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers.get("user-agent", "")
        return httpx.Response(200, content=b"ok")

    async def go():
        async with client_with(handler, rate_per_sec=0) as c:
            await c.get("https://example.test/p/1")

    run(go())
    assert "NHSDentistIntelligence" in seen["ua"]
    assert "http" in seen["ua"], "UA must carry a contact URL"


def test_rate_limiter_enforces_global_interval():
    """Concurrency must not raise the aggregate rate above the promise."""

    async def go():
        limiter = RateLimiter(rate_per_sec=20)  # 50ms apart
        start = time.monotonic()
        await asyncio.gather(*(limiter.acquire() for _ in range(5)))
        return time.monotonic() - start

    elapsed = run(go())
    # 5 acquisitions at 50ms spacing ⇒ the last waits ~200ms.
    assert elapsed >= 0.18, f"rate limit not enforced: {elapsed:.3f}s"


def test_rate_limiter_pause_delays_everyone():
    async def go():
        limiter = RateLimiter(rate_per_sec=1000)
        await limiter.pause(0.2)
        start = time.monotonic()
        await limiter.acquire()
        return time.monotonic() - start

    assert run(go()) >= 0.15


def test_unlimited_rate_is_opt_in_and_fast():
    async def go():
        limiter = RateLimiter(rate_per_sec=0)
        start = time.monotonic()
        for _ in range(50):
            await limiter.acquire()
        return time.monotonic() - start

    assert run(go()) < 0.1


def test_fetched_ok_semantics():
    now = "2026-07-25T03:00:00+00:00"
    assert Fetched("u", 200, b"x", "", now).ok
    assert not Fetched("u", 200, b"x", "", now, error="nope").ok
    assert not Fetched("u", 500, b"", "", now).ok


def test_client_rejects_use_outside_context_manager():
    c = PoliteClient()
    with pytest.raises(RuntimeError, match="async context manager"):
        run(c.get("https://example.test/"))
