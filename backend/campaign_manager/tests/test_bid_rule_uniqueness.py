"""ZC-C9 — one LIVE bid automation per (tenant, platform, campaign, keyword, match type).

Two rules on one keyword do not merge: each reads the live bid, decides against its own
target and ceiling, and writes — so the bid oscillates every tick and neither rule's History
explains it. Both marketplaces are affected.

The DB index (`c4f7b2e81a93`) is the authority; this covers the code check that produces a
readable refusal — and that is the ONLY enforcement until that migration can be applied.
DB calls are stubbed.

    python -m campaign_manager.tests.test_bid_rule_uniqueness
"""
import asyncio
import uuid

from campaign_manager import repo
from campaign_manager.tests._zepto_flags import zepto_bidding_on

TENANT = uuid.UUID("fa53082e-7e83-424d-aab9-086fe1b4c680")


class _Rule:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _with_existing(existing, fn):
    """Run `fn()` with `live_bid_rule` answering `existing` (and recording its arguments)."""
    seen = {}

    async def _live(tenant_id, platform, campaign_id, keyword, match_type="EXACT", *,
                    exclude_id=None):
        seen.update(tenant_id=tenant_id, platform=platform, campaign_id=campaign_id,
                    keyword=keyword, match_type=match_type, exclude_id=exclude_id)
        return existing

    orig = repo.live_bid_rule
    repo.live_bid_rule = _live
    try:
        return fn(), seen
    finally:
        repo.live_bid_rule = orig


# ── the check ───────────────────────────────────────────────────────────────

def test_no_existing_rule_means_no_objection():
    _with_existing(None, lambda: asyncio.run(repo.require_no_live_bid_rule(
        TENANT, "zepto", 1, "pink toffee", "EXACT")))


def test_an_existing_live_rule_is_refused_and_named():
    def _go():
        try:
            asyncio.run(repo.require_no_live_bid_rule(TENANT, "zepto", 2427461,
                                                      "pink toffee", "exact"))
        except repo.DuplicateBidRule as e:
            return e
        raise AssertionError("must refuse")

    err, seen = _with_existing(_Rule(id="abc123"), _go)
    assert "pink toffee" in str(err) and "EXACT" in str(err)
    assert "rule abc123" in str(err), "say WHICH rule, so it can be edited instead"
    assert "Nothing was created" in str(err)
    assert err.rule_id == "abc123"


def test_the_match_type_is_part_of_the_identity():
    """One keyword is bid separately under EXACT / PHRASE / BROAD, so those are different
    automations — refusing the second would block a legitimate setup."""
    _, seen = _with_existing(None, lambda: asyncio.run(repo.require_no_live_bid_rule(
        TENANT, "zepto", 1, "pink toffee", "PHRASE")))
    assert seen["match_type"] == "PHRASE"


def test_a_missing_match_type_is_reported_as_EXACT():
    def _go():
        try:
            asyncio.run(repo.require_no_live_bid_rule(TENANT, "zepto", 1, "kw", None))
        except repo.DuplicateBidRule as e:
            return e
        raise AssertionError("must refuse")

    err, _ = _with_existing(_Rule(id="x"), _go)
    assert "(EXACT)" in str(err), "NULL match type IS EXACT everywhere in the engines"


# ── where it is enforced ────────────────────────────────────────────────────

def test_creating_a_rule_checks_before_writing_anything():
    calls = []

    async def _no_dupe(*a, **k):
        calls.append(("checked", a[1:]))

    async def _automatable(*a, **k):
        return None

    class _Boom:
        def __call__(self):
            raise AssertionError("must not reach the database")

    orig = (repo.require_no_live_bid_rule, repo.require_automatable, repo.AsyncSessionLocal)
    repo.require_no_live_bid_rule = _no_dupe
    repo.require_automatable = _automatable
    repo.AsyncSessionLocal = _Boom()
    try:
        asyncio.run(repo.create_bid_rule(TENANT, "blinkit", 77, "C", "bread", 3, 10))
    except AssertionError as e:
        assert "must not reach the database" in str(e)
    finally:
        (repo.require_no_live_bid_rule, repo.require_automatable,
         repo.AsyncSessionLocal) = orig
    assert calls and calls[0][1][0] == "blinkit"


@zepto_bidding_on
def test_resuming_a_paused_rule_checks_too_and_excludes_itself():
    """Pausing frees the keyword, so something else may have taken it. Resuming into that
    would be exactly the bid fight this prevents — and the rule must not find ITSELF."""
    paused = _Rule(id="me", tenant_id=TENANT, platform="zepto", campaign_id=1,
                   keyword="pink toffee", match_type="EXACT", active=False, state="paused")

    class _Db:
        def __call__(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, model, rule_id):
            return paused

        async def commit(self):
            raise AssertionError("must refuse before committing")

        async def refresh(self, row):
            return None

    def _go():
        try:
            asyncio.run(repo.set_bid_state("me", "active"))
        except repo.DuplicateBidRule as e:
            return e
        raise AssertionError("must refuse")

    orig = repo.AsyncSessionLocal
    repo.AsyncSessionLocal = _Db()
    try:
        err, seen = _with_existing(_Rule(id="other"), _go)
    finally:
        repo.AsyncSessionLocal = orig
    assert "rule other" in str(err)
    assert seen["exclude_id"] == "me", "a rule must not block its own resume"
    assert paused.state == "paused", "nothing changed"


def test_pausing_is_never_blocked():
    live = _Rule(id="me", tenant_id=TENANT, platform="zepto", campaign_id=1, keyword="kw",
                 match_type="EXACT", active=True, state="active")

    class _Db:
        def __call__(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, model, rule_id):
            return live

        async def commit(self):
            return None

        async def refresh(self, row):
            return None

    async def _never(*a, **k):
        raise AssertionError("pausing must not be duplicate-checked")

    orig = (repo.AsyncSessionLocal, repo.require_no_live_bid_rule)
    repo.AsyncSessionLocal, repo.require_no_live_bid_rule = _Db(), _never
    try:
        asyncio.run(repo.set_bid_state("me", "paused"))
    finally:
        repo.AsyncSessionLocal, repo.require_no_live_bid_rule = orig
    assert live.state == "paused" and live.active is False


def test_an_already_active_rule_is_not_rechecked():
    """Re-asserting `active` on a running rule (an idempotent call) must not trip over the
    rule itself being live."""
    live = _Rule(id="me", tenant_id=TENANT, platform="zepto", campaign_id=1, keyword="kw",
                 match_type="EXACT", active=True, state="active")

    class _Db:
        def __call__(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, model, rule_id):
            return live

        async def commit(self):
            return None

        async def refresh(self, row):
            return None

    async def _never(*a, **k):
        raise AssertionError("an already-active rule must not be re-checked")

    orig = (repo.AsyncSessionLocal, repo.require_no_live_bid_rule)
    repo.AsyncSessionLocal, repo.require_no_live_bid_rule = _Db(), _never
    try:
        asyncio.run(repo.set_bid_state("me", "active"))
    finally:
        repo.AsyncSessionLocal, repo.require_no_live_bid_rule = orig
    assert live.state == "active"


# ── the migration that will enforce it in the database ──────────────────────

def test_the_index_matches_the_code_check():
    """Same columns, same normalisation, same partiality — otherwise the DB and the code
    would disagree about what a duplicate is."""
    from pathlib import Path

    sql = Path("alembic/versions/c4f7b2e81a93_one_live_bid_rule_per_keyword.py").read_text(
        encoding="utf-8")
    for fragment in ("tenant_id, platform, campaign_id", "lower(trim(keyword))",
                     "upper(coalesce(match_type, 'EXACT'))", "WHERE active"):
        assert fragment in sql, fragment
    assert "CREATE UNIQUE INDEX" in sql


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} bid-rule uniqueness tests passed.")
