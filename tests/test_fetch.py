"""Tests for full-estate capture (ledger 1.1)."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from client import PoliteClient
from fetch import Practice, _capture_one, capture, parse_sitemap
from snapshot import read_manifest, read_run

SITEMAP = b"""<?xml version="1.0" encoding="utf-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.nhs.uk/services/dentist/a-practice/V007878</loc><lastmod>2026-07-24</lastmod></url>
  <url><loc>https://www.nhs.uk/services/dentist/b-practice/V000464</loc><lastmod>2026-07-23</lastmod></url>
  <url><loc>https://www.nhs.uk/services/dentist/dup/V007878</loc><lastmod>2026-07-24</lastmod></url>
  <url><loc></loc></url>
</urlset>
"""


def test_parse_sitemap_extracts_ids_and_dedupes():
    practices = parse_sitemap(SITEMAP)
    assert [p.practice_id for p in practices] == ["V007878", "V000464"]
    assert practices[0].lastmod == "2026-07-24"
    assert practices[0].appointments_url.endswith("/V007878/appointments")


def test_parse_sitemap_ignores_slug():
    """The slug is cosmetic; only the trailing ODS id matters."""
    practices = parse_sitemap(SITEMAP)
    assert practices[0].profile_url.endswith("/a-practice/V007878")


def test_capture_one_falls_back_to_overview_on_404():
    """Referral-only specialists have no appointments page — they must not be
    silently dropped from the estate."""

    def handler(request):
        if request.url.path.endswith("/appointments"):
            return httpx.Response(404)
        return httpx.Response(200, content=b"<html>overview</html>")

    async def go():
        async with PoliteClient(
            rate_per_sec=0, backoff_scale=0, transport=httpx.MockTransport(handler)
        ) as c:
            return await _capture_one(c, Practice("V003750", "https://x.test/d/s/V003750"))

    record = asyncio.run(go())
    assert record.ok
    assert record.meta["page"] == "overview"
    assert record.body == b"<html>overview</html>"


def test_capture_one_prefers_appointments():
    def handler(request):
        return httpx.Response(200, content=b"<html>appointments</html>")

    async def go():
        async with PoliteClient(
            rate_per_sec=0, backoff_scale=0, transport=httpx.MockTransport(handler)
        ) as c:
            return await _capture_one(c, Practice("V1", "https://x.test/d/s/V1", lastmod="2026-07-24"))

    record = asyncio.run(go())
    assert record.meta["page"] == "appointments"
    assert record.meta["lastmod"] == "2026-07-24"


def big_sitemap(n: int) -> bytes:
    rows = "".join(
        f"<url><loc>https://x.test/services/dentist/p/V{i:06d}</loc>"
        f"<lastmod>2026-07-24</lastmod></url>"
        for i in range(n)
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{rows}</urlset>"
    ).encode()


def estate_handler(n: int, *, fail_ids: set[str] | None = None):
    fail_ids = fail_ids or set()

    def handler(request):
        url = str(request.url)
        if url.endswith(".xml"):
            return httpx.Response(200, content=big_sitemap(n), headers={"content-type": "text/xml"})
        practice_id = url.rstrip("/").replace("/appointments", "").rsplit("/", 1)[-1]
        if practice_id in fail_ids:
            return httpx.Response(500)
        return httpx.Response(
            200,
            content=f"<html>{practice_id} accepting</html>".encode(),
            headers={"content-type": "text/html"},
        )

    return handler


def run_capture(tmp_path, handler, **kwargs):
    async def go():
        # Patch the module-level client construction by passing a transport through.
        import fetch as fetch_mod

        original = fetch_mod.PoliteClient

        def factory(**kw):
            kw.setdefault("backoff_scale", 0)
            return original(transport=httpx.MockTransport(handler), **kw)

        fetch_mod.PoliteClient = factory
        try:
            kwargs.setdefault("min_expected", 5)
            return await capture(root=tmp_path, day="2026-07-25", rate=0, **kwargs)
        finally:
            fetch_mod.PoliteClient = original

    return asyncio.run(go())


def test_full_capture_writes_every_practice(tmp_path):
    assert run_capture(tmp_path, estate_handler(60)) == 0

    run = read_run(tmp_path, "2026-07-25")
    assert run["complete"] is True
    assert run["route"] == "nhsuk-html"
    # 60 practices + the sitemap record itself.
    assert run["records_ok"] == 61

    ids = {e["practice_id"] for e in read_manifest(tmp_path, "2026-07-25")}
    assert "_sitemap" in ids, "sitemap provenance not recorded"
    assert "V000000" in ids and "V000059" in ids


def test_capture_records_failures_without_aborting(tmp_path):
    assert run_capture(tmp_path, estate_handler(40, fail_ids={"V000005", "V000006"})) == 0
    run = read_run(tmp_path, "2026-07-25")
    assert run["records_failed"] == 2
    assert run["records_ok"] == 39  # 40 - 2 failed + 1 sitemap
    assert run["complete"] is True


def test_capture_refuses_implausibly_small_sitemap(tmp_path):
    """A sitemap that suddenly lists 2 practices means the source changed
    shape. Recording it would look like a genuine collapse later."""
    assert run_capture(tmp_path, estate_handler(2), min_expected=5) == 1
    assert not (tmp_path / "2026-07-25" / "run.json").exists()


def test_capture_fails_cleanly_when_sitemap_unavailable(tmp_path):
    def handler(request):
        return httpx.Response(503)

    assert run_capture(tmp_path, handler) == 1


def test_limit_is_honoured_for_smoke_tests(tmp_path):
    assert run_capture(tmp_path, estate_handler(60), limit=5) == 0
    assert read_run(tmp_path, "2026-07-25")["records_ok"] == 6  # 5 + sitemap


def test_resume_skips_already_captured(tmp_path):
    """A run that dies at practice N must not re-fetch the first N."""
    calls = {"n": 0}
    base = estate_handler(60)

    def counting(request):
        if not str(request.url).endswith(".xml"):
            calls["n"] += 1
        return base(request)

    run_capture(tmp_path, counting, limit=100)
    # Reopen the day as if the first run had been interrupted.
    import json

    run_path = tmp_path / "2026-07-25" / "run.json"
    meta = json.loads(run_path.read_text())
    meta["complete"] = False
    run_path.write_text(json.dumps(meta))

    first_pass = calls["n"]
    run_capture(tmp_path, counting, limit=100)
    assert calls["n"] == first_pass, "resume re-fetched practices it already had"


def test_completed_day_is_not_recaptured(tmp_path):
    run_capture(tmp_path, estate_handler(60), limit=5)
    with pytest.raises(FileExistsError):
        run_capture(tmp_path, estate_handler(60), limit=5)
