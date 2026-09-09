"""Reconciler schedule names must render as something a person can read.

`reconciler` names its rows as machine keys — `auto:cm:budget:<uuid>:blinkit:0200` —
and that is correct: `_apply` matches desired rows against existing ones BY NAME and
`_is_managed` parses the platform out of them, so the format is load-bearing. The
mistake was showing it to people: in `cli schedules list`, in `cli status`, and inside
`check_deadman`'s overdue ALERTS, where a 2am page read `0200` and a 36-char UUID.

`jobs.types.schedule_label` renders them instead. This file is the coupling guard: it
lives on the side that OWNS the name format, so adding a new `Desired(...)` shape in
the reconciler without teaching the label function about it fails here rather than
silently printing a raw key in an alert months later.

    python -m campaign_manager.tests.test_schedule_labels
"""
from jobs.types import schedule_label

TENANT = "a870fd8d-7373-47ec-ad69-5dd08ce35542"
P = f"auto:cm:"

# Every shape `reconciler.py` builds, in the order it builds them. Keep in sync with
# the `Desired(f"{_PREFIX}...")` call sites — that is the point of this file.
SHAPES = {
    f"{P}budget:{TENANT}:blinkit:0200":                  "Blinkit budget · 02:00",
    f"{P}budget:{TENANT}:blinkit:1930":                  "Blinkit budget · 19:30",
    f"{P}budget:{TENANT}:blinkit:poll":                  "Blinkit budget · hourly catch-up",
    f"{P}budget:{TENANT}:blinkit:once:20260904T0200":    "Blinkit budget · one-off 04 Sep 02:00",
    f"{P}budget:{TENANT}:blinkit:expire:42":             "Blinkit budget · reset after rule 42 ends",
    f"{P}bid:{TENANT}:blinkit:opt":                      "Blinkit bids · optimiser",
    f"{P}bid:{TENANT}:blinkit:reset:1930":               "Blinkit bids · reset 19:30",
    f"{P}bid:{TENANT}:blinkit:reset:20260904T1930":      "Blinkit bids · reset 04 Sep 19:30",
    f"{P}bid:{TENANT}:blinkit:once:20260904":            "Blinkit bids · one-off 04 Sep",
    f"{P}cleanup:{TENANT}:blinkit":                      "Blinkit automations · nightly tidy-up",
}


def test_every_reconciler_shape_renders():
    for name, expected in SHAPES.items():
        assert schedule_label(name) == expected, f"{name}\n  got: {schedule_label(name)}"


def test_no_label_leaks_a_uuid():
    """The single worst thing about the old names, and the reason this exists. The
    tenant is already its own column on every surface that shows a schedule."""
    for name in SHAPES:
        assert TENANT not in schedule_label(name)


def test_no_label_is_just_the_raw_key():
    """The fallback is correct behaviour for an UNKNOWN name, but for a shape the
    reconciler actually produces it means someone added a `Desired(...)` and did not
    teach `schedule_label` about it."""
    for name in SHAPES:
        assert schedule_label(name) != name, f"{name} fell through to the raw key"


def test_labels_are_short_enough_for_a_table_cell():
    for name, label in ((n, schedule_label(n)) for n in SHAPES):
        assert len(label) <= 45, f"{label!r} is {len(label)} chars"


# ── the reconciler is the source of truth, so check against it directly ──────

def test_the_shape_list_matches_the_reconciler_source():
    """Guards the guard. If a new `Desired(f"{_PREFIX}…")` appears in reconciler.py with
    a `kind` this file has never seen, the table above is stale — which would let an
    unrendered name reach an alert while these tests still passed."""
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "reconciler.py").read_text(encoding="utf-8")
    # kinds the reconciler emits: the token right after the prefix
    emitted = set(re.findall(r'_PREFIX\}(\w+):', src))
    covered = {n.split(":")[2] for n in SHAPES}
    missing = emitted - covered
    assert not missing, f"reconciler emits kinds with no label coverage: {sorted(missing)}"


# ── anything not ours is left alone ──────────────────────────────────────────

def test_hand_written_names_pass_through_untouched():
    """`schedules add` rows are already written for humans — never reformat them."""
    for name in ("DOBRA | Blinkit scorecard weekly", "Heartbeat hourly", "Log cleanup weekly"):
        assert schedule_label(name) == name


def test_an_unknown_shape_falls_back_to_the_raw_key():
    """Same rule as `label_for`: a name we cannot parse must still be printable. The
    case that produces one is a format change — exactly when a readable message is
    needed most, so failing here would be the worst possible behaviour."""
    weird = f"{P}newkind:{TENANT}:blinkit:something:else"
    assert schedule_label(weird).startswith("Blinkit newkind")
    assert schedule_label(f"{P}too:short") == f"{P}too:short"


def test_empty_and_none_are_safe():
    assert schedule_label(None) == ""
    assert schedule_label("") == ""


# ── whose schedule is it ─────────────────────────────────────────────────────

def test_the_client_is_named_when_known():
    """Two active tenants share this table, so 'Blinkit budget · 02:00 is overdue'
    does not identify anything. Matches the hand-made rows' `DOBRA | …` style so a
    listing reads consistently."""
    got = schedule_label(f"{P}budget:{TENANT}:blinkit:0200", "Dobra")
    assert got == "DOBRA | Blinkit budget · 02:00"


def test_an_unknown_client_is_omitted_not_guessed():
    assert schedule_label(f"{P}bid:{TENANT}:blinkit:opt", None) == "Blinkit bids · optimiser"


def test_a_hand_made_name_never_gets_a_second_prefix():
    """`DOBRA | Blinkit seller daily` already names its client; prefixing again would
    render `DOBRA | DOBRA | …`."""
    manual = "DOBRA | Blinkit seller daily"
    assert schedule_label(manual, "Dobra") == manual


def test_a_second_marketplace_reads_correctly():
    """Names carry the platform, so Zepto rows must label themselves without a change."""
    assert schedule_label(f"{P}bid:{TENANT}:zepto:opt") == "Zepto bids · optimiser"


def test_a_bogus_time_token_is_not_silently_reformatted():
    """`9999` is not a time. Better to show the raw token than to invent '99:99'."""
    assert schedule_label(f"{P}budget:{TENANT}:blinkit:9999") == "Blinkit budget · 9999"


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
    print(f"\n{len(tests) - failed}/{len(tests)} schedule-label tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
