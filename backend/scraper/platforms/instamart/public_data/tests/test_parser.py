"""Instamart public search — extraction and classification against real captures.

Fixtures are page-0 bodies captured live on 2026-09-17 at Bengaluru store
1388682: `sourdough` (32 items, 3 ads) and the brand query `brik oven` (4 items,
nextOffset null). Nothing here touches the network or the database.
"""
import json
from pathlib import Path

import pytest

from scraper.platforms.instamart.public_data import endpoints as ep
from scraper.platforms.instamart.public_data import parser
from scraper.platforms.instamart.public_data.scraper import (
    _extract_product, _next_offset, _result_count, _walk_items,
)

FIX = Path(__file__).parent / "fixtures"


def _data(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))["data"]


def _products(name: str) -> list[dict]:
    out = []
    for item in _walk_items(_data(name)):
        p = _extract_product(item, len(out) + 1)
        if p:
            out.append(p)
    return out


# ── shape ────────────────────────────────────────────────────────────────────

def test_walk_finds_every_grid_item_in_order():
    items = _walk_items(_data("sourdough_p0.json"))
    assert len(items) == 32
    assert items[0]["displayName"].startswith("Brik Oven Artisanal Sourdough")


def test_result_count_and_next_offset():
    d = _data("sourdough_p0.json")
    assert _result_count(d) == 145
    assert _next_offset(d) == 1
    b = _data("brik_oven_p0.json")
    assert _result_count(b) == 4
    assert _next_offset(b) is None          # the end signal: null, not "" / missing


# ── one product ──────────────────────────────────────────────────────────────

def test_first_item_fields():
    p = _products("sourdough_p0.json")[0]
    assert p["position"] == 1
    assert p["brand"] == "Brik Oven"
    assert p["product_id"] == "AEYU74I37R"
    assert p["group_id"] == "Z41HDW022T"
    assert p["variant_id"] == "XS4A5GV2ID"
    assert p["price"] == 104.0 and p["mrp"] == 110.0
    assert p["in_stock"] is True
    assert p["is_ad"] is False
    assert p["merchant_id"] == "1388682"            # podId, the store that served it
    assert p["merchant_type"] == "primary"
    assert p["unit"] == "400 g"
    assert p["rating"] == 4.4
    assert p["category"] == "Bread and Buns"
    assert p["ptype"] == "Gourmet Breads"
    assert p["extra"]["confidence"] == ep.CONFIDENCE_HIGH
    assert p["extra"]["bestseller"] is True
    assert p["extra"]["discount_label"] == "5% OFF"


def test_ads_are_flagged_and_carry_slot_and_campaign():
    ps = _products("sourdough_p0.json")
    ads = [p for p in ps if p["is_ad"]]
    assert len(ads) == 3
    assert ps[1]["is_ad"] and ps[1]["brand"] == "Brik Oven"
    assert ps[1]["ad_meta"]["im_adslot"] == "1"
    assert ps[1]["ad_meta"]["im_kw"] == "sourdough"
    assert ps[1]["ad_meta"]["im_cid"]
    assert ps[0]["ad_meta"] == {}                    # organic rows carry nothing


def test_inventory_depth_vs_per_order_cap():
    ps = _products("sourdough_p0.json")
    by_id = {p["product_id"]: p for p in ps}
    cap = by_id["AEYU74I37R"]        # "Only 6 unit(s) … per order" — a cap, not stock
    assert cap["max_allowed_qty"] == 6 and cap["inventory"] is None
    depth = by_id["LR4NPP5KR4"]      # "That's all we have in stock" — real depth
    assert depth["max_allowed_qty"] == 3 and depth["inventory"] == 3
    assert "stock" in depth["extra"]["cart_limit_msg"].lower()


def test_low_confidence_items_are_tagged_not_dropped():
    ps = _products("sourdough_p0.json")
    tiers = {p["extra"]["confidence"] for p in ps}
    assert tiers == {"HIGH_CONFIDENCE", "LOW_CONFIDENCE"}


# ── brand query ──────────────────────────────────────────────────────────────

def test_brand_query_is_all_own_brand():
    ps = _products("brik_oven_p0.json")
    assert len(ps) == 4
    assert {p["brand"] for p in ps} == {"Brik Oven"}
    assert all(p["in_stock"] for p in ps)
    assert sorted(p["price"] for p in ps) == [104.0, 104.0, 149.0, 180.0]


# ── classification through the shared parser ────────────────────────────────

def test_parse_classifies_own_brand_and_competitors():
    ps = _products("sourdough_p0.json")
    res = parser.parse({
        "platform": "instamart", "keyword": "sourdough", "brand_slug": "brik-oven",
        "city": "bengaluru", "zone": "Malleshwaram", "pincode": "560003",
        "lat": 12.99, "lon": 77.59, "aliases": ["brik oven"],
        # (slug, aliases) pairs — the shape orchestrator._competitor_list builds
        "competitors": [("the-bakers-dozen", ["the baker's dozen"]),
                        ("the-health-factory", []), ("bakers-loaf", ["baker's loaf"])],
        "merchant_id": "1388682", "total_results": 145, "products": ps,
    })
    assert res["provider"] == "instamart"
    assert res["brand_rank"] == 1
    assert res["brand_product_count"] >= 3        # organic #1 + two ad placements
    assert res["total_results"] == 145
    # Competitors are kept through their watchlist ALIAS ("the baker's dozen")
    # but stored under the marketplace name slugified — `the-baker-s-dozen`, the
    # same slug Zepto's 1,070 rows for this brand already carry. Same classifier,
    # same convention; a mismatch here would mean Instamart drifted from Zepto.
    names = {c["brand_slug"] for c in res["competitors"]}
    assert {"the-baker-s-dozen", "the-health-factory"} <= names
    own = [l for l in res["listings"] if l["is_brand"]]
    assert own and all(l["merchant_id"] == "1388682" for l in own)
    assert any(l["is_ad"] for l in own)


@pytest.mark.parametrize("name,expected", [
    ("sourdough_p0.json", 32),
    ("brik_oven_p0.json", 4),
])
def test_every_item_extracts(name, expected):
    assert len(_products(name)) == expected
