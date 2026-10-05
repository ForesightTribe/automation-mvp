"""Where a Zepto search stops paging (2026-10-02) — public_data/scraper.search.

It stops at the Similar Products break, at the cap, or when Zepto says `hasReachedEnd`.
It does NOT stop because a page came back short: on 20 saved page-0 responses, `almonds`
returned 27 rows of 220 and `sourdough` 18 of 212, every one with more behind it. A
"short page = the end" rule (checklist Z3b as first written) would have dropped them.

No browser: `_fetch` is a script. Run:
    python -m scraper.platforms.zepto.public_data.tests.test_paging
"""
import asyncio

from scraper.platforms.zepto.public_data import endpoints as ep
from scraper.platforms.zepto.public_data import scraper as zs


def _item(pid: int) -> dict:
    return {"position": pid - 1, "productResponse": {
        "id": f"r{pid}", "storeId": "store-1",
        "product": {"id": f"p{pid}", "name": f"Brik Oven Bread {pid}", "brand": "Brik Oven"},
        "productVariant": {"id": f"v{pid}", "mrp": 10000, "packsize": 400,
                           "unitOfMeasure": "GRAM", "formattedPacksize": "400 g"},
        "discountedSellingPrice": 9000,
    }}


def _page(first: int, n: int, *, end: bool = False, brk: bool = False) -> dict:
    layout = [{"widgetId": ep.PRODUCT_GRID_WIDGET, "data": {"resolver": {"data": {
        "items": [_item(first + i) for i in range(n)]}}}}]
    if brk:
        layout.append({"widgetId": "HEADER_WIDGET"})
    return {"status": 200, "kind": "ok",
            "body": {"layout": layout, ep.REACHED_END_KEY: end,
                     ep.TOTAL_COUNT_KEY: 200}}


def _run(pages: list[dict], cap: int) -> tuple[dict, int]:
    calls = {"n": 0}
    orig_fetch, orig_pass = zs._fetch, zs._ensure_pass

    async def _fetch(session, url, headers, body):
        calls["n"] += 1
        return pages.pop(0) if pages else {"status": 200, "kind": "ok",
                                           "body": {"layout": None}}

    async def _no_pass(session):
        return None

    zs._fetch, zs._ensure_pass = _fetch, _no_pass
    try:
        session = {"headers": {}, "store_id": "store-1", "secondary_ids": (),
                   "body": dict(ep.SEARCH_BODY)}
        res = asyncio.run(zs.search(session, "bread", cap, merchant_id="store-1"))
    finally:
        zs._fetch, zs._ensure_pass = orig_fetch, orig_pass
    return res, calls["n"]


def test_zepto_saying_it_reached_the_end_stops_paging():
    res, n = _run([_page(1, 24, end=True)], cap=60)
    assert n == 1 and len(res["products"]) == 24 and res["ok"]


def test_a_short_page_is_not_the_end():
    res, n = _run([_page(1, 27), _page(28, 20, end=True)], cap=60)
    assert n == 2 and len(res["products"]) == 47


def test_the_similar_products_break_still_stops_it():
    res, n = _run([_page(1, 21, brk=True)], cap=60)
    assert n == 1 and len(res["products"]) == 21


def test_the_cap_still_stops_it():
    res, n = _run([_page(1, 30), _page(31, 30)], cap=30)
    assert n == 1 and len(res["products"]) == 30


def test_a_later_page_failing_is_flagged_cut_short():
    failed = {"status": 500, "kind": "http500", "error": "HTTP 500"}
    res, n = _run([_page(1, 30), failed], cap=60)
    assert res["ok"] and res["truncated"] and not res["blocked"] and n == 2


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} Zepto paging tests passed.")
