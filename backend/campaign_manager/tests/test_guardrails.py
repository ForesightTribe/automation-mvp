"""Unit tests for the write-choke-point guardrails (docs §12.1 / V0.10).

Pure logic — no Blinkit, no DB. The repo has no pytest yet, so these are plain
assert-based tests: `test_*` functions (pytest-discoverable if pytest is added
later) plus a `__main__` runner so they work today with:

    python -m campaign_manager.tests.test_guardrails
"""
from campaign_manager import config, writes


def test_bounds_rejects_zero_and_absurd():
    assert writes.budget_out_of_bounds(0) is not None          # a bug computing 0 → rejected
    assert writes.budget_out_of_bounds(-5) is not None
    assert writes.budget_out_of_bounds(10_000_000) is not None  # absurdly high → rejected
    assert writes.budget_out_of_bounds(None) is not None


def test_bounds_accepts_sane():
    assert writes.budget_out_of_bounds(500) is None
    assert writes.budget_out_of_bounds(config.MIN_BUDGET) is None
    assert writes.budget_out_of_bounds(config.MAX_BUDGET) is None


def test_bounds_honours_explicit_range():
    assert writes.budget_out_of_bounds(50, min_budget=100, max_budget=1000) is not None
    assert writes.budget_out_of_bounds(500, min_budget=100, max_budget=1000) is None


def test_clamp_bid():
    assert writes.clamp_bid(50, 100, 900) == 100     # below min → min
    assert writes.clamp_bid(2000, 100, 900) == 900   # above max → max
    assert writes.clamp_bid(400, 100, 900) == 400    # within → unchanged


def test_noop_skip():
    assert writes.is_noop(500, 500) is True          # same → skip
    assert writes.is_noop(500.0, 500) is True         # numeric equality across types
    assert writes.is_noop(600, 500) is False          # different → write
    assert writes.is_noop(500, None) is False         # unknown current → not a no-op


def test_rate_limit():
    cap = config.MAX_WRITES_PER_WINDOW
    assert writes.exceeds_rate_limit(cap) is True     # at the cap → refuse
    assert writes.exceeds_rate_limit(cap + 3) is True
    assert writes.exceeds_rate_limit(cap - 1) is False
    assert writes.exceeds_rate_limit(0, limit=5) is False
    assert writes.exceeds_rate_limit(5, limit=5) is True


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
    print(f"\n{len(tests) - failed}/{len(tests)} guardrail tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
