"""Unit tests for the live-position search — snippet parsing + paging. No browser, no
network: `search` is driven against a fake page whose `in_page_fetch` is stubbed.

Run standalone:  python -m campaign_manager.tests.test_live_position
"""
import asyncio

from campaign_manager.marketplaces.blinkit import live_position as lp


def _snippet(name, pid, ads_campaign_id=None):
    return {
        "data": {"name": {"text": name}, "identity": {"id": pid}},
        "tracking": {"common_attributes": {"ads_campaign_id": ads_campaign_id}},
    }


def _body(snippets, next_url=None):
    resp = {"snippets": snippets}
    if next_url:
        resp["pagination"] = {"next_url": next_url}
    return {"response": resp}


# ── snippet parsing ──────────────────────────────────────────────────────────

def test_positions_are_one_based_and_sequential():
    out = lp._parse_snippets([_snippet("Alpha", 1), _snippet("Bravo", 2)], start_rank=1)
    assert [p["position"] for p in out] == [1, 2]


def test_start_rank_continues_across_pages():
    out = lp._parse_snippets([_snippet("Charlie", 3)], start_rank=13)
    assert out[0]["position"] == 13


def test_sponsored_detected_from_ads_campaign_id():
    out = lp._parse_snippets([_snippet("Sponsored Cola", 1, "998877")], start_rank=1)
    assert out[0]["is_ad"] is True


def test_placeholder_campaign_ids_are_not_sponsored():
    """Blinkit sends these for organic rows; treating them as ads would have the optimizer
    chase a position its ad never held."""
    for junk in (None, "", "0", "null", "None"):
        out = lp._parse_snippets([_snippet("Organic", 1, junk)], start_rank=1)
        assert out[0]["is_ad"] is False, junk


def test_unnamed_and_stub_rows_are_dropped():
    out = lp._parse_snippets([_snippet("", 1), _snippet("ab", 2), _snippet("Real", 3)], start_rank=1)
    assert [p["name"] for p in out] == ["Real"]
    assert out[0]["position"] == 1          # numbering follows KEPT rows


def test_malformed_snippets_are_skipped_not_fatal():
    out = lp._parse_snippets(["nope", None, {}, {"data": "wrong"}, _snippet("Good", 9)], start_rank=1)
    assert len(out) == 1 and out[0]["name"] == "Good"


# ── paging ───────────────────────────────────────────────────────────────────

def test_next_page_reads_the_url_and_its_query_string():
    url = "https://blinkit.com/v1/layout/search?offset=12&search_method=basic"
    nxt, method = lp._next_page(_body([], next_url=url))
    assert nxt == url and method == "basic"


def test_no_pagination_means_no_next_page():
    assert lp._next_page(_body([])) == (None, None)


# ── search() against a stubbed transport ─────────────────────────────────────

def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _session(pages):
    """A session whose fetches return `pages` in order."""
    calls = []

    async def fake_fetch(page, url, headers, body):
        calls.append({"url": url, "headers": headers, "body": body})
        return pages[len(calls) - 1]

    lp.in_page_fetch = fake_fetch
    return {"page": object(), "headers": {"auth_key": "k", "lat": "0", "lon": "0"}}, calls


def test_search_returns_parsed_products():
    session, calls = _session([{"status": 200, "body": _body([_snippet("Alpha Cola", 1, "77")])}])
    out = _run(lp.search(session, "cola", 12.9, 77.5))
    assert len(out) == 1 and out[0]["is_ad"] is True
    assert len(calls) == 1


def test_search_sends_the_store_as_headers_not_navigation():
    """Changing store must cost nothing — it is a header swap, not a page load."""
    session, calls = _session([{"status": 200, "body": _body([_snippet("Alpha Cola", 1)])}])
    _run(lp.search(session, "cola", 19.07, 72.87))
    assert calls[0]["headers"]["lat"] == "19.07" and calls[0]["headers"]["lon"] == "72.87"


def test_search_follows_pages_and_continues_numbering():
    session, calls = _session([
        {"status": 200, "body": _body([_snippet(f"Prod {i}", i) for i in range(12)],
                                      next_url="https://b.com/x?search_method=basic")},
        {"status": 200, "body": _body([_snippet("Prod 12", 12)])},
    ])
    out = _run(lp.search(session, "cola"))
    assert [p["position"] for p in out][-1] == 13
    assert calls[1]["body"] is None          # only the offset-0 request carries a body


def test_search_stops_at_similarity_padding():
    """Our sponsored slot is never in the loosely-related tail, so paging into it would
    spend requests against the same rate limit for nothing."""
    session, calls = _session([
        {"status": 200, "body": _body([_snippet("Alpha Cola", 1)],
                                      next_url="https://b.com/x?search_method=similarity")},
        {"status": 200, "body": _body([_snippet("Padding item", 2)])},
    ])
    _run(lp.search(session, "cola"))
    assert len(calls) == 1


def test_search_raises_when_the_first_page_fails():
    """'We couldn't look' must be distinguishable from 'our ad wasn't there' — the bid
    loop turns the first into an error row and the second into a skip."""
    session, _ = _session([{"status": 403, "body": None, "error": "Cloudflare"}])
    try:
        _run(lp.search(session, "cola"))
    except RuntimeError as e:
        assert "403" in str(e) or "Cloudflare" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_search_keeps_page_one_when_a_later_page_fails():
    """A truncated list is still a usable answer — the ad we care about ranks near the top."""
    session, _ = _session([
        {"status": 200, "body": _body([_snippet("Alpha Cola", 1)],
                                      next_url="https://b.com/x?search_method=basic")},
        {"status": 500, "body": None},
    ])
    out = _run(lp.search(session, "cola"))
    assert len(out) == 1


def test_search_raises_without_captured_headers():
    """A failed warm-up must fail loudly per keyword, not silently return 'not found' —
    which the optimizer would read as 'our ad isn't ranking' and act on."""
    try:
        _run(lp.search({"page": object(), "headers": {}}, "cola"))
    except RuntimeError as e:
        assert "headers" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e or 'assertion failed'}")
    print(f"\n{len(tests) - failed}/{len(tests)} live-position tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run_all())
