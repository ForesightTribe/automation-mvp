"""Pure tests for the Zepto adapter's decision logic.

No Zepto, no DB, no browser — everything here is a function of its arguments. The
network-shaped parts (`list_campaigns`, `read_campaign`) are thin passthroughs and
are covered by the live gates instead.

    python -m campaign_manager.tests.test_zepto_adapter
"""
from campaign_manager.marketplaces.zepto import adapter, client as zc

_BRAND = "b9cea5fc-da5f-4045-9b67-c07831733746"


class _FakeClient:
    """Just the two attributes the adapter touches."""

    def __init__(self, brand_ids):
        self.brand_ids = brand_ids

    @property
    def brand_id(self):
        return self.brand_ids[0]


def test_status_maps_to_the_engine_vocabulary():
    assert adapter._canonical("ACTIVE") == "running"
    assert adapter._canonical("PAUSED") == "paused"
    # Zepto's ON_HOLD equivalent: live but out of budget. Stoppable, not startable,
    # and never ours to clear.
    assert adapter._canonical("DAILY_BUDGET_EXHAUSTED") == "held"


def test_status_is_case_and_whitespace_insensitive():
    assert adapter._canonical("  active ") == "running"


def test_unknown_status_passes_through_rather_than_being_coerced():
    """A status we have never seen must NOT become something writable.

    Returning it unchanged lets a guardrail refuse it by name. Mapping it to a
    default would let the engine act on a campaign whose real state it does not
    understand.
    """
    assert adapter._canonical("SOME_NEW_STATE") == "SOME_NEW_STATE"
    assert adapter._canonical(None) is None
    assert adapter._canonical("") is None


def test_set_advertiser_accepts_a_matching_account():
    adapter.set_advertiser(_FakeClient([_BRAND]), _BRAND)          # no raise


def test_set_advertiser_refuses_a_mismatched_account():
    """The B3 guardrail. On Blinkit a stale stored id silently writes real money to
    a dead account; here we can check the session instead of trusting a constant."""
    try:
        adapter.set_advertiser(_FakeClient([_BRAND]), "some-other-brand-uuid")
    except RuntimeError as e:
        assert "mismatch" in str(e).lower()
    else:
        raise AssertionError("a mismatched account_ref must refuse the write")


def test_set_advertiser_is_a_noop_when_nothing_is_stored():
    """Zepto derives its account from the session, so an unset account_ref is
    normal — not a reason to block."""
    for empty in (None, "", 0):
        adapter.set_advertiser(_FakeClient([_BRAND]), empty)


def test_bids_from_detail_keeps_one_entry_per_keyword_text():
    detail = {"keyword_config": [
        {"keyword": "pink toffee", "match_type": "EXACT", "bid_value": 10,
         "is_negative": False},
    ]}
    assert adapter.bids_from_detail(detail) == {"pink toffee": 10}


def test_campaign_row_unwraps_zeptos_value_label_pairs():
    """Zepto wraps some list metrics as {"value","label"} so its UI can annotate
    them. The label is advice for a human; only the value is data."""
    row = zc.campaign_row({
        "campaign_id": 2427461,
        "campaign_name": "Foresight | Tech Test",
        "status": "ACTIVE",
        "daily_budget": "500",
        "smart_cpc": {"value": "16.00", "label": ""},
        "ad_position": {"value": "16", "label": "Low ad rank — Act now"},
        "sov": {"value": "0.07", "label": ""},
    })
    assert row["cpc"] == "16.00"
    assert row["ad_position"] == "16"
    assert row["sov"] == "0.07"
    assert row["campaign_id"] == 2427461


def test_campaign_row_tolerates_plain_values():
    """Not every row wraps: a plain value must survive unchanged."""
    row = zc.campaign_row({"campaign_id": 1, "smart_cpc": "12.00"})
    assert row["cpc"] == "12.00"


def test_missing_brand_id_fails_loudly():
    """A session with no brandIds is live but useless — every ads call is scoped by
    it. Better to say so than to send `brand_id=None` and get a puzzling 400."""
    try:
        _FakeClient([]).brand_id
    except IndexError:
        pass    # the fake's own failure; the real client raises RuntimeError
    from campaign_manager.marketplaces.zepto.transport import ZeptoClient
    try:
        ZeptoClient("t", "jwt", "waf", []).brand_id
    except RuntimeError as e:
        assert "brandIds" in str(e)
    else:
        raise AssertionError("an empty brand_ids must refuse to produce a brand_id")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} zepto-adapter tests passed.")
