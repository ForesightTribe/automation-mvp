"""The write invariant: a PUT may only change what it was asked to change.

The test that justifies the whole module is `test_it_catches_the_original_city_bug` — it
feeds `payload.check` the exact payload the old bid builder produced (hardcoded
`city_ids: "-1"`) against a city-targeted campaign, and asserts it is rejected. Every other
test here defends that one from regressing into something weaker.

⚠️ A check that compares a payload to ANOTHER PAYLOAD cannot catch that bug — both copies
come from the same builder, so both contain the constant and the diff is empty. That is why
these rules invert the payload back into the campaign's own vocabulary and compare against
the DETAIL. `test_a_self_consistency_check_would_not_have_caught_it` pins the distinction so
nobody "simplifies" it away.

Pure — no Blinkit, no DB, no browser. Run with:

    python -m campaign_manager.tests.test_payload_invariant
"""
from campaign_manager.marketplaces.blinkit import payload
from campaign_manager.writes import WriteRefused

# A city-targeted campaign, as `get_campaign_detail` returns it.
DETAIL = {
    "name": "Foresight | Sprite [Delhi NCR]",
    "brand_name": "Dobra",
    "campaign_type": "PRODUCT_LISTING",
    "objective_type": "PERFORMANCE",
    "campaign_budget": 500,
    "pacing_type": "DAILY",
    "pids": "554767,554768",
    "start_ts": "2026-07-08T18:30:00",
    "end_ts": "2027-03-31T00:00:00",
    "region_type": "CITY",
    "region_ids": [2010, 2011, 2013],
    "campaign_targeting": {
        "keyword_targeting": {
            "keywords": [
                {"keyword": "sprite", "bids": [{"match_type": "EXACT", "cpm": 201}]},
                {"keyword": "soda", "bids": [{"match_type": "EXACT", "cpm": 150}]},
            ],
        },
    },
}


def _payload(**overrides) -> dict:
    """A faithful bid payload for DETAIL — the shape the builder produces when correct."""
    base = {
        "name": "Foresight | Sprite [Delhi NCR]",
        "brand_name": "Dobra",
        "advertiser_id": 19802,
        "asset_type": "PRODUCT_LISTING",
        "objective_type": "PERFORMANCE",
        "pids": "554767,554768",
        "campaign_start": "7/8/2026",
        "campaign_end": "3/31/2027",
        "bidding_strategy": {"total_budget": 500, "pacing_type": "DAILY"},
        "campaign_targeting": {
            "city_ids": "2010,2011,2013",
            "keyword_targeting": {
                "keywords": [
                    {"keyword": "sprite", "bids": [{"match_type": "EXACT", "cpm": 250}]},
                    {"keyword": "soda", "bids": [{"match_type": "EXACT", "cpm": 150}]},
                ],
            },
        },
    }
    for path, value in overrides.items():
        parts = path.split(".")
        target = base
        for hop in parts[:-1]:          # walk to the parent; a dot-free path stays at base
            target = target[hop]
        target[parts[-1]] = value
    return base


# ── The bug this exists for ─────────────────────────────────────────────────

def test_it_catches_the_original_city_bug():
    """The exact payload the bid builder produced for six weeks: a hardcoded `-1` against a
    campaign targeted at Delhi NCR. `-1` means ALL OF INDIA."""
    bad = _payload(**{"campaign_targeting.city_ids": "-1"})
    problems = payload.check(DETAIL, bad, shape=payload.BID)
    assert problems, "the -1 payload was accepted — this is the bug, unfixed"
    assert any("cities" in p for p in problems), problems


def test_a_self_consistency_check_would_not_have_caught_it():
    """Why the rules compare against the DETAIL and not against a second payload.

    Build the payload twice from the same broken builder — once 'unchanged', once with the
    bid moved. Both carry `-1`, so diffing them finds nothing. Any future refactor that
    turns this into a payload-vs-payload diff silently restores the original bug.
    """
    unchanged = _payload(**{"campaign_targeting.city_ids": "-1"})
    unchanged["campaign_targeting"]["keyword_targeting"]["keywords"][0]["bids"][0]["cpm"] = 201
    changed = _payload(**{"campaign_targeting.city_ids": "-1"})   # sprite already at 250

    self_diff = [k for k in unchanged if unchanged[k] != changed.get(k)]
    assert self_diff == ["campaign_targeting"], (
        f"a payload-vs-payload diff should see ONLY the intended bid change, saw {self_diff}")
    # Both carry city_ids "-1", so the self-diff is blind to the campaign-destroying field.
    assert unchanged["campaign_targeting"]["city_ids"] == "-1"
    assert changed["campaign_targeting"]["city_ids"] == "-1"
    # …yet the real check, against the campaign, rejects it.
    assert payload.check(DETAIL, changed, shape=payload.BID)


# ── A faithful payload passes ───────────────────────────────────────────────

def test_a_faithful_bid_payload_passes():
    assert payload.check(DETAIL, _payload(), shape=payload.BID) == []


def test_pan_india_campaign_may_send_minus_one():
    """`-1` is correct when the campaign really is untargeted — the check must not force
    every campaign to look city-targeted."""
    pan = {**DETAIL, "region_type": "PAN_INDIA", "region_ids": None}
    p = _payload(**{"campaign_targeting.city_ids": "-1"})
    assert payload.check(pan, p, shape=payload.BID) == []


def test_city_order_does_not_matter():
    p = _payload(**{"campaign_targeting.city_ids": "2013,2010,2011"})
    assert payload.check(DETAIL, p, shape=payload.BID) == []


def test_budget_int_vs_float_is_not_a_mismatch():
    assert payload.check(DETAIL, _payload(**{"bidding_strategy.total_budget": 500.0}),
                         shape=payload.BID) == []


# ── Each shape may change only its own thing ────────────────────────────────

def test_a_bid_write_may_change_bids_but_not_the_budget():
    moved_budget = _payload(**{"bidding_strategy.total_budget": 9999})
    problems = payload.check(DETAIL, moved_budget, shape=payload.BID)
    assert any("budget" in p for p in problems), problems


def test_a_budget_write_may_change_the_budget():
    assert payload.check(DETAIL, _payload(**{"bidding_strategy.total_budget": 9999}),
                         shape=payload.BUDGET) == []


def test_a_budget_write_may_not_drop_keywords():
    """The failure mode the bid builder's merge logic exists to prevent: sending a partial
    keyword list REPLACES the campaign's keywords."""
    p = _payload()
    p["campaign_targeting"]["keyword_targeting"]["keywords"] = [
        {"keyword": "sprite", "bids": [{"match_type": "EXACT", "cpm": 201}]},
    ]
    problems = payload.check(DETAIL, p, shape=payload.BUDGET)
    assert any("keywords" in x for x in problems), problems


def test_a_restart_may_reset_the_dates_and_budget_but_not_the_cities():
    p = _payload(advertiser_id=0, **{"bidding_strategy.total_budget": 200})
    assert payload.check(DETAIL, p, shape=payload.RESTART) == []
    p_bad = _payload(advertiser_id=0, **{"campaign_targeting.city_ids": "-1",
                                        "bidding_strategy.total_budget": 200})
    assert any("cities" in x for x in payload.check(DETAIL, p_bad, shape=payload.RESTART))


def test_dropping_products_is_caught():
    problems = payload.check(DETAIL, _payload(pids="554767"), shape=payload.BID)
    assert any("pids" in p for p in problems), problems


def test_renaming_the_campaign_is_caught():
    problems = payload.check(DETAIL, _payload(name="something else"), shape=payload.BID)
    assert any("name" in p for p in problems), problems


# ── An absent field is the builder's business, not the checker's ────────────

def test_absent_fields_are_not_flagged():
    """A campaign with no keyword targeting sends no `keyword_targeting` block at all.
    Absent ≠ wrong: this checks what IS sent."""
    thin = {"name": "Foresight | Sprite [Delhi NCR]"}
    assert payload.check(DETAIL, thin, shape=payload.BID) == []


# ── verify() is the raising wrapper ─────────────────────────────────────────

def test_verify_raises_writerefused_so_one_write_dies_not_the_run():
    bad = _payload(**{"campaign_targeting.city_ids": "-1"})
    try:
        payload.verify(DETAIL, bad, shape=payload.BID, campaign_id=568944)
    except WriteRefused as e:
        assert "568944" in str(e) and "cities" in str(e), str(e)
        return
    raise AssertionError("verify accepted a payload that would broaden the campaign")


def test_verify_is_silent_on_a_faithful_payload():
    payload.verify(DETAIL, _payload(), shape=payload.BID, campaign_id=1)


# ── Holes found by probing the first version, now pinned shut ──────────────

def test_a_null_value_is_checked_not_skipped():
    """`city_ids: None` is a VALUE, not an omission. The first version collapsed
    present-but-null into absent and let it through unexamined."""
    problems = payload.check(DETAIL, _payload(**{"campaign_targeting.city_ids": None}),
                             shape=payload.BID)
    assert any("cities" in p for p in problems), problems


def test_a_bid_write_may_not_drop_a_keyword():
    """The worst of the first version's holes: `BID` exempted the keyword rule, so a bid
    write — the exact operation that caused the incident — could delete keywords unchecked.
    The rule checks the keyword SET; a bid write changes a CPM, so it never needed exempting.
    """
    p = _payload()
    p["campaign_targeting"]["keyword_targeting"]["keywords"] = [
        {"keyword": "sprite", "bids": [{"match_type": "EXACT", "cpm": 250}]},
    ]
    problems = payload.check(DETAIL, p, shape=payload.BID)
    assert any("keywords" in x for x in problems), problems


def test_a_bid_write_may_ADD_a_keyword():
    """`update_keyword_bids` legitimately appends a keyword that is not on the campaign yet.
    Dropping is the damage; adding is an operation. Hence NO_LOSS, not equality."""
    p = _payload()
    p["campaign_targeting"]["keyword_targeting"]["keywords"].append(
        {"keyword": "lemonade", "bids": [{"match_type": "EXACT", "cpm": 300}]})
    assert payload.check(DETAIL, p, shape=payload.BID) == []


def test_a_thin_detail_refuses_rather_than_passing_everything():
    """`_fetch` turns a Blinkit error page into `{}`. Every rule compares against the
    detail, so an empty one makes the check vacuous — it would wave through anything,
    exactly when the payload built from that same failed read is most dangerous."""
    for thin in ({}, {"campaign_budget": 500}):
        try:
            payload.verify(thin, _payload(), shape=payload.BID, campaign_id=1)
        except WriteRefused:
            continue
        raise AssertionError(f"a payload was accepted against detail={thin!r}")


def test_a_mangled_date_is_caught():
    """Every write reformats the dates, so a broken conversion re-dates a live campaign."""
    problems = payload.check(DETAIL, _payload(campaign_start="1/1/1970"), shape=payload.BID)
    assert any("campaign_start" in p for p in problems), problems


def test_a_restart_may_reset_the_dates():
    p = _payload(advertiser_id=0, campaign_start="9/3/2026", campaign_end="12/31/9999")
    assert payload.check(DETAIL, p, shape=payload.RESTART) == []


# ── Coverage: what the table builds vs what the invariant checks ───────────

# Fields that genuinely cannot be verified against the campaign, with the reason. Anything
# NOT here and NOT covered by a rule is an unguarded field, and the test below fails.
UNCHECKABLE = {
    "source_platform":       "a constant Blinkit expects; the campaign has no such field",
    "requested_by":          "our operator's email, not a campaign property",
    "campaign_request_type": "names the operation, not the campaign",
    "campaign_id":           "the address of the write, checked by the caller",
    "is_extendable":         "a constant the dashboard sends; no campaign equivalent",
    "preview_image_url":     "a constant the dashboard sends; no campaign equivalent",
    "campaign_data":         "checked field-by-field instead — see the campaign_data.pids "
                             "rule; the rest of the block is shape-specific scaffolding",
    "campaign_targeting":    "checked field-by-field — cities and keywords have their own rules",
    "bidding_strategy":      "checked field-by-field — budget and pacing have their own rules",
}


def test_every_derived_field_is_checked():
    """Every field the builder derives from the campaign must have a verification rule.

    This is the coverage ratchet. When the table gained rows, the checker did not follow —
    27 fields were built and 8 checked, and the gap was invisible because nothing measured
    it. Adding a row to `build.FIELDS` now fails this test until you either write a rule or
    state in `UNCHECKABLE` why the field cannot have one.
    """
    from campaign_manager.marketplaces.blinkit import build

    built = {key for key, _, _ in build.FIELDS}
    checked = ({path[0] for _, path, *_ in payload._RULES}
               | set(payload.STRUCTURAL_FIELDS))
    unguarded = built - checked - set(UNCHECKABLE)
    assert not unguarded, (
        f"{len(unguarded)} field(s) are built but neither checked nor declared "
        f"unverifiable: {sorted(unguarded)}")


def test_the_unverifiable_list_stays_honest():
    """Nobody may park a field in UNCHECKABLE that the builder no longer sends — that would
    quietly shrink the ratchet's job over time."""
    from campaign_manager.marketplaces.blinkit import build

    built = {key for key, _, _ in build.FIELDS}
    stale = set(UNCHECKABLE) - built
    assert not stale, f"UNCHECKABLE names fields that are no longer built: {sorted(stale)}"


# ── The WRITE direction: payload.city_ids ──────────────────────────────────
#
# Folded in from the old test_city_targeting.py when `city_ids` moved into payload.py.
# One module owns both directions of the translation, so one suite tests both.

def test_city_ids_from_a_list():
    assert payload.city_ids(DETAIL) == "2010,2011,2013"


def test_city_ids_from_a_string():
    """Blinkit returns this already comma-separated on some campaigns."""
    assert payload.city_ids({**DETAIL, "region_ids": "2010,2011"}) == "2010,2011"


def test_city_ids_from_a_bare_scalar():
    assert payload.city_ids({**DETAIL, "region_ids": 2010}) == "2010"


def test_city_ids_pan_india_collapses_to_minus_one():
    assert payload.city_ids({**DETAIL, "region_type": "PAN_INDIA", "region_ids": None}) == "-1"
    assert payload.city_ids({"region_ids": []}) == "-1"
    assert payload.city_ids({}) == "-1"


def test_city_ids_blank_entries_are_dropped():
    assert payload.city_ids({**DETAIL, "region_ids": [2010, None, "", 2011]}) == "2010,2011"


def test_city_ids_refuses_a_city_campaign_with_unreadable_ids():
    """The fail-open case that made the original bug invisible: a campaign that says it is
    city-targeted but whose ids we cannot read must abort the write, not default to -1."""
    for bad in (None, [], "", "  "):
        try:
            payload.city_ids({"region_type": "CITY", "region_ids": bad})
        except WriteRefused:
            continue
        raise AssertionError(f"region_ids={bad!r} on a CITY campaign should have raised")


def test_no_builder_hardcodes_the_minus_one_literal():
    """The source-level guard. That literal is exactly what the bug was, and it is invisible
    to any test that only exercises a pan-India campaign — which is what the golden captured
    payload happens to be."""
    from pathlib import Path
    here = Path(__file__).resolve().parents[1] / "marketplaces" / "blinkit"
    for name in ("client.py", "restart.py"):
        source = (here / name).read_text(encoding="utf-8")
        for literal in ('"city_ids": "-1"', "'city_ids': '-1'"):
            assert literal not in source, (
                f"{name} hardcodes {literal} — city targeting must come from "
                f"payload.city_ids(detail)")


def test_a_refusal_costs_one_write_not_the_whole_run():
    """The engines wrap their loops in try/FINALLY, so an exception escaping a write would
    abort the run and silently skip every campaign after it. `writes.apply_bid` must catch
    the refusal and report a failed write instead."""
    import asyncio
    from campaign_manager import writes

    class _RefusingAdapter:
        MIN_BID = None
        MAX_BID = None

        async def apply_bid(self, client, campaign_id, keyword, cpm, match_type):
            raise WriteRefused("region_type=CITY but no readable region_ids")

    ok = asyncio.run(writes.apply_bid(
        _RefusingAdapter(), client=None, run_id="test", campaign_id=568944,
        keyword="sprite", new_cpm=250, current_cpm=201, min_bid=100, max_bid=500,
        dry_run=False, recent_writes=0))
    assert ok is False, "a refused write must report not-applied, not raise"


# ── the two gaps closed 2026-09-04 ─────────────────────────────────────────

def test_an_update_must_carry_a_real_advertiser_id():
    for bad in (0, None, -1, "19802"):
        assert payload.check(DETAIL, _payload(advertiser_id=bad), shape=payload.BID), (
            f"advertiser_id={bad!r} was accepted on an UPDATE")
    assert payload.check(DETAIL, _payload(advertiser_id=19802), shape=payload.BID) == []


def test_a_restart_must_send_advertiser_zero():
    """AD4 — the server derives the account from the token for a RESTART, and the dashboard
    sends 0. Sending the real id here is a different request than the captured one."""
    assert payload.check(DETAIL, _payload(advertiser_id=19802), shape=payload.RESTART)
    assert payload.check(DETAIL, _payload(advertiser_id=0), shape=payload.RESTART) == []


def test_brand_name_is_checked_on_updates_and_exempt_on_restart():
    assert any("brand_name" in p for p in
               payload.check(DETAIL, _payload(brand_name="NotDobra"), shape=payload.BID))
    assert payload.check(DETAIL, _payload(advertiser_id=0, brand_name=""),
                         shape=payload.RESTART) == []


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
    print(f"\n{len(tests) - failed}/{len(tests)} payload-invariant tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
