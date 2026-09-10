"""Blinkit sponsored-slot detection, and the dedupe key that depends on it.

Every fixture below is shaped from the REAL capture in `public_data/api.txt`
(campaign 568836 on our own `Dobra Blueberry Goli Soda`, and the banner carousel
that carries the same key somewhere else entirely).

    python -m scraper.platforms.blinkit.public_data.tests.test_ads
"""
from scraper.platforms.blinkit.public_data import ads, scraper


# ── the marker ───────────────────────────────────────────────────────────────

def test_a_real_sponsored_slot_is_detected():
    """Straight from api.txt line 17246."""
    common = {"ads_campaign_id": 568836, "ads_type": "monet_product_listing",
              "badge": "AD", "product_position": "1"}
    assert ads.is_sponsored(common) is True
    assert ads.campaign_id(common) == "568836"


def test_placeholder_campaign_ids_are_organic():
    """Blinkit sends these on organic rows. Reading one as an ad would have the bid
    optimizer chase a position its ad never held — this is the same guard
    live_position has always applied, now shared."""
    for junk in (None, "", "0", "null", "None", 0):
        assert ads.is_sponsored({"ads_campaign_id": junk}) is False, junk
        assert ads.campaign_id({"ads_campaign_id": junk}) == ""


def test_a_missing_or_malformed_block_is_organic_not_an_error():
    """"We could not tell" must read as organic — under-counting ads rather than
    inventing them — and must never raise inside a scrape loop."""
    for bad in (None, {}, "not a dict", 42, []):
        assert ads.is_sponsored(bad) is False
        assert ads.campaign_id(bad) == ""
        assert ads.ad_meta(bad) == {}


def test_the_campaign_id_is_returned_as_a_string():
    """Blinkit sends it as an int; every consumer compares it to ids read from the
    ads dashboard, which are strings."""
    assert ads.campaign_id({"ads_campaign_id": 568836}) == "568836"


# ── the trap: the same key, in the wrong place ───────────────────────────────

def test_a_banner_is_not_a_sponsored_product():
    """api.txt carries `ads_campaign_id` 15 times: 9 on product cards and 6 inside a
    promotional BANNER's `widget_meta` / `entry_source_map`. A recursive search for
    the key — the obvious implementation — would flag the banner as a sponsored
    product. `is_sponsored` takes the common_attributes block precisely so it
    cannot see them."""
    banner_snippet = {
        "tracking": {
            "widget_meta": {"ads_campaign_id": 451556,
                            "ads_type": "monet_banner_listing"},
            "entry_source_map": {"ads_campaign_id": 451556},
            "common_attributes": {"widget_position": 2},   # no campaign id here
        }
    }
    common = banner_snippet["tracking"]["common_attributes"]
    assert ads.is_sponsored(common) is False


# ── the stored tracking ids ──────────────────────────────────────────────────

def test_ad_meta_carries_the_ids_on_a_sponsored_row():
    meta = ads.ad_meta({"ads_campaign_id": 568836, "ads_subcampaign_id": 32123778,
                        "ads_cost_id": 3609, "ads_type": "monet_product_listing"})
    assert meta == {"ads_campaign_id": "568836", "ads_subcampaign_id": "32123778",
                    "ads_cost_id": "3609", "ads_type": "monet_product_listing"}


def test_ad_meta_is_empty_on_an_organic_row():
    """`extra` is more than half the weight of a listing row on the largest table we
    write, and ~92% of rows are organic — so an organic row must add nothing."""
    assert ads.ad_meta({"product_position": "4", "brand": "Dobra"}) == {}


def test_ad_meta_omits_ids_the_response_did_not_carry():
    assert ads.ad_meta({"ads_campaign_id": 1, "ads_cost_id": ""}) == {"ads_campaign_id": "1"}


# ── extraction wires the marker into the product row ─────────────────────────

def _snippet(pid, name, position, ads_campaign_id=None):
    """A product snippet in the shape `_extract_product` reads."""
    common = {"product_position": str(position), "l0_category": "", "reason": ""}
    if ads_campaign_id is not None:
        common["ads_campaign_id"] = ads_campaign_id
        common["ads_type"] = "monet_product_listing"
    return {
        "data": {"atc_action": {"add_to_cart": {"cart_item": {
            "product_id": pid, "product_name": name, "brand": "Dobra",
            "price": 73, "mrp": 75, "unit": "250 ml", "inventory": 2,
            "merchant_id": "s1", "merchant_type": "express"}}}},
        "tracking": {"common_attributes": common},
    }


def test_extraction_flags_a_sponsored_product():
    p = scraper._extract_product(_snippet("620124", "Dobra Blueberry Goli Soda", 1, 568836))
    assert p["is_ad"] is True
    assert p["ad_meta"]["ads_campaign_id"] == "568836"


def test_extraction_leaves_an_organic_product_alone():
    p = scraper._extract_product(_snippet("620124", "Dobra Blueberry Goli Soda", 19))
    assert p["is_ad"] is False and p["ad_meta"] == {}


# ── the dedupe key ───────────────────────────────────────────────────────────

def _dedupe(rows, distinct_ad_slots=True):
    """The exact keying `search()` applies, isolated from the browser and paging."""
    out, seen = [], set()
    for p in rows:
        pid = p.get("product_id")
        if pid:
            key = (pid, bool(p.get("is_ad")) and distinct_ad_slots)
            if key in seen:
                continue
            seen.add(key)
        out.append(p)
    return out


def _row(pid, is_ad, position):
    return {"product_id": pid, "is_ad": is_ad, "position": position}


def test_a_repeated_product_is_still_collapsed():
    """The behaviour this dedupe existed for: the `similarity` tail re-lists items
    already returned as `basic`, which wrote a duplicate row per store."""
    kept = _dedupe([_row("1", False, 3), _row("1", False, 18)])
    assert len(kept) == 1 and kept[0]["position"] == 3, "first sighting carries the best rank"


def test_the_ad_and_the_organic_slot_both_survive_the_keyword_scrape():
    """The point of the widened key. A page measures PLACEMENTS, and a product
    holding both slots is two of them."""
    kept = _dedupe([_row("618158", True, 5), _row("618158", False, 19)])
    assert len(kept) == 2


def test_the_ad_row_does_not_evict_the_organic_one():
    """The asymmetry that made this worth changing. Ads outrank organics, so with a
    pid-only key the sponsored row arrives FIRST and wins — silently converting the
    product's stored placement from earned to bought. The reverse (dropping the ad)
    would at least have been the conservative error."""
    kept = _dedupe([_row("618158", True, 5), _row("618158", False, 19)])
    assert {r["is_ad"] for r in kept} == {True, False}


def test_the_targeted_scrape_collapses_them_to_one_row():
    """`sku_snapshots` is a product's state at a store, not a placement on a page.
    A brand-name query is exactly where a brand-defence ad appears, and a second row
    would double-count that store's inventory."""
    kept = _dedupe([_row("618158", True, 5), _row("618158", False, 19)],
                   distinct_ad_slots=False)
    assert len(kept) == 1


def test_a_product_with_no_id_is_never_deduped_away():
    """No id means no identity — dropping such rows would silently shrink the page
    and with it the SoV denominator."""
    kept = _dedupe([_row("", False, 1), _row("", False, 2), _row(None, False, 3)])
    assert len(kept) == 3


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e or 'assertion failed'}")
    print(f"\n{len(tests) - failed}/{len(tests)} Blinkit ad-marker tests passed.")
    raise SystemExit(1 if failed else 0)
