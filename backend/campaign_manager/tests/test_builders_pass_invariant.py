"""The real builders must satisfy the invariant they now enforce.

`test_payload_invariant.py` proves the checker rejects a bad payload. This proves the
opposite and equally important half: that the payloads our **actual** builders produce for
realistic campaigns are accepted. A checker that is too strict does not fail loudly in a
unit test — it fails in production by refusing every write, which looks exactly like the
marketplace being down.

Exercises the whole chain — `update_keyword_bids`, `update_campaign` and `restart.build` —
with the network replaced by a capture. No Blinkit, no browser, no DB.

    python -m campaign_manager.tests.test_builders_pass_invariant
"""
import asyncio

from campaign_manager.marketplaces.blinkit import payload, restart
from campaign_manager.marketplaces.blinkit.client import BlinkitClient

CITY_DETAIL = {
    "name": "Foresight | Sprite [Delhi NCR]",
    "campaign_type": "PRODUCT_LISTING",
    "objective_type": "PERFORMANCE",
    "campaign_budget": 500,
    "pacing_type": "DAILY",
    "cpm": 0,
    "creative_type": "",
    "collection_id": "",
    "header_title": "",
    "store_name": "",
    "brand_ids": "",
    "brand_name": "Dobra",
    "pids": "554767,554768",
    "start_ts": "2026-07-08T18:30:00",
    "end_ts": "2027-03-31T00:00:00",
    "infinite_campaign": False,
    "region_type": "CITY",
    "region_ids": [2010, 2011, 2013],
    "campaign_targeting": {
        "keyword_targeting": {
            "keywords": [
                {"keyword": "sprite", "bids": [{"match_type": "EXACT", "cpm": 201,
                                                "max_boost": None}]},
                {"keyword": "soda", "bids": [{"match_type": "EXACT", "cpm": 150,
                                              "max_boost": None}]},
            ],
        },
    },
}

PAN_INDIA_DETAIL = {**CITY_DETAIL, "region_type": "PAN_INDIA", "region_ids": None,
                    "name": "Foresight | Tech Test"}

# A campaign with no keyword targeting at all — the shape that makes `keyword_targeting`
# absent from the budget payload.
NO_KEYWORDS = {k: v for k, v in CITY_DETAIL.items() if k != "campaign_targeting"}


class _CapturingClient(BlinkitClient):
    """A real BlinkitClient with the transport and the detail read swapped out.

    Subclassed rather than mocked so the builders under test are the genuine ones — the
    point is to exercise the actual payload construction, not a reimplementation of it.
    """

    def __init__(self, detail: dict):
        self._page = None
        self._token = ""
        self._email = "ops@foresighttribe.com"
        self._detail = detail
        self.sent = None

    async def get_campaign_detail(self, campaign_id: int):
        return self._detail, {"PRODUCT_LISTING": 500}

    async def get_advertiser_id(self) -> int:
        return 19802

    async def _fetch(self, method, path, body=None):
        self.sent = body
        return {"status": True}


def _run_async(coro):
    return asyncio.run(coro)


# ── The bid builder ─────────────────────────────────────────────────────────

def test_bid_write_on_a_city_targeted_campaign_is_accepted():
    c = _CapturingClient(CITY_DETAIL)
    _run_async(c.update_keyword_bids(
        568944, [{"keyword": "sprite", "match_type": "EXACT", "cpm": 250}],
        advertiser_id=19802))
    assert c.sent is not None, "the write was refused — the invariant is too strict"
    assert c.sent["campaign_targeting"]["city_ids"] == "2010,2011,2013"


def test_bid_write_preserves_the_other_keyword():
    c = _CapturingClient(CITY_DETAIL)
    _run_async(c.update_keyword_bids(
        568944, [{"keyword": "sprite", "match_type": "EXACT", "cpm": 250}],
        advertiser_id=19802))
    sent = {k["keyword"]: k["bids"][0]["cpm"]
            for k in c.sent["campaign_targeting"]["keyword_targeting"]["keywords"]}
    assert sent == {"sprite": 250, "soda": 150}, sent


def test_bid_write_on_a_pan_india_campaign_is_accepted():
    c = _CapturingClient(PAN_INDIA_DETAIL)
    _run_async(c.update_keyword_bids(
        574687, [{"keyword": "sprite", "match_type": "EXACT", "cpm": 250}],
        advertiser_id=19802))
    assert c.sent["campaign_targeting"]["city_ids"] == "-1"


# ── The budget builder ──────────────────────────────────────────────────────

def test_budget_write_on_a_city_targeted_campaign_is_accepted():
    c = _CapturingClient(CITY_DETAIL)
    _run_async(c.update_campaign(
        568944, {"bidding_strategy": {"total_budget": 900.0, "pacing_type": "DAILY"}},
        advertiser_id=19802))
    assert c.sent is not None, "the write was refused — the invariant is too strict"
    assert c.sent["campaign_targeting"]["city_ids"] == "2010,2011,2013"
    assert c.sent["bidding_strategy"]["total_budget"] == 900.0


def test_budget_write_on_a_campaign_with_no_keywords_is_accepted():
    c = _CapturingClient(NO_KEYWORDS)
    _run_async(c.update_campaign(
        568944, {"bidding_strategy": {"total_budget": 900.0, "pacing_type": "DAILY"}},
        advertiser_id=19802))
    assert c.sent is not None


def test_budget_write_with_empty_pids_is_accepted():
    """`empty_pids=True` is the delisted-catalog fallback: it deliberately sends no pids.
    The checker must not read a deliberately-emptied field as corruption — it only checks
    what is sent, and this sends `""`.

    ⚠️ If this ever starts failing, do NOT relax the pids rule: that fallback is a real
    write path and the right fix is to declare it as an intended change for its own shape.
    """
    c = _CapturingClient(CITY_DETAIL)
    _run_async(c.update_campaign(
        568944, {"bidding_strategy": {"total_budget": 900.0, "pacing_type": "DAILY"}},
        empty_pids=True, advertiser_id=19802))
    assert c.sent is not None, (
        "empty_pids was refused — see the docstring before touching the pids rule")


# ── The restart builder ─────────────────────────────────────────────────────

def test_restart_payload_passes_its_own_invariant():
    built = restart.build(CITY_DETAIL, campaign_id=568944, budget=200,
                          requested_by="ops@foresighttribe.com")
    assert payload.check(CITY_DETAIL, built, shape=payload.RESTART) == []
    assert built["campaign_targeting"]["city_ids"] == "2010,2011,2013"


def test_restart_of_a_pan_india_campaign_passes():
    built = restart.build(PAN_INDIA_DETAIL, campaign_id=574687, budget=200,
                          requested_by="ops@foresighttribe.com")
    assert payload.check(PAN_INDIA_DETAIL, built, shape=payload.RESTART) == []


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
        except Exception as e:                       # a refusal surfaces as WriteRefused
            failed += 1
            print(f"  FAIL  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} builder-invariant tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
