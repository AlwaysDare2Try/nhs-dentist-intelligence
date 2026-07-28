"""A deliberately polite HTTP client (supports ledger step 1.1).

We are an uninvited guest on public infrastructure paid for by the same taxpayers
this project is meant to serve. The rules that follow are not performance tuning
— they are the terms on which this crawl is defensible:

* One request per second globally, no matter how many workers are running.
* An honest User-Agent naming the project and how to contact us.
* ``Retry-After`` is obeyed exactly when the server sends it.
* Exponential backoff on transient failure; immediate surrender on 4xx.

The client is route-agnostic on purpose: it does not know or care whether it is
pulling JSON from the Service Search API or HTML from nhs.uk, so the route
decision (ledger 2.2 / ADR-002) can change without touching this file.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self

import httpx

# C6: daily cadence, ~1 req/sec. The source runs on a 90-day update mandate, so
# there is nothing to gain from going faster and a reputation to lose.
DEFAULT_RATE_PER_SEC = 1.0
DEFAULT_CONCURRENCY = 4
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_ATTEMPTS = 4

USER_AGENT = (
    "NHSDentistIntelligence/0.1 (open data research; England dental access; "
    "+https://github.com/AlwaysDare2Try/nhs-dentist-intelligence)"
)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


@dataclass(slots=True)
class Fetched:
    """The raw outcome of one request. Deliberately uninterpreted."""

    url: str
    status: int
    body: bytes
    content_type: str
    fetched_at: str
    attempts: int = 1
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error


class RateLimiter:
    """Global token bucket. Shared by every worker so concurrency never raises
    the aggregate rate above what we promised."""

    def __init__(self, rate_per_sec: float = DEFAULT_RATE_PER_SEC) -> None:
        self.interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def acquire(self) -> None:
        if not self.interval:
            return
        async with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + self.interval
        if wait:
            await asyncio.sleep(wait)

    async def pause(self, seconds: float) -> None:
        """Push the whole bucket back — used when a server says Retry-After.
        One worker being throttled means every worker should back off."""
        async with self._lock:
            self._next_at = max(self._next_at, time.monotonic() + seconds)


class PoliteClient:
    """Async HTTP client with a global rate limit and bounded retries."""

    def __init__(
        self,
        *,
        rate_per_sec: float = DEFAULT_RATE_PER_SEC,
        concurrency: int = DEFAULT_CONCURRENCY,
        timeout: float = DEFAULT_TIMEOUT,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        backoff_scale: float = 1.0,
    ) -> None:
        self.limiter = RateLimiter(rate_per_sec)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.max_attempts = max_attempts
        # Tests set this to 0 so retry logic can be verified without sleeping.
        self.backoff_scale = backoff_scale
        self._headers = {
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            **(headers or {}),
        }
        self._timeout = timeout
        # Injected in tests so the politeness guarantees can be verified without
        # touching the network.
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=self._timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=DEFAULT_CONCURRENCY * 2),
            transport=self._transport,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get(self, url: str, **kwargs) -> Fetched:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> Fetched:
        return await self.request("POST", url, **kwargs)

    async def request(self, method: str, url: str, **kwargs) -> Fetched:
        """Perform one request, retrying transient failures. Never raises for a
        bad response — a failure is data too, and the caller records it."""
        if self._client is None:
            raise RuntimeError("PoliteClient used outside its async context manager")

        last_error = ""
        status = 0
        async with self.semaphore:
            for attempt in range(1, self.max_attempts + 1):
                await self.limiter.acquire()
                try:
                    response = await self._client.request(method, url, **kwargs)
                    status = response.status_code

                    if status == 200:
                        return Fetched(
                            url=url,
                            status=status,
                            body=response.content,
                            content_type=response.headers.get("content-type", ""),
                            fetched_at=_now(),
                            attempts=attempt,
                        )

                    if status in RETRYABLE_STATUS:
                        last_error = f"HTTP {status}"
                        await self._backoff(response, attempt)
                        continue

                    # 4xx other than 429: the request is wrong, not the moment.
                    return Fetched(
                        url=url,
                        status=status,
                        body=b"",
                        content_type=response.headers.get("content-type", ""),
                        fetched_at=_now(),
                        attempts=attempt,
                        error=f"HTTP {status}",
                    )

                except (httpx.TransportError, httpx.HTTPError) as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    if attempt < self.max_attempts:
                        await self._backoff(None, attempt)

        return Fetched(
            url=url,
            status=status,
            body=b"",
            content_type="",
            fetched_at=_now(),
            attempts=self.max_attempts,
            error=last_error or "exhausted retries",
        )

    async def _backoff(self, response: httpx.Response | None, attempt: int) -> None:
        """Honour Retry-After if offered, otherwise exponential with jitter.
        Jitter matters: without it, a batch of workers that fail together retry
        together and hit the server as a thundering herd."""
        delay = 0.0
        if response is not None:
            header = response.headers.get("retry-after", "")
            if header.strip().isdigit():
                delay = float(header.strip())
        if not delay:
            delay = min(60.0, 2.0**attempt) * (0.5 + random.random())
        delay *= self.backoff_scale
        if not delay:
            return

        if response is not None and response.status_code == 429:
            # Being rate-limited is a message to the whole crawl, not one worker.
            await self.limiter.pause(delay)
        await asyncio.sleep(delay)


def _now() -> str:
    return datetime.now(UTC).isoformat()
