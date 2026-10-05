"""Zepto's write invariant — a PUT may change only what it was asked to.

Mirrors `test_payload_invariant.py` (Blinkit). The point of `zepto/payload.py` is to catch
a TRANSLATOR bug, which the one-field diff guard structurally cannot: it compares our
translation with itself. On 2026-09-21 three such bugs were live at once (ZC-A12..A14) and
the diff guard passed all three. Each is re-created below and must be caught.

Fixtures are the two real dashboard captures of Tech Test 2427461:
  * `test_zepto_translate`        — ALL cities, one keyword (2026-08-21)
  * `test_zepto_translate_manual` — 2 chosen cities, 3 match types, a negative (2026-09-21)

    python -m campaign_manager.tests.test_zepto_payload_invariant
"""
import asyncio
import copy

from campaign_manager import writes
from campaign_manager.marketplaces.zepto import adapter as zad
from campaign_manager.marketplaces.zepto import client as zc
from campaign_manager.marketplaces.zepto import payload as P
from campaign_manager.marketplaces.zepto import translate
from campaign_manager.tests import test_zepto_translate as ALL_CASE
from campaign_manager.tests import test_zepto_translate_manual as MANUAL_CASE

OPTS = ALL_CASE.TARGETING_OPTIONS
CID = 2427461


def _body(detail):
    return translate.to_put(detail, OPTS, CID)


def _manual():
    return copy.deepcopy(MANUAL_CASE.GET_DETAIL)


def _all():
    return copy.deepcopy(ALL_CASE.GET_DETAIL)


# ── a faithful payload passes ───────────────────────────────────────────────

def test_faithful_payloads_pass_for_both_captured_campaigns():
    for detail in (_all(), _manual()):
        assert P.check(detail, _body(detail), shape=P.READBACK) == []


def test_a_budget_write_may_change_the_budget_and_nothing_else():
    d = _manual()
    body = _body(d)
    body["daily_budget"] = 900
    assert P.check(d, body, shape=P.BUDGET) == []
    assert any("daily_budget" in p for p in P.check(d, body, shape=P.READBACK))


# ── the three bugs the diff guard missed ────────────────────────────────────

def test_catches_an_empty_all_cities_list_ZC_A12():
    d = _all()
    body = _body(d)
    body["geo_targeting"]["city"]["include"] = []
    assert any("city_include" in p for p in P.check(d, body, shape=P.BUDGET))


def test_catches_city_objects_sent_instead_of_ids_ZC_A13():
    d = _manual()
    body = _body(d)
    body["geo_targeting"]["city"]["include"] = copy.deepcopy(d["city_targeting"])
    assert any("city_include" in p for p in P.check(d, body, shape=P.BUDGET))


def test_catches_dropped_negative_keywords_ZC_A14():
    d = _manual()
    body = _body(d)
    body["keyword_targeting"] = [k for k in body["keyword_targeting"] if not k.get("is_negative")]
    assert any("negative_keywords" in p for p in P.check(d, body, shape=P.BUDGET))


def test_the_diff_guard_alone_would_have_passed_those_bugs():
    """Why this module exists: a translator dropping negatives drops them from BOTH copies,
    so the before/after diff shows only the intended budget change."""
    d = _manual()
    broken = _body(d)
    broken["keyword_targeting"] = [k for k in broken["keyword_targeting"]
                                   if not k.get("is_negative")]
    mutated = copy.deepcopy(broken)
    mutated["daily_budget"] = 900
    assert [line.split(":")[0] for line in translate.diff(broken, mutated)] == [".daily_budget"]
    assert P.check(d, mutated, shape=P.BUDGET), "the faithfulness check must catch it"


# ── bids ────────────────────────────────────────────────────────────────────

def test_a_bid_write_may_change_only_its_own_keyword():
    d = _manual()
    body = _body(d)
    for k in body["keyword_targeting"]:
        if (k["text"], k["match_type"]) == ("pink toffee", "PHRASE"):
            k["bid_value"] = 14
    assert P.check(d, body, shape=P.BID, keyword=("pink toffee", "PHRASE")) == []
    # ...but the same body is a violation for any other target pair.
    assert P.check(d, body, shape=P.BID, keyword=("pink toffee", "EXACT"))


def test_a_bid_write_may_not_change_the_budget():
    d = _manual()
    body = _body(d)
    body["daily_budget"] = 900
    assert any("daily_budget" in p for p in
               P.check(d, body, shape=P.BID, keyword=("pink toffee", "EXACT")))


def test_a_bid_write_on_a_keyword_the_campaign_lacks_is_refused():
    d = _manual()
    assert P.check(d, _body(d), shape=P.BID, keyword=("sourdough", "EXACT"))


def test_a_bid_write_may_not_target_a_negative_keyword():
    d = _manual()
    assert P.check(d, _body(d), shape=P.BID, keyword=("test", "EXACT"))


def test_adding_or_dropping_a_bidding_keyword_is_caught():
    d = _manual()
    body = _body(d)
    body["keyword_targeting"].append({"text": "bagel", "match_type": "EXACT", "bid_value": 10})
    assert any(p.startswith("keywords") for p in P.check(d, body, shape=P.BUDGET))
    body = _body(d)
    body["keyword_targeting"].pop()
    assert any(p.startswith("keywords") for p in P.check(d, body, shape=P.BUDGET))


# ── every other restated field ──────────────────────────────────────────────

def _one_change(mutate, rule):
    d = _manual()
    body = _body(d)
    mutate(body)
    problems = P.check(d, body, shape=P.BUDGET)
    assert any(p.startswith(rule) for p in problems), f"{rule} not caught: {problems}"


def test_each_restated_field_is_checked():
    _one_change(lambda b: b.update(campaign_name="renamed"), "campaign_name")
    _one_change(lambda b: b.update(brand_id="someone-else"), "brand_id")
    _one_change(lambda b: b.update(lifetime_budget=5000), "lifetime_budget")
    _one_change(lambda b: b.update(bidding_strategy_type="DYNAMIC_UP_AND_DOWN"),
                "bidding_strategy_type")
    _one_change(lambda b: b.update(start_date="2026-08-22"), "start_date")
    _one_change(lambda b: b.update(end_date="2026-12-31"), "end_date")
    _one_change(lambda b: b["bid_multipliers"]["pdp"].update(base=5), "bid_multipliers")
    _one_change(lambda b: b["geo_targeting"].update(type="ALL"), "city_mode")
    _one_change(lambda b: b["geo_targeting"]["city"]["exclude"].append("x"), "city_exclude")
    _one_change(lambda b: b["product_config"]["product_variant_ids"].clear(), "products")
    _one_change(lambda b: b["product_config"].update(type="AUTO"), "product_mode")
    _one_change(lambda b: b["bid_targeting"].update(targeting_type="AUTO"), "bid_targeting")
    _one_change(lambda b: b.update(campaignId="999"), "campaign_id")


def test_a_full_timestamp_start_date_is_refused():
    """Echoing the GET's timestamp shifts the campaign's start — the trap the first golden
    test caught. It must not pass by reading as the right calendar date."""
    _one_change(lambda b: b.update(start_date="2026-08-21T12:20:30.808196+05:30"), "start_date")


def test_the_multiplier_time_key_is_structural():
    d = _manual()
    body = _body(d)
    body["bid_multipliers"]["time"] = {"time": {"mon": [1]}}
    assert any("bid_multipliers.time" in p for p in P.check(d, body, shape=P.BUDGET))


def test_a_missing_field_is_a_problem_not_a_pass():
    d = _manual()
    body = _body(d)
    del body["keyword_targeting"]
    assert any("missing" in p for p in P.check(d, body, shape=P.BUDGET))


def test_a_thin_detail_refuses_rather_than_passing_everything():
    try:
        P.verify({}, _body(_manual()), shape=P.BUDGET, campaign_id=CID)
    except writes.WriteRefused as e:
        assert "unreadable" in str(e)
    else:
        raise AssertionError("an empty detail must refuse")


def test_every_field_the_translator_sends_is_checked():
    """The coverage ratchet: a field added to `translate.to_put` without a rule here is
    written to live campaigns unchecked. Adding one must add a rule (or a structural check)."""
    leaves = set()

    def walk(obj, path=()):
        if isinstance(obj, dict) and obj and path[:1] != ("bid_multipliers",):
            for k, v in obj.items():
                walk(v, path + (k,))
        else:
            leaves.add(path)

    walk(_body(_manual()))
    covered = {path for _, path, *_ in P._RULES}

    def is_covered(leaf):
        return any(leaf[:len(c)] == c for c in covered)

    unchecked = sorted(".".join(leaf) for leaf in leaves if not is_covered(leaf))
    assert not unchecked, f"sent to Zepto with no faithfulness rule: {unchecked}"


# ── wired into the real write path ──────────────────────────────────────────

class _Client:
    brand_ids = ["b9cea5fc-da5f-4045-9b67-c07831733746"]


def _with_fakes(detail, *, after=None, to_put=None):
    """Run the adapter against fixtures. `after` is what a read-back returns; `to_put`
    replaces the translator (to inject a bug)."""
    sent = {}
    reads = {"n": 0}

    async def get_detail(client, campaign_id):
        reads["n"] += 1
        return copy.deepcopy(detail if reads["n"] == 1 or after is None else after)

    async def options(client, **_):
        return OPTS

    async def update(client, campaign_id, payload):
        sent.update(payload)
        return {"message": "Campaign updated successfully"}

    orig = (zc.get_campaign_detail, zc.get_targeting_options, zc.update_campaign,
            translate.to_put)
    zc.get_campaign_detail, zc.get_targeting_options, zc.update_campaign = (
        get_detail, options, update)
    if to_put is not None:
        translate.to_put = to_put
    return sent, orig


def _restore(orig):
    (zc.get_campaign_detail, zc.get_targeting_options, zc.update_campaign,
     translate.to_put) = orig


def test_a_translator_bug_is_refused_before_anything_is_sent():
    real = translate.to_put

    def drops_negatives(detail, options, campaign_id):
        body = real(detail, options, campaign_id)
        body["keyword_targeting"] = [k for k in body["keyword_targeting"]
                                     if not k.get("is_negative")]
        return body

    sent, orig = _with_fakes(_manual(), to_put=drops_negatives)
    try:
        asyncio.run(zad.apply_budget(_Client(), CID, 900))
    except writes.WriteRefused as e:
        assert "negative_keywords" in str(e) and "Nothing was sent" in str(e)
    else:
        raise AssertionError("a translator dropping negatives must be refused")
    finally:
        _restore(orig)
    assert sent == {}, "nothing may reach Zepto"


def test_a_clean_write_reads_back_clean():
    d = _manual()
    after = {**copy.deepcopy(d), "daily_budget": 900}
    sent, orig = _with_fakes(d, after=after)
    try:
        out = asyncio.run(zad.apply_budget(_Client(), CID, 900))
    finally:
        _restore(orig)
    assert sent["daily_budget"] == 900
    assert "post_write_mismatch" not in out


def test_zepto_changing_something_after_the_write_is_reported():
    """The write landed, so nothing can be undone — but it must not be silent."""
    d = _manual()
    after = {**copy.deepcopy(d), "daily_budget": 900,
             "city_targeting": d["city_targeting"][:1]}          # Mysuru vanished
    sent, orig = _with_fakes(d, after=after)
    try:
        out = asyncio.run(zad.apply_budget(_Client(), CID, 900))
    finally:
        _restore(orig)
    assert out.get("success") is True
    assert any("city_include" in p for p in out["post_write_mismatch"])


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
    print(f"\n{len(tests) - failed}/{len(tests)} zepto payload-invariant tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
