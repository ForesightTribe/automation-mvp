"""Per-marketplace scrape caps (2026-10-02).

A cap is a number of results and each marketplace pages differently (Blinkit 12, Zepto 30),
so caps are set per (brand, marketplace) on the workbook's `caps` sheet and read through
`scraper/public/caps.py`. These pin: the readers take the cap for THEIR marketplace, the
sheet is validated, and a cap that wastes a page is warned about. No DB.

    python -m scraper.public.tests.test_caps
"""
import asyncio
import uuid
from types import SimpleNamespace

import pytest

from cli.commands import sync
from scraper.public import caps, orchestrator, targeted
from scraper.public.providers import get_provider

TENANT = uuid.uuid4()
TENANTS = {"Dobra": TENANT}


# ── the pure rules ───────────────────────────────────────────────────────────

def test_the_keyword_scrape_takes_the_first_own_brand_that_sets_a_cap():
    got = {"a": caps.Caps(None, 60), "b": caps.Caps(30, None), "c": caps.Caps(60, 60)}
    assert caps.tenant_keyword_cap(got) == 30
    assert caps.tenant_keyword_cap({"a": caps.Caps(None, 60)}) is None
    assert caps.tenant_keyword_cap({}) is None


def test_a_cap_off_the_page_grid_is_flagged():
    assert caps.off_page(36, 30)          # Zepto: two pages, 24 rows thrown away
    assert not caps.off_page(60, 30)
    assert not caps.off_page(36, 12)      # Blinkit: three whole pages
    assert caps.off_page(30, 12)
    assert not caps.off_page(None, 30) and not caps.off_page(36, None)


def test_each_marketplace_knows_its_page():
    assert get_provider("blinkit").page_size == 12
    assert get_provider("zepto").page_size == 30


# ── the readers take THEIR marketplace's cap ─────────────────────────────────

class _DB:
    """Answers the one watchlist query the readers make."""

    def __init__(self, rows):
        self.rows = rows

    async def execute(self, *_):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.rows))


def _with_caps(by_mp):
    """Run with `caps.own_caps` answering per marketplace."""
    def wrap(fn):
        def run():
            saved = caps.own_caps

            async def _own(db, tid, mp):
                return by_mp.get(mp, {})
            caps.own_caps = _own
            try:
                fn()
            finally:
                caps.own_caps = saved
        run.__name__ = fn.__name__
        return run
    return wrap


ROWS = [SimpleNamespace(brand_slug="dobra", aliases=["dobra"]),
        SimpleNamespace(brand_slug="dobra-lite", aliases=[])]


@_with_caps({"blinkit": {"dobra": caps.Caps(36, 48)}, "zepto": {"dobra": caps.Caps(30, 60)}})
def test_the_own_sku_scrape_takes_the_brands_cap_for_its_marketplace():
    on_zepto = asyncio.run(targeted._own_brands(_DB(ROWS), TENANT, 99, "zepto"))
    on_blinkit = asyncio.run(targeted._own_brands(_DB(ROWS), TENANT, 99, "blinkit"))
    assert on_zepto == [("dobra", ["dobra"], 60), ("dobra-lite", [], 99)]
    assert on_blinkit == [("dobra", ["dobra"], 48), ("dobra-lite", [], 99)]


@_with_caps({"zepto": {"dobra": caps.Caps(30, 60)}})
def test_no_cap_on_a_marketplace_means_its_default():
    got = asyncio.run(targeted._own_brands(_DB(ROWS), TENANT, 99, "blinkit"))
    assert [c for _, _, c in got] == [99, 99]
    assert asyncio.run(orchestrator._keyword_cap(None, TENANT, "blinkit")) is None
    assert asyncio.run(orchestrator._keyword_cap(None, TENANT, "zepto")) == 30


# ── the workbook's caps sheet ────────────────────────────────────────────────

def _row(**kw):
    base = {"tenant": "Dobra", "brand": "dobra", "mp": "zepto", "keyword_cap": 30,
            "brand_cap": 60}
    return {**base, **kw}


def test_the_sheet_reads_one_cap_pair_per_brand_and_marketplace():
    desired, warnings = sync._desired_caps(
        [_row(), _row(mp="Blinkit", keyword_cap=36, brand_cap=48)], TENANTS)
    assert desired == {(TENANT, "dobra", "zepto"): (30, 60),
                       (TENANT, "dobra", "blinkit"): (36, 48)}
    assert warnings == []


def test_a_row_with_both_caps_blank_is_no_row():
    desired, _ = sync._desired_caps([_row(keyword_cap="", brand_cap=None)], TENANTS)
    assert desired == {}


def test_one_blank_cap_keeps_the_other():
    desired, _ = sync._desired_caps([_row(keyword_cap="", brand_cap=60)], TENANTS)
    assert desired == {(TENANT, "dobra", "zepto"): (None, 60)}


def test_a_blinkit_shaped_cap_on_zepto_is_warned_about_not_refused():
    desired, warnings = sync._desired_caps([_row(keyword_cap=36, brand_cap=48)], TENANTS)
    assert desired == {(TENANT, "dobra", "zepto"): (36, 48)}
    assert len(warnings) == 2 and all("page size (30)" in w for w in warnings)


@pytest.mark.parametrize("bad, said", [
    (_row(mp=""), "has no `mp`"),
    (_row(keyword_cap=0), "positive"),
    (_row(brand_cap=-5), "positive"),
])
def test_the_sheet_refuses_what_cannot_be_right(bad, said):
    with pytest.raises(ValueError, match=said.replace("`", ".")):
        sync._desired_caps([bad], TENANTS)


def test_the_same_brand_and_marketplace_twice_is_refused():
    with pytest.raises(ValueError, match="appears twice"):
        sync._desired_caps([_row(), _row(mp="ZEPTO")], TENANTS)


def test_the_template_carries_a_caps_sheet_and_brands_without_caps(tmp_path):
    from openpyxl import load_workbook

    path = tmp_path / "t.xlsx"
    sync._write_template(str(path))
    wb = load_workbook(path)
    assert [c.value for c in wb["caps"][1]] == ["tenant", "brand", "mp", "keyword_cap",
                                                "brand_cap"]
    assert "keyword_cap" not in [c.value for c in wb["brands"][1]]
    data = sync._read_config(str(path))
    desired, warnings = sync._desired_caps(data["caps"], TENANTS)
    assert len(desired) == 2 and warnings == []


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
