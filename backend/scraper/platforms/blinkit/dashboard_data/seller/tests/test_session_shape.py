"""The seller scrapes must read everything they need off the session — no browser.

WHY THIS EXISTS
---------------
The scorecard silently lost four weeks of data (2026-08-05 → 2026-09-04). Nothing it
called had been deleted: `auth_service.ensure()` returned a valid session, `auth probe`
passed, `expires_at` was days out, and every other Blinkit scrape was green. The one
thing that changed is that seller logins became browserless REST, so the session stopped
carrying the Firebase IndexedDB blob a browser needs to restore the SPA — and the
scorecard was the only consumer still opening a browser.

It then reported `session may be expired`, which was false, and cost weeks.

These tests pin the invariant that would have caught it on day one: **every seller scrape
derives its context from the session alone.** They are pure — a fixture session, no
browser, no network, no DB.

    python -m scraper.platforms.blinkit.dashboard_data.seller.tests.test_session_shape
"""
import json

from scraper.platforms.blinkit.dashboard_data.seller.scraper import (
    _entity_from_state, _headers_from_state, _scorecard_context_from_state)

# Shaped exactly like a live `blinkit_seller` session: an access_token cookie and a
# myEntity localStorage entry, and NO indexedDB key — because the REST login does not
# produce one. The two ids differ on purpose; see below.
ENTITY = {"id": 107951, "name": "Oxbow Brands Private Limited.", "type": "manufacturer",
          "external_id": 40246, "tenant": "BLINKIT", "disabled": False}

SESSION = {
    "cookies": [{"name": "access_token", "value": "t" * 40, "domain": ".partnersbiz.com"}],
    "origins": [{"origin": "https://partnersbiz.com", "localStorage": [
        {"name": "myEntity", "value": json.dumps(ENTITY)},
        {"name": "access_token_expiry", "value": "1790000000"},
    ]}],
}


def _without(key):
    """The session minus one piece, to check we degrade rather than guess."""
    s = json.loads(json.dumps(SESSION))
    if key == "cookie":
        s["cookies"] = []
    elif key == "entity":
        s["origins"][0]["localStorage"] = [
            i for i in s["origins"][0]["localStorage"] if i["name"] != "myEntity"]
    elif key == "external_id":
        e = dict(ENTITY)
        del e["external_id"]
        s["origins"][0]["localStorage"][0]["value"] = json.dumps(e)
    return s


# ── the invariant: no scrape needs a browser ─────────────────────────────────

def test_headers_come_from_the_session():
    """Sales / PO / SOH. There is no fallback behind this any more — the browser paths
    were deleted once it was clear they could never succeed — so returning None here
    means those three scrapes simply stop."""
    assert _headers_from_state(SESSION) is not None


def test_the_scorecard_context_comes_from_the_session():
    """The regression itself. The scorecard needs headers AND manufacturer_id; needing
    the second is the only reason it kept a browser and the only reason it broke."""
    ctx = _scorecard_context_from_state(SESSION)
    assert ctx is not None, "the scorecard has nothing to fall back to — it would raise"
    headers, manufacturer_id = ctx
    assert headers and manufacturer_id


# ── the id trap ──────────────────────────────────────────────────────────────

def test_manufacturer_id_is_external_id_not_id():
    """⚠️ `myEntity` carries BOTH, and they are different numbers for one account.
    `id` (107951) is the portal's entity id; `external_id` (40246) is what the scorecard
    APIs filter on and what every stored `blinkit_scorecard_*` row is keyed by. Using
    `id` does not error — it returns an EMPTY scorecard, which is far worse."""
    _, manufacturer_id = _scorecard_context_from_state(SESSION)
    assert manufacturer_id == "40246"
    assert manufacturer_id != "107951"


def test_manufacturer_id_is_a_string():
    """It is sent in a JSON filter and compared against stored values as text."""
    _, manufacturer_id = _scorecard_context_from_state(SESSION)
    assert isinstance(manufacturer_id, str)


# ── degrade honestly ─────────────────────────────────────────────────────────

def test_a_session_without_a_token_yields_nothing():
    assert _headers_from_state(_without("cookie")) is None
    assert _scorecard_context_from_state(_without("cookie")) is None


def test_a_session_without_myentity_yields_nothing():
    """The entity is not optional: /v1/* returns 403 ERROR_CODE:11 without the
    X-Entity-Id / X-Entity-Type headers derived from it."""
    assert _entity_from_state(_without("entity")) is None
    assert _headers_from_state(_without("entity")) is None
    assert _scorecard_context_from_state(_without("entity")) is None


def test_an_entity_without_external_id_does_not_fall_back_to_id():
    """Better to return None and report it than to scrape the wrong manufacturer."""
    assert _scorecard_context_from_state(_without("external_id")) is None


def test_malformed_myentity_does_not_raise():
    """A scrape loop must not die on a surprising session shape."""
    s = json.loads(json.dumps(SESSION))
    s["origins"][0]["localStorage"][0]["value"] = "{not json"
    assert _entity_from_state(s) is None
    assert _scorecard_context_from_state(s) is None


def test_an_empty_session_does_not_raise():
    for empty in ({}, {"cookies": [], "origins": []}):
        assert _headers_from_state(empty) is None
        assert _scorecard_context_from_state(empty) is None


# ── the shape of a real seller session ───────────────────────────────────────

def test_the_fixture_has_no_indexeddb_on_purpose():
    """Guards the assumption the whole fix rests on. A `blinkit_seller` session carries
    NO IndexedDB blob, so it can never restore the Firebase SPA into a browser — which
    is why every seller scrape must work from the session alone. If a future login does
    start emitting one, this test should be updated deliberately, not silently."""
    assert "indexedDB" not in SESSION


def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e or 'assertion failed'}")
    print(f"\n{len(tests) - failed}/{len(tests)} seller session-shape tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
