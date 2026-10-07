"""Instamart private scrape — the run (dashboard_data/run.py).

What each section records in `scrape_jobs`, and how failures travel:

  * sales: no job row unless loading; --no-load downloads and reports only
  * po: line items lost once are re-fetched; still lost -> job FAILED with the
    rows that did land (it used to say success); the export never fails it
  * one section failing does not stop the next; missing credentials fail all

No network, browser or database: every collaborator is a fake.

Run:  python -m pytest scraper/platforms/instamart/dashboard_data/tests
"""
import asyncio
import contextlib
import datetime as dt
import uuid
from pathlib import Path
from types import SimpleNamespace

from scraper.platforms.instamart.dashboard_data import run as ir

TENANT = "fa53082e-7e83-424d-aab9-086fe1b4c680"
CREDS = SimpleNamespace(email="e@x.com", extra={"account_id": "acc", "brand_account_id": "brand"})


class _FastAsyncio:
    def __getattr__(self, name):
        return getattr(asyncio, name)

    @staticmethod
    async def sleep(_s, *a, **k):
        return None


class _DB:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        return None


class _Portal:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def brand_account_id(self):
        return None


class _HTTP:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _async(value):
    async def fn(*a, **k):
        if isinstance(value, Exception):
            raise value
        return value(*a, **k) if callable(value) else value
    return fn


class _Jobs:
    def __init__(self):
        self.created: list[str] = []
        self.closed: list[tuple] = []

    async def create(self, _db, _tid, dashboard, *a, **k):
        self.created.append(dashboard)
        return str(uuid.uuid4())

    async def complete(self, _db, _job, records=0):
        self.closed.append(("success", records))

    async def fail(self, _db, _job, error, records_written=None):
        self.closed.append(("failed", error, records_written))


@contextlib.contextmanager
def _patched(jobs: _Jobs, **attrs):
    """Patch run.py's names (`name`) and its imported modules (`module__name`)."""
    targets = {
        (ir, "asyncio"): _FastAsyncio(),
        (ir, "AsyncSessionLocal"): _DB,
        (ir, "PortalSession"): _Portal,
        (ir, "create_scrape_job"): jobs.create,
        (ir, "complete_scrape_job"): jobs.complete,
        (ir, "fail_scrape_job"): jobs.fail,
        (ir, "tenant_slug"): _async("brik-oven"),
        (ir.auth_store, "get_credentials"): _async(CREDS),
        (ir.httpx, "AsyncClient"): _HTTP,
    }
    for key, v in attrs.items():
        if "__" in key:
            mod, name = key.split("__", 1)
            targets[(getattr(ir, mod), name)] = v
        else:
            targets[(ir, key)] = v
    saved = {k: getattr(*k) for k in targets}
    for (mod, name), v in targets.items():
        setattr(mod, name, v)
    try:
        yield
    finally:
        for (mod, name), v in saved.items():
            setattr(mod, name, v)


def _run(**kw):
    return asyncio.run(ir.run(TENANT, **kw))


# ── windows ──────────────────────────────────────────────────────────────────

def test_sales_window():
    today = dt.date(2026, 10, 6)
    y = dt.date(2026, 10, 5)
    assert ir.sales_window(None, None, None, today) == (y, y)
    assert ir.sales_window(None, None, 4, today) == (dt.date(2026, 10, 2), y)
    assert ir.sales_window("2026-09-30", None, None, today) == (dt.date(2026, 9, 30),) * 2
    assert ir.sales_window("2026-09-30", "2026-10-02", None, today) == (
        dt.date(2026, 9, 30), dt.date(2026, 10, 2))


def test_sales_window_too_long_fails_before_any_job():
    jobs = _Jobs()
    with _patched(jobs):
        [res] = _run(sales=True, ads=False, po=False, date_from="2026-08-01", date_to="2026-09-30")
    assert not res.ok and "31" in res.error
    assert jobs.created == []


# ── sales ────────────────────────────────────────────────────────────────────

def _sales_fakes(tmp: Path):
    xlsx = tmp / "IMSales.xlsx"
    xlsx.write_bytes(b"x")
    store = [{"date": dt.date(2026, 10, 5), "store_id": "1", "item_code": "I", "gmv": 100.0, "units_sold": 2}]
    return xlsx, {
        "seller_scraper__fetch_sales_report": _async(xlsx),
        "seller_parser__parse": lambda _p: (list(store), [{"date": dt.date(2026, 10, 5), "city": "B"}]),
        "seller_storage__save_sales": _async({"store_daily": 1, "brand_city": 1}),
    }


def test_sales_loads_and_deletes_the_file(tmp_path):
    jobs = _Jobs()
    xlsx, fakes = _sales_fakes(tmp_path)
    with _patched(jobs, **fakes):
        [res] = _run(sales=True, ads=False, po=False)
    assert res.ok and res.written == {"store_daily": 1, "brand_city": 1}
    assert jobs.created == ["instamart_seller_sales"]
    assert jobs.closed == [("success", 2)]
    assert not xlsx.exists()


def test_sales_no_load_writes_nothing_and_keep_file_keeps_it(tmp_path):
    jobs = _Jobs()
    xlsx, fakes = _sales_fakes(tmp_path)
    fakes["seller_storage__save_sales"] = _async(AssertionError("must not save"))
    with _patched(jobs, **fakes):
        [res] = _run(sales=True, ads=False, po=False, load=False, keep_file=True)
    assert res.ok and jobs.created == []
    assert xlsx.exists()


# ── po ───────────────────────────────────────────────────────────────────────

def _po(pid: str, grn: int = 5) -> dict:
    return {"purchase_order_id": pid, "status": "STATUS_CONFIRMED", "receiving_status": None,
            "value": 100.0, "total_quantity": 10, "pending_quantity": 10 - grn,
            "grn_quantity": grn, "expiry_date": dt.date(2026, 10, 20), "completed_date": None}


def _po_fakes(line_calls: list, still_lost: bool, export=None, stored=None):
    pos = [_po("P1"), _po("P2")]

    async def lines(_client, _token, ids):
        line_calls.append(list(ids))
        if len(line_calls) == 1:
            return {"P1": {}}, ["P2"]                     # P2 lost on the first pass
        return ({}, ["P2"]) if still_lost else ({"P2": {}}, [])

    return {
        "supply_session__get_token": _async(("tok", "brand-9")),
        "supply_storage__stored_po_fingerprints": _async(stored or {}),
        "supply_scraper__fetch_all_purchase_orders": _async(pos),
        "supply_scraper__fetch_all_po_lines": lines,
        "supply_parser__parse_po_lines": lambda raw, purchase_order_id: [
            {"purchase_order_id": purchase_order_id, "external_item_code": "S"}],
        "supply_storage__save_purchase_orders": _async(
            lambda _db, _t, p, i, _j: {"purchase_orders": len(p), "purchase_order_items": len(i)}),
        "_sync_export": export or _async(None),
    }


def test_po_lost_lines_recovered_on_recheck_complete_the_job():
    jobs, calls = _Jobs(), []
    with _patched(jobs, **_po_fakes(calls, still_lost=False)):
        [res] = _run(sales=False, ads=False, po=True)
    assert calls == [["P1", "P2"], ["P2"]]                 # only the lost one replayed
    assert res.ok and res.written == {"purchase_orders": 2, "purchase_order_items": 2}
    assert jobs.closed == [("success", 4)]


def test_po_lines_still_lost_fail_the_job_with_what_landed():
    jobs, calls = _Jobs(), []
    with _patched(jobs, **_po_fakes(calls, still_lost=True)):
        [res] = _run(sales=False, ads=False, po=True)
    assert not res.ok and res.lost == ["lines P2"]
    assert len(jobs.closed) == 1
    status, error, written = jobs.closed[0]
    assert status == "failed" and "P2" in error and written == 3   # 2 POs + P1's line


def test_po_export_failure_never_fails_the_section():
    jobs = _Jobs()

    async def export(*_a):
        raise RuntimeError("batch/list 500")

    # The real _sync_export swallows its own errors; prove it does.
    real = ir._sync_export
    fakes = _po_fakes([], still_lost=False)
    del fakes["_sync_export"]
    fakes["supply_scraper__submit_po_export"] = export
    with _patched(jobs, **fakes):
        [res] = _run(sales=False, ads=False, po=True)
    assert ir._sync_export is real
    assert res.ok and jobs.closed == [("success", 4)]


# ── the run ──────────────────────────────────────────────────────────────────

def test_a_failed_section_does_not_stop_the_next():
    jobs = _Jobs()
    fakes = _po_fakes([], still_lost=False)
    fakes["run_ads"] = _async(RuntimeError("signed call 403 after retries"))
    with _patched(jobs, **fakes):
        ads, po = _run(sales=False, ads=True, po=True)
    assert ads.name == "ads" and not ads.ok and "403" in ads.error
    assert po.name == "po" and po.ok


def test_missing_credentials_fail_every_section_without_a_job():
    jobs = _Jobs()
    with _patched(jobs, auth_store__get_credentials=_async(None)):
        results = _run()
    assert [r.name for r in results] == ["sales", "ads", "po"]
    assert all(not r.ok and "credentials" in r.error for r in results)
    assert jobs.created == []


def test_po_fetches_lines_only_for_new_or_changed_pos():
    jobs, calls = _Jobs(), []
    fakes = _po_fakes(calls, still_lost=False)
    pos = [_po("P1"), _po("P2", grn=8), _po("P3")]   # P2 received more since last run
    fakes["supply_scraper__fetch_all_purchase_orders"] = _async(pos)
    fp = ir.supply_storage.po_fingerprint
    # Stored: P1 and P2 as of the last run; P3 is new.
    fakes["supply_storage__stored_po_fingerprints"] = _async({"P1": fp(_po("P1")), "P2": fp(_po("P2"))})

    async def lines(_c, _t, ids):
        calls.append(list(ids))
        return {i: {} for i in ids}, []
    fakes["supply_scraper__fetch_all_po_lines"] = lines
    with _patched(jobs, **fakes):
        [res] = _run(sales=False, ads=False, po=True)
    assert calls == [["P2", "P3"]]                    # P1 unchanged -> no call
    assert res.ok and res.written == {"purchase_orders": 3, "purchase_order_items": 2}


def test_po_all_lines_fetches_every_po():
    jobs, calls = _Jobs(), []
    fakes = _po_fakes(calls, still_lost=False)
    fakes["supply_storage__stored_po_fingerprints"] = _async(AssertionError("must not read"))

    async def lines(_c, _t, ids):
        calls.append(list(ids))
        return {i: {} for i in ids}, []
    fakes["supply_scraper__fetch_all_po_lines"] = lines
    with _patched(jobs, **fakes):
        [res] = _run(sales=False, ads=False, po=True, po_all_lines=True)
    assert calls == [["P1", "P2"]] and res.ok


# ── backfill ─────────────────────────────────────────────────────────────────

def test_report_chunks_cover_the_range_at_most_31_days_each():
    chunks = ir.report_chunks(dt.date(2026, 7, 1), dt.date(2026, 9, 30))
    assert chunks[0] == (dt.date(2026, 7, 1), dt.date(2026, 7, 31))
    assert chunks[-1][1] == dt.date(2026, 9, 30)
    assert all((b - a).days + 1 <= 31 for a, b in chunks)
    assert all(nxt[0] - prev[1] == dt.timedelta(days=1) for prev, nxt in zip(chunks, chunks[1:]))
    assert ir.report_chunks(dt.date(2026, 9, 2), dt.date(2026, 9, 1)) == []


def test_backfill_splits_sales_and_hands_ads_and_po_the_range():
    jobs, calls = _Jobs(), []

    def rec(name):
        async def section(_t, _c, *args):
            calls.append((name, args))
            return ir.SectionResult(name)
        return section
    fakes = {"run_sales": rec("sales"), "run_ads": rec("ads"), "run_po": rec("po")}
    start, end = dt.date(2026, 7, 1), dt.date(2026, 9, 15)
    with _patched(jobs, **fakes):
        results = asyncio.run(ir.backfill(TENANT, start, end))
    assert [r.name for r in results] == ["sales", "sales", "sales", "ads", "po"]
    sales = [args[:2] for n, args in calls if n == "sales"]
    assert sales == [("2026-07-01", "2026-07-31"), ("2026-08-01", "2026-08-31"),
                     ("2026-09-01", "2026-09-15")]
    assert [args[:2] for n, args in calls if n == "ads"] == [(start, end)]
    assert [args[:2] for n, args in calls if n == "po"] == [(False, True)]   # every PO's lines


def test_a_failed_sales_chunk_does_not_stop_the_rest():
    jobs, seen = _Jobs(), []

    async def sales(_t, _c, a, *_):
        seen.append(a)
        if a == "2026-08-01":
            raise RuntimeError("report timed out")
        return ir.SectionResult("sales")
    with _patched(jobs, run_sales=sales):
        results = asyncio.run(ir.backfill(TENANT, dt.date(2026, 7, 1), dt.date(2026, 9, 15),
                                          ads=False, po=False))
    assert seen == ["2026-07-01", "2026-08-01", "2026-09-01"]
    assert [r.ok for r in results] == [True, False, True]
