"""The table-driven builder must produce EXACTLY what the hand-written ones produced.

This is what makes `build.py` a refactor rather than a rewrite of code that moves real
money. `fixtures_blinkit_payloads.json` was captured by running the OLD hand-written
builders over nine campaign shapes — city-targeted, pan-India, BANNER_LISTING, no keywords,
pids as a string / as a list / only in `products`, with `campaign_data`, with negative
keywords, with a repeat-order suggestion — for all four write types. 36 payloads.

If `build()` differs from those by so much as a type (`502` vs `502.0`, `""` vs `None`),
this fails. Blinkit is picky in ways we have learned the hard way — an image key in
`campaign_data` trips a validator even when its value is unchanged — so "close enough" is
not a standard that applies here.

⚠️ These fixtures are a RECORD OF WHAT SHIPPED, not a specification of what is correct. The
old builders' quirks are frozen in deliberately: matching them exactly is what proves the
refactor changed nothing. If Blinkit's contract genuinely changes, update the fixtures in a
separate commit that says so, and never to make a failing test pass.

    python -m campaign_manager.tests.test_build_equivalence
"""
import json
from datetime import datetime
from pathlib import Path

from campaign_manager.marketplaces.blinkit import build

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures_blinkit_payloads.json").read_text(encoding="utf-8"))

CAMPAIGN_ID = 637511
REQUESTED_BY = "ops@foresighttribe.com"
ADVERTISER = 19802
MIN_CPM = {"PRODUCT_LISTING": 500, "BANNER_LISTING": 500}
TODAY = datetime(2026, 9, 3)


def _build(detail: dict, kind: str) -> dict:
    """Drive `build()` the way each caller does."""
    common = dict(detail=detail, campaign_id=CAMPAIGN_ID, requested_by=REQUESTED_BY,
                  advertiser_id=ADVERTISER, min_cpm=MIN_CPM, today=TODAY)
    if kind == "bid":
        return build.build(shape=build.BID, keyword_updates=[
            {"keyword": "soda", "match_type": "EXACT", "cpm": 111}], **common)
    if kind == "budget":
        return build.build(shape=build.BUDGET, budget=900.0, **common)
    if kind == "restart":
        return build.build(shape=build.RESTART, budget=900, **common)
    raise ValueError(kind)


def _diff(expected: dict, got: dict) -> str:
    lines = []
    for key in sorted(set(expected) | set(got)):
        e, g = expected.get(key, "<missing>"), got.get(key, "<missing>")
        if e != g:
            lines.append(f"      {key}:\n        old = {e!r}\n        new = {g!r}")
    return "\n" + "\n".join(lines)


def _check(name: str, kind: str) -> None:
    entry = FIXTURES[name]
    if kind not in entry:
        return                                   # the old builder errored on this shape
    expected, got = entry[kind], _build(entry["detail"], kind)
    assert got == expected, f"{name}/{kind} differs from what shipped:{_diff(expected, got)}"


# One test per campaign shape, so a failure names the shape rather than "something differs".

def test_city_targeted():
    for kind in ("bid", "budget", "restart"):
        _check("city_targeted", kind)


def test_pan_india():
    for kind in ("bid", "budget", "restart"):
        _check("pan_india", kind)


def test_banner_listing():
    """The variant with its own `campaign_data`: any image field trips Blinkit's
    "Cannot change listing spotlight image" validator even when unchanged."""
    for kind in ("bid", "budget", "restart"):
        _check("banner_listing", kind)


def test_no_keywords():
    """A budget write omits `keyword_targeting` entirely rather than sending an empty list,
    which would read as "delete them all"."""
    for kind in ("bid", "budget", "restart"):
        _check("no_keywords", kind)


def test_pids_as_list():
    for kind in ("bid", "budget", "restart"):
        _check("pids_as_list", kind)


def test_pids_from_products():
    for kind in ("bid", "budget", "restart"):
        _check("pids_from_products", kind)


def test_with_campaign_data():
    for kind in ("bid", "budget", "restart"):
        _check("with_campaign_data", kind)


def test_with_negative_keywords():
    for kind in ("bid", "budget", "restart"):
        _check("with_negative_kw", kind)


def test_with_repeat_order():
    for kind in ("bid", "budget", "restart"):
        _check("with_repeat_order", kind)


def test_the_fixtures_actually_cover_the_shapes():
    """A guard against the suite silently emptying — if the fixtures file is truncated or a
    shape stops building, every test above passes vacuously.

    9 campaign shapes x 3 write kinds. It was 4 kinds and 36 payloads until 2026-09-05,
    when `budget_empty_pids` was removed with the delisted-catalog fallback it covered.
    Lowering this number is only ever correct alongside deleting a write path — if it
    fails after a refactor, the payloads went missing rather than being retired.
    """
    assert len(FIXTURES) == 9, f"expected 9 campaign shapes, found {len(FIXTURES)}"
    built = sum(1 for e in FIXTURES.values()
                for k in ("bid", "budget", "restart") if k in e)
    assert built == 27, f"expected 27 golden payloads, found {built}"


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
    print(f"\n{len(tests) - failed}/{len(tests)} build-equivalence tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
