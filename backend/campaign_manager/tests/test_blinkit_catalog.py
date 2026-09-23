"""Blinkit brand catalogue → our products at a store, and whether the read saw them all — pure.

`complete` is what allows "not sold here" to exclude a store, so it must be conservative: a
capped read, or one a 429 cut short, only counts as complete once our brand's block has
visibly ended.

    python -m campaign_manager.tests.test_blinkit_catalog
"""
from campaign_manager.marketplaces.blinkit import catalog

OURS = catalog.own_names(["dobra"])


def _p(pid, brand="Dobra", in_stock=True, inventory=2):
    return {"product_id": pid, "brand": brand, "name": f"{brand} {pid}",
            "in_stock": in_stock, "inventory": inventory}


def _others(n, start=9000):
    return [_p(str(start + i), brand="Kinley") for i in range(n)]


def _res(products, ok=True, error="", merchant="29859"):
    return {"ok": ok, "error": error, "products": products, "merchant_id": merchant}


def test_a_failed_search_tells_us_nothing():
    assert catalog.summarise(_res([], ok=False, error="HTTP 403"), 48, OURS)["ok"] is False


def test_none_of_our_products_is_a_failed_read_not_a_store_that_sells_nothing():
    out = catalog.summarise(_res(_others(20)), 48, OURS)
    assert out["ok"] is False and "none of our products" in out["error"]


def test_only_our_products_are_kept():
    out = catalog.summarise(_res([_p("1"), _p("2", brand="Too Yumm")] + _others(12)), 48, OURS)
    assert [p["pid"] for p in out["products"]] == ["1"]


def test_sold_out_products_are_kept_and_flagged():
    out = catalog.summarise(_res([_p("1", in_stock=False, inventory=0)] + _others(12)), 48, OURS)
    assert out["products"][0]["in_stock"] is False and out["products"][0]["inventory"] == 0


def test_a_search_that_ran_out_cleanly_is_complete():
    out = catalog.summarise(_res([_p("1"), _p("2")]), 48, OURS)
    assert out["complete"] is True


def test_a_capped_read_is_complete_once_our_block_has_ended():
    out = catalog.summarise(_res([_p(str(i)) for i in range(30)] + _others(18)), 48, OURS)
    assert out["complete"] is True


def test_a_capped_read_still_inside_our_block_is_not_complete():
    products = [_p(str(i)) for i in range(40)] + _others(5) + [_p("41"), _p("42"), _p("43")]
    assert catalog.summarise(_res(products), 48, OURS)["complete"] is False


def test_one_foreign_product_mid_block_proves_nothing():
    # Recon: a competitor's tapioca chips sat between our own combos.
    products = [_p(str(i)) for i in range(20)] + _others(1) + [_p(str(i)) for i in range(20, 47)]
    assert catalog.summarise(_res(products), 48, OURS)["complete"] is False


def test_a_read_cut_short_by_429_is_not_complete_just_because_it_is_short():
    out = catalog.summarise(_res([_p("1"), _p("2")], error="HTTP 429"), 48, OURS)
    assert out["ok"] is True and out["complete"] is False


def test_a_truncated_read_that_already_left_our_block_is_complete():
    out = catalog.summarise(_res([_p("1")] + _others(12), error="HTTP 429"), 48, OURS)
    assert out["complete"] is True


def test_brand_matching_ignores_case_and_whitespace():
    assert catalog.own_names([" Dobra ", "", None]) == {"dobra"}
    out = catalog.summarise(_res([_p("1", brand="DOBRA")]), 48, OURS)
    assert out["ok"] is True and out["products"][0]["pid"] == "1"


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
    print(f"\n{len(tests) - failed}/{len(tests)} blinkit-catalog tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
