"""Golden-payload test for the Blinkit RESTART body (docs/campaign-manager.md §8.4).

**The most important test in the activation feature.** Resuming a campaign re-submits it
whole — budget, keywords, bids, pids, dates — so a drift in the builder does not fail
loudly, it silently rewrites a live campaign. `CAPTURED` below is a byte-for-byte
transcription of a real restart of campaign 574687 performed from Blinkit's own dashboard
on 2026-08-06. If `build()` ever stops reproducing it, that is a bug in us, not the test.

Pure — no Blinkit, no DB, no browser. Run with:

    python -m campaign_manager.tests.test_restart_payload
"""
from datetime import datetime

from campaign_manager.marketplaces.blinkit import restart

# ── The real thing, captured from the dashboard's own network request ───────
CAPTURED = {
    "source_platform": "diy_dashboard_web",
    "requested_by": "bhanu.nangru@foresighttribe.com",
    "advertiser_id": 0,
    "brand_name": "",
    "campaign_id": 574687,
    "objective_type": "PERFORMANCE",
    "asset_type": "PRODUCT_LISTING",
    "image_url": "",
    "header_title": "",
    "creative_type": "",
    "highlighted_pids": "554767",
    "collection_id": "",
    "store_name": "",
    "name": "Foresight | Tech Test",
    "campaign_start": "8/6/2026",
    "campaign_end": "12/31/9999",
    "cpm": 0,
    "campaign_data": {
        "brand_ids": "",
        "category_ids": "",
        "pids": "554767",
        "products": [],
        "ro_details": {
            "ro_number": None, "ro_amount": None, "ro_issue_date": None, "proof_url": None,
        },
    },
    "bidding_strategy": {"total_budget": 200, "pacing_type": "DAILY"},
    "campaign_targeting": {
        "city_ids": "-1",
        "is_extendable": False,
        "keyword_targeting": {
            "keywords": [
                {"keyword": "pink toffee",
                 "bids": [{"match_type": "EXACT", "cpm": 201, "max_boost": None}]},
            ],
        },
    },
    "campaign_request_type": "RESTART",
    "preview_image_url": "",
}

# A `get_campaign_detail` response consistent with the campaign that produced CAPTURED.
DETAIL = {
    "name": "Foresight | Tech Test",
    "campaign_type": "PRODUCT_LISTING",
    "objective_type": "PERFORMANCE",
    "campaign_budget": 201,
    "pacing_type": "DAILY",
    "cpm": 0,
    "header_title": "",
    "creative_type": "",
    "collection_id": "",
    "store_name": "",
    "brand_name": "Dobra",              # present in detail, deliberately NOT sent (AD4)
    "pids": "554767",
    "start_ts": "2026-07-08T18:30:00",  # replaced by today (AD4)
    "end_ts": "2027-03-31T00:00:00",    # replaced by the sentinel (AD5)
    "infinite_campaign": False,
    "campaign_targeting": {
        "keyword_targeting": {
            "keywords": [
                {"keyword": "pink toffee",
                 "bids": [{"match_type": "EXACT", "cpm": 201, "max_boost": None}]},
            ],
        },
    },
}

ARGS = dict(campaign_id=574687, budget=200,
            requested_by="bhanu.nangru@foresighttribe.com",
            today=datetime(2026, 8, 6))


def test_golden_payload_matches_the_capture():
    built = restart.build(DETAIL, **ARGS)
    assert built == CAPTURED, _diff(CAPTURED, built)


def test_end_date_is_always_the_infinite_sentinel():
    """AD5 — a restarted campaign must never come back carrying an expiry, whatever
    end date it had before. A finite one is a time bomb under a nightly automation."""
    built = restart.build({**DETAIL, "end_ts": "2026-08-09T00:00:00"}, **ARGS)
    assert built["campaign_end"] == "12/31/9999"


def test_advertiser_is_zero_not_the_stored_account():
    """AD4 — the dashboard sends 0 for RESTART (and the real id for a budget UPDATE)."""
    assert restart.build(DETAIL, **ARGS)["advertiser_id"] == 0


def test_start_date_is_today_not_the_campaigns_own():
    built = restart.build(DETAIL, **{**ARGS, "today": datetime(2026, 12, 25)})
    assert built["campaign_start"] == "12/25/2026"


def test_city_targeting_is_preserved_not_broadened():
    """Sending -1 for a city-targeted campaign would silently broaden its reach."""
    built = restart.build({**DETAIL, "region_ids": [12, 34]}, **ARGS)
    assert built["campaign_targeting"]["city_ids"] == "12,34"
    assert restart.build(DETAIL, **ARGS)["campaign_targeting"]["city_ids"] == "-1"


def test_pids_from_list_and_from_products_fallback():
    from_list = restart.build({**DETAIL, "pids": [554767, 998]}, **ARGS)
    assert from_list["highlighted_pids"] == "554767,998"
    assert from_list["campaign_data"]["pids"] == "554767,998"

    no_pids = {k: v for k, v in DETAIL.items() if k != "pids"}
    fallback = restart.build({**no_pids, "products": [{"pid": 554767}]}, **ARGS)
    assert fallback["highlighted_pids"] == "554767"


def test_keywords_read_from_the_top_level_fallback():
    """Blinkit returns keywords nested on some campaigns and top-level on others."""
    top_level = {k: v for k, v in DETAIL.items() if k != "campaign_targeting"}
    top_level["keywords"] = [
        {"keyword": "toffee", "bids": [{"match_type": "EXACT_MATCH", "cpm": 300}]},
    ]
    built = restart.build(top_level, **ARGS)
    assert built["campaign_targeting"]["keyword_targeting"]["keywords"] == [
        {"keyword": "toffee", "bids": [{"match_type": "EXACT", "cpm": 300, "max_boost": None}]},
    ]


def test_budget_is_whole_when_whole():
    """The capture sends 200, not 200.0 — stay faithful to it."""
    assert restart.build(DETAIL, **{**ARGS, "budget": 200.0})["bidding_strategy"]["total_budget"] == 200
    assert isinstance(
        restart.build(DETAIL, **{**ARGS, "budget": 200.0})["bidding_strategy"]["total_budget"], int)
    assert restart.build(DETAIL, **{**ARGS, "budget": 200.5})["bidding_strategy"]["total_budget"] == 200.5


def test_overwrites_summary_names_what_gets_rewritten():
    """AD9 — the audit line that makes a silently-reverted bid visible."""
    ow = restart.overwrites(DETAIL, budget=200)
    assert ow["budget"] == "201→200"
    assert ow["keywords"] == 1
    assert ow["bids"] == "pink toffee:201"
    assert ow["pids"] == "554767"


def _diff(expected: dict, got: dict) -> str:
    lines = []
    for key in sorted(set(expected) | set(got)):
        e, g = expected.get(key, "<missing>"), got.get(key, "<missing>")
        if e != g:
            lines.append(f"    {key}: expected {e!r}, got {g!r}")
    return "payload differs from the capture:\n" + "\n".join(lines)


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
    print(f"\n{len(tests) - failed}/{len(tests)} restart-payload tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
