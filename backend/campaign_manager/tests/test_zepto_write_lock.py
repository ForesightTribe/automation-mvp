"""ZC-C8 — one writer at a time per campaign.

Zepto's budget and bid writes are both a read-modify-write of the WHOLE campaign, and the
engines that make them run in parallel lanes. Overlap does not fail: the second PUT reverts
the first one's field, silently. These tests pin the lock that prevents it — against a fake
Postgres that implements `pg_try_advisory_lock` in a dict, so no DB is needed.

    python -m campaign_manager.tests.test_zepto_write_lock
"""
import asyncio

from campaign_manager import repo, writes
from campaign_manager.marketplaces.zepto import adapter as zad


class _FakePg:
    """`AsyncSessionLocal` over an in-memory lock table, one entry per key."""

    def __init__(self, fail: bool = False):
        self.held: set[int] = set()
        self.fail = fail
        self.calls: list[str] = []

    def __call__(self):
        return _FakeSession(self)


class _FakeSession:
    def __init__(self, pg):
        self.pg = pg

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _key(self, params):
        return params["k"]

    async def scalar(self, stmt, params=None):
        if self.pg.fail:
            raise RuntimeError("database is down")
        key = self._key(params)
        self.pg.calls.append("try")
        if key in self.pg.held:
            return False
        self.pg.held.add(key)
        return True

    async def execute(self, stmt, params=None):
        self.pg.calls.append("unlock")
        self.pg.held.discard(self._key(params))
        return None


def _with_pg(pg, coro_factory):
    orig = repo.AsyncSessionLocal
    repo.AsyncSessionLocal = pg
    try:
        return asyncio.run(coro_factory())
    finally:
        repo.AsyncSessionLocal = orig


# ── the key ─────────────────────────────────────────────────────────────────

def test_the_key_is_stable_across_processes():
    """`hash()` is salted per process, so two runners would compute different keys for one
    campaign and never see each other's lock — the one failure mode that must not exist."""
    a = repo._lock_key("zepto", "tenant-1", 2427461)
    assert a == repo._lock_key("zepto", "tenant-1", 2427461)
    assert a == 8570992933641567408, "the key changed — running jobs would not see old locks"


def test_different_campaigns_tenants_and_platforms_do_not_share_a_lock():
    keys = {repo._lock_key("zepto", "t1", 1), repo._lock_key("zepto", "t1", 2),
            repo._lock_key("zepto", "t2", 1), repo._lock_key("blinkit", "t1", 1)}
    assert len(keys) == 4


def test_the_key_fits_postgres_bigint():
    k = repo._lock_key("zepto", "t", 99)
    assert -(2 ** 63) <= k < 2 ** 63


# ── the lock ────────────────────────────────────────────────────────────────

def test_a_second_writer_waits_and_then_proceeds():
    pg = _FakePg()
    order: list[str] = []

    async def _main():
        async def first():
            async with repo.campaign_write_lock("zepto", "t", 1):
                order.append("first in")
                await asyncio.sleep(0.4)
                order.append("first out")

        async def second():
            await asyncio.sleep(0.05)
            async with repo.campaign_write_lock("zepto", "t", 1):
                order.append("second in")

        await asyncio.gather(first(), second())

    _with_pg(pg, _main)
    assert order == ["first in", "first out", "second in"], order
    assert not pg.held, "the lock must be released"


def test_two_campaigns_never_block_each_other():
    pg = _FakePg()
    order: list[str] = []

    async def _main():
        async def hold(cid, label):
            async with repo.campaign_write_lock("zepto", "t", cid):
                order.append(f"{label} in")
                await asyncio.sleep(0.2)

        await asyncio.gather(hold(1, "a"), hold(2, "b"))

    _with_pg(pg, _main)
    assert order == ["a in", "b in"], order


def test_a_holder_that_never_finishes_refuses_rather_than_hangs():
    pg = _FakePg()
    pg.held.add(repo._lock_key("zepto", "t", 1))       # somebody else is mid-write

    async def _main():
        try:
            async with repo.campaign_write_lock("zepto", "t", 1, timeout_s=0.3):
                raise AssertionError("must not enter")
        except repo.WriteLockBusy as e:
            return str(e)

    msg = _with_pg(pg, _main)
    assert "campaign 1" in msg and "0.3s" in msg


def test_the_lock_is_released_even_when_the_write_raises():
    pg = _FakePg()

    async def _main():
        try:
            async with repo.campaign_write_lock("zepto", "t", 1):
                raise ValueError("the PUT failed")
        except ValueError:
            pass

    _with_pg(pg, _main)
    assert not pg.held
    assert "unlock" in pg.calls


def test_a_broken_lock_service_does_not_block_writing():
    """Fail-open: losing every write because the lock cannot be taken would be a bigger
    outage than the overlap it prevents."""
    pg = _FakePg(fail=True)
    entered = []

    async def _main():
        async with repo.campaign_write_lock("zepto", "t", 1):
            entered.append(True)

    _with_pg(pg, _main)
    assert entered == [True]


# ── the adapter ─────────────────────────────────────────────────────────────

def _busy_lock():
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _busy(platform, tenant_id, campaign_id, **kw):
        raise repo.WriteLockBusy("another job has been writing for more than 45s")
        yield           # pragma: no cover  (makes it a generator)
    return _busy


def test_a_busy_budget_write_is_refused_not_crashed():
    """`WriteRefused` is the engines' "we did not send it" — the run carries on with the
    next campaign and the tick retries. An unhandled error would fail the whole run."""
    async def _main():
        return await zad.apply_budget(object(), 2427461, 600)

    orig, reads = repo.campaign_write_lock, []
    repo.campaign_write_lock = _busy_lock()

    async def _never(client, campaign_id):
        reads.append(campaign_id)
        raise AssertionError("must not read the campaign while another write holds it")

    zorig = zad._rebased_payload
    zad._rebased_payload = _never
    try:
        asyncio.run(_main())
    except writes.WriteRefused as e:
        assert "cannot overwrite each other" in str(e)
    else:
        raise AssertionError("must refuse")
    finally:
        repo.campaign_write_lock, zad._rebased_payload = orig, zorig
    assert reads == [], "nothing was read, so nothing was sent"


def test_a_busy_bid_write_is_refused_too():
    orig = repo.campaign_write_lock
    repo.campaign_write_lock = _busy_lock()
    try:
        asyncio.run(zad.apply_bid(object(), 2427461, "pink toffee", 12, "EXACT"))
    except writes.WriteRefused as e:
        assert "cannot overwrite each other" in str(e)
    else:
        raise AssertionError("must refuse")
    finally:
        repo.campaign_write_lock = orig


def test_the_bid_read_happens_INSIDE_the_lock():
    """The keyword index is only valid for the list it was read from, so a budget PUT
    landing between the read and ours would move the bid onto the wrong keyword."""
    events = []
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _watch(platform, tenant_id, campaign_id, **kw):
        events.append("lock")
        yield
        events.append("unlock")

    async def _read(client, campaign_id):
        events.append("read")
        raise writes.WriteRefused("stop here — the read is all we are watching")

    orig = (repo.campaign_write_lock, zad._rebased_payload)
    repo.campaign_write_lock, zad._rebased_payload = _watch, _read
    try:
        asyncio.run(zad.apply_bid(object(), 2427461, "pink toffee", 12, "EXACT"))
    except writes.WriteRefused:
        pass
    finally:
        repo.campaign_write_lock, zad._rebased_payload = orig
    assert events[:2] == ["lock", "read"], events


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} zepto write-lock tests passed.")
