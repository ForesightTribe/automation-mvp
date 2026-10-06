"""Zepto private scrape — the run (seller/run.py), 2026-10-05.

What each section does with what Zepto gives back, and what it records:

  P1   ads scrape the 3 days up to yesterday, not yesterday alone (7 until P54)
  P28  a blank ads day is "not ready" only if it is yesterday; an older one is saved as
       zeros, unless we already hold real spend for it (then the stored rows stay)
  P29  the city split sweeps every city for the newest day (a new tenant and a new
       city are found); older days ask the known + swept cities (also P21)
  P35  a section that lost fetches marks its scrape_jobs row FAILED, with the rows
       that did land — it used to say success and then exit 1
  P44  lost sales fetches are re-checked once and, if still lost, fail the section
  P45  "Zepto has not computed this day yet" trims the window instead of failing it
  P46  an expired session reaches the caller as AuthError (exit 3), from every section

No network, no database: the fetchers, the DB session and the savers are fakes,
patched in for the length of one test.

Run:  python -m scraper.platforms.zepto.dashboard_data.seller.tests.test_run
"""
import asyncio
import contextlib
import uuid
from datetime import date, timedelta

from platform_auth.errors import AuthError
from scraper.platforms.zepto.dashboard_data.seller import run as zr
from scraper.platforms.zepto.dashboard_data.seller import scraper as zs
from scraper.platforms.zepto.dashboard_data.seller import storage as zst

TENANT = "fa53082e-7e83-424d-aab9-086fe1b4c680"
TODAY = date(2026, 10, 5)


# ── fakes ────────────────────────────────────────────────────────────────────

class _FastAsyncio:
    """The real asyncio with sleep() made instant, so retry gaps cost nothing."""

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


def _async(fn):
    async def wrapper(*a, **k):
        return fn(*a, **k)
    return wrapper


class _Jobs:
    """Records what each section wrote to its scrape_jobs row."""

    def __init__(self):
        self.closed: list[tuple] = []

    async def create(self, *_a, **_k):
        return str(uuid.uuid4())

    async def complete(self, _db, _job, records=0):
        self.closed.append(("success", records))

    async def fail(self, _db, _job, error, records_written=None):
        self.closed.append(("failed", error, records_written))


@contextlib.contextmanager
def _patched(jobs: _Jobs | None = None, run_attrs: dict | None = None, **module_attrs):
    """Patch run.py's own names plus attributes of the scraper / storage modules
    (given as 'zs__name' / 'zst__name'), restoring all of them afterwards."""
    jobs = jobs or _Jobs()
    targets = {
        (zr, "asyncio"): _FastAsyncio(),
        (zr, "AsyncSessionLocal"): _DB,
        (zr, "create_scrape_job"): jobs.create,
        (zr, "complete_scrape_job"): jobs.complete,
        (zr, "fail_scrape_job"): jobs.fail,
    }
    for k, v in (run_attrs or {}).items():
        targets[(zr, k)] = v
    for k, v in module_attrs.items():
        mod, name = k.split("__", 1)
        targets[({"zs": zs, "zst": zst}[mod], name)] = v
    saved = {key: getattr(*key) for key in targets}
    for (mod, name), v in targets.items():
        setattr(mod, name, v)
    try:
        yield jobs
    finally:
        for (mod, name), v in saved.items():
            setattr(mod, name, v)


def _days(*back: int) -> list[str]:
    return [(date.today() - timedelta(days=b)).isoformat() for b in back]


def _go(coro):
    return asyncio.run(coro)


# ── P1 · the ads window ──────────────────────────────────────────────────────

def test_ads_window_defaults_to_the_3_days_up_to_yesterday():
    days = zr.ads_window(None, None, today=TODAY)
    assert days == ["2026-10-02", "2026-10-03", "2026-10-04"]
    assert len(days) == zr.ADS_DAYS == 3


def test_ads_window_counts_back_from_to_and_honours_from():
    assert zr.ads_window(None, "2026-09-28", today=TODAY)[0] == "2026-09-26"
    assert zr.ads_window("2026-09-19", "2026-09-21", today=TODAY) == [
        "2026-09-19", "2026-09-20", "2026-09-21"]
    assert zr.ads_window("2026-09-22", "2026-09-21", today=TODAY) == []


# ── P28 · what a blank ads day means ─────────────────────────────────────────

def test_blank_day_verdicts():
    assert zr.blank_ads_day("2026-10-04", 0, today=TODAY) == "not_ready"      # yesterday
    assert zr.blank_ads_day("2026-10-05", 0, today=TODAY) == "not_ready"      # today
    assert zr.blank_ads_day("2026-09-25", 4200.0, today=TODAY) == "keep_stored"
    assert zr.blank_ads_day("2026-09-25", 0, today=TODAY) == "zero"           # all paused


def _campaign(cid: int, *, blank: bool) -> dict:
    v = "-" if blank else "100"
    return {"campaign_id": cid, "brand_id": "brand-1", "campaign_name": f"C{cid}",
            "spend": v, "impressions": v, "clicks": v}


def _ads_fakes(blank_days: set, stored: dict, saved: dict, tab_calls: list, *, fail_tabs=None):
    fail_tabs = dict(fail_tabs or {})

    async def fetch_campaigns(_c, _b, day, _to, _cat):
        return [_campaign(1, blank=day in blank_days), _campaign(2, blank=day in blank_days)]

    async def fetch_tab(_c, _b, day, _to, view, cat):
        tab_calls.append(day)
        key = (day, view, cat)
        if fail_tabs.get(key, 0) > 0:
            fail_tabs[key] -= 1
            raise RuntimeError("500 from ads-bff")
        return []

    async def save_ads(_db, rows, kws, prods, bds):
        saved["rows"] = rows
        return {"campaigns": len({r["upsert_key"] for r in rows})}

    return dict(
        zs__discover_ids=_async(lambda *_: {"brand_id": "brand-1", "brand_name": "Brik Oven"}),
        zs__fetch_ad_campaigns=fetch_campaigns,
        zs__fetch_ads_tabular=fetch_tab,
        zs__fetch_campaign_catalog=_async(lambda *_: {"campaigns": [], "failed": []}),
        zst__save_ad_results=save_ads,
        zst__stored_ad_spend=_async(lambda _db, _t, day: stored.get(day, 0.0)),
    )


def test_ads_saves_a_paused_brands_old_days_as_zero():
    zero_day, kept_day, normal_day, newest = _days(4, 3, 2, 1)
    saved, tab_calls = {}, []
    with _patched(**_ads_fakes({zero_day, kept_day, newest}, {kept_day: 5000.0}, saved, tab_calls)) as jobs:
        res = _go(zr.run_ads(object(), TENANT, zero_day, newest, "all", True))

    assert res.ok and jobs.closed == [("success", 4)]          # 2 campaigns x 2 saved days
    by_day: dict = {}
    for r in saved["rows"]:
        by_day.setdefault(r["date"].isoformat(), []).append(r)
    assert sorted(by_day) == [zero_day, normal_day]           # newest skipped, kept day untouched
    assert all(r["spend"] == 0 for r in by_day[zero_day])     # genuine zeros, not a hole
    assert res.not_ready == [newest]
    assert set(tab_calls) == {normal_day} and len(tab_calls) == 6 * 3   # no tabs for blank days


def test_ads_lost_tab_fails_the_section_and_its_scrape_job():
    d1 = _days(2)[0]
    saved, tab_calls = {}, []
    fakes = _ads_fakes(set(), {}, saved, tab_calls,
                       fail_tabs={(d1, "keyword_table", "sponsored_products"): 99,
                                  (d1, "city_table", "sponsored_brands"): 1})
    with _patched(**fakes) as jobs:
        res = _go(zr.run_ads(object(), TENANT, d1, d1, "all", True))
    assert not res.ok
    assert res.lost == [f"{d1[5:]} products keywords"]
    assert res.recovered == [f"{d1[5:]} brands city"]
    status, error, records = jobs.closed[-1]
    assert status == "failed" and error.startswith("partial: 1 fetch(es) lost") and records == 2


def test_ads_auth_error_saves_what_came_back_then_propagates():
    d1, d2 = _days(2, 1)
    saved, tab_calls = {}, []
    fakes = _ads_fakes(set(), {}, saved, tab_calls)
    real = fakes["zs__fetch_ad_campaigns"]

    async def dies_on_d2(c, b, day, to, cat):
        if day == d2:
            raise AuthError("re-login exhausted")
        return await real(c, b, day, to, cat)

    fakes["zs__fetch_ad_campaigns"] = dies_on_d2
    with _patched(**fakes) as jobs:
        try:
            _go(zr.run_ads(object(), TENANT, d1, d2, "all", True))
        except AuthError:
            assert len(saved["rows"]) == 2                    # d1 was saved
            assert jobs.closed == [("failed", "auth_expired", 2)]
            return
    raise AssertionError("AuthError was swallowed")


# ── sales ────────────────────────────────────────────────────────────────────

IDS = {
    "brand_id": "brand-1", "brand_name": "Sereko",
    "subcategory_ids": [], "subcategory_names": [],
    "city_ids": ["c1", "c2", "c3"],
    "city_list": [{"cityID": "c1", "cityName": "Mumbai"},
                  {"cityID": "c2", "cityName": "Delhi"},
                  {"cityID": "c3", "cityName": "Pune"}],
}


def _overview(start: str, end: str) -> dict:
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    labels = [(d0 + timedelta(days=i)).strftime("%d %b").lstrip("0") for i in range((d1 - d0).days + 1)]
    pts = [{"key": k, "Sereko": 1} for k in labels]
    return {"headers": {"gmv": {"value": 0}, "units": {"value": 0}},
            "metrics": {"gmv": {"data": pts}, "units": {"data": pts}}}


def _product(pv: str = "pv-1") -> dict:
    return {"productVariantId": pv, "productName": "Sereko Serum", "gmv": 500, "qtySold": 2}


def _sales_fakes(*, known: list[str], sells: set, fail: dict | None = None,
                 product_fail: dict | None = None, not_ready: set | None = None):
    """sells: cities with sales; fail: {(day, city): times to fail before answering};
    not_ready: window END dates for which the overview says NoDataYet."""
    calls: list[tuple[str, tuple]] = []
    saved: dict = {}
    fail, product_fail, not_ready = dict(fail or {}), dict(product_fail or {}), set(not_ready or ())

    async def overview(_c, start, end, _ids):
        if end in not_ready:
            raise zs.NoDataYet(f"{end} not computed")
        return _overview(start, end)

    async def by_city(_c, day, _to, _ids, cities, failed=None):
        calls.append((day, tuple(cities)))
        out = {}
        for city in cities:
            if fail.get((day, city), 0) > 0:
                fail[(day, city)] -= 1
                failed.append(city)
                continue
            if city in sells:
                out[city] = [_product()]
        return out

    async def products(_c, day, _to, _ids):
        if product_fail.get(day, 0) > 0:
            product_fail[day] -= 1
            raise RuntimeError("500 from product-performance")
        return [_product()]

    async def save(_db, daily, prods, cities):
        saved.update(daily=daily, products=prods, cities=cities)
        return len(daily) + len(prods) + len(cities)

    patches = dict(
        zs__discover_ids=_async(lambda *_: IDS),
        zs__fetch_sales_overview=overview,
        zs__fetch_product_performance=products,
        zs__fetch_product_performance_by_city=by_city,
        zst__save_sales_results=save,
        zst__known_cities=_async(lambda *_: list(known)),
    )
    return patches, calls, saved


def _sales(d_from, d_to, *, all_cities=False, **fakes):
    patches, calls, saved = _sales_fakes(**fakes)
    with _patched(**patches) as jobs:
        res = _go(zr.run_sales(object(), TENANT, d_from, d_to, all_cities, True))
    return res, calls, saved, jobs


def test_new_tenant_sweeps_every_city_once_then_uses_the_sellers():
    d1, d2, d3 = _days(3, 2, 1)
    res, calls, saved, _ = _sales(d1, d3, known=[], sells={"c2"})
    assert res.ok
    assert calls[0] == (d3, ("c1", "c2", "c3"))               # one sweep, newest day only
    assert calls[1:] == [(d1, ("c2",)), (d2, ("c2",))]        # then just the seller
    assert sorted(r["date"].isoformat() for r in saved["cities"]) == [d1, d2, d3]


def test_every_run_sweeps_the_newest_day_and_catches_a_new_city():
    # c1 has sold before; c3 starts selling now (P21).
    d1, d2 = _days(2, 1)
    res, calls, saved, _ = _sales(d1, d2, known=["c1"], sells={"c1", "c3"})
    assert calls == [(d2, ("c1", "c2", "c3")), (d1, ("c1", "c3"))]
    assert len(saved["cities"]) == 4


def test_all_cities_sweeps_every_day():
    d1, d2 = _days(2, 1)
    _, calls, _, _ = _sales(d1, d2, all_cities=True, known=["c1"], sells={"c1"})
    assert calls == [(d1, ("c1", "c2", "c3")), (d2, ("c1", "c2", "c3"))]


def test_a_city_that_fails_once_is_recovered():
    d1, d2 = _days(2, 1)
    res, calls, saved, jobs = _sales(d1, d2, known=["c1", "c2"], sells={"c1", "c2"},
                                     fail={(d1, "c1"): 1})
    assert res.ok and res.recovered == [f"Mumbai {d1}"]
    assert (d1, ("c1",)) in calls and len(saved["cities"]) == 4
    assert jobs.closed[-1][0] == "success"


def test_lost_sales_fetches_fail_the_section_after_saving_what_came_back():
    d1, d2 = _days(2, 1)
    res, _, saved, jobs = _sales(d1, d2, known=["c1", "c2"], sells={"c1", "c2"},
                                 fail={(d2, "c2"): 99}, product_fail={d1: 99})
    assert not res.ok and sorted(res.lost) == sorted([f"products {d1}", f"Delhi {d2}"])
    assert len(saved["cities"]) == 3                          # the rest was still saved
    assert [r["period_start"].isoformat() for r in saved["products"]] == [d2]
    status, error, records = jobs.closed[-1]
    assert status == "failed" and "partial" in error and records == len(saved["daily"]) + 1 + 3


def test_not_computed_yet_trims_the_window_instead_of_failing():
    d1, d2 = _days(2, 1)
    res, _, saved, jobs = _sales(d1, d2, known=["c1"], sells={"c1"}, not_ready={d2})
    assert res.ok and res.not_ready == [d2] and res.window == f"{d1}..{d1}"
    assert [r["date"].isoformat() for r in saved["daily"]] == [d1]
    assert jobs.closed[-1][0] == "success"


def test_nothing_computed_yet_is_not_a_failure():
    d1 = _days(1)[0]
    res, calls, saved, jobs = _sales(d1, d1, known=["c1"], sells={"c1"}, not_ready={d1})
    assert res.ok and res.not_ready == [d1] and calls == [] and saved == {}
    assert jobs.closed == [("success", 0)]


def test_auth_error_in_sales_is_recorded_and_propagates():
    d1 = _days(1)[0]
    patches, _, _ = _sales_fakes(known=["c1"], sells={"c1"})

    async def dead(*_a, **_k):
        raise AuthError("re-login exhausted")

    patches["zs__fetch_product_performance"] = dead
    with _patched(**patches) as jobs:
        try:
            _go(zr.run_sales(object(), TENANT, d1, d1, False, True))
        except AuthError:
            assert jobs.closed == [("failed", "auth_expired", None)]
            return
    raise AssertionError("AuthError was swallowed")


# ── PO ───────────────────────────────────────────────────────────────────────

def test_po_auth_error_propagates_and_a_flaky_endpoint_does_not():
    async def boom(*_a, **_k):
        raise RuntimeError("500 from asn/filter")

    async def dead(*_a, **_k):
        raise AuthError("session gone")

    base = dict(zs__fetch_pos=_async(lambda *_: []), zs__fetch_grns=_async(lambda *_: []),
                zs__fetch_po_items=_async(lambda *_: {}),
                zst__save_po_results=_async(lambda *a: {"pos": 0}))
    with _patched(**base, zs__fetch_asns=boom) as jobs:
        res = _go(zr.run_po(object(), TENANT, 30, True))
    assert res.lost == ["asn/filter"] and not res.ok and jobs.closed[-1][0] == "failed"

    with _patched(**base, zs__fetch_asns=dead) as jobs:
        try:
            _go(zr.run_po(object(), TENANT, 30, True))
        except AuthError:
            assert jobs.closed == [("failed", "auth_expired", None)]
            return
    raise AssertionError("AuthError was swallowed (P46)")


# ── run(): one login, sections isolated ──────────────────────────────────────

def test_run_isolates_a_failing_section_and_stops_on_auth():
    order: list[str] = []

    async def sales(*_a, **_k):
        order.append("sales")
        raise RuntimeError("boom")

    async def po(*_a, **_k):
        order.append("po")
        return zr.SectionResult("po")

    async def ads(*_a, **_k):
        order.append("ads")
        raise AuthError("gone")

    setup = _async(lambda *_: (None, None, object()))
    reported: list = []
    with _patched(run_attrs={"setup": setup, "run_sales": sales, "run_po": po, "run_ads": ads}):
        try:
            _go(zr.run(TENANT, on_section=reported.append))
        except AuthError:
            pass
        else:
            raise AssertionError("AuthError was swallowed")
    assert order == ["sales", "po", "ads"]                    # sales' failure did not stop po
    assert [(r.name, r.ok) for r in reported] == [("sales", False), ("po", True)]


# ── the log (scraper/utils/run_log.py — "Steps" level, 2026-10-06) ───────────

@contextlib.contextmanager
def _captured_log():
    from loguru import logger
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(m.rstrip("\n")), level="INFO",
                      format="{level}|{extra[tag]}|{message}")
    try:
        yield lines
    finally:
        logger.remove(sink)


def test_a_run_logs_tagged_steps_not_requests():
    d1, d2 = _days(2, 1)
    sales_patches, _, _ = _sales_fakes(known=["c1"], sells={"c1"})
    saved, tab_calls = {}, []
    ads_patches = _ads_fakes(set(), {}, saved, tab_calls)
    setup = _async(lambda *_: (None, None, object()))
    fakes = {**sales_patches, **ads_patches, "zs__discover_ids": _async(lambda *_: IDS)}
    with _captured_log() as lines, _patched(run_attrs={"setup": setup}, **fakes):
        _go(zr.run(TENANT, po=False, date_from=d1, date_to=d2))

    tags = {line.split("|")[1] for line in lines}
    assert tags <= {f"zepto·{TENANT[:8]}", f"zepto·{TENANT[:8]}·sales", f"zepto·{TENANT[:8]}·ads"}
    assert not any(line.startswith(("WARNING", "ERROR")) for line in lines)   # nothing was lost
    # Steps, not requests: 2 days x 18 analytics calls happened, but the ads section
    # logs one line per day plus a handful of section lines.
    assert len(tab_calls) == 2 * 18
    ads_lines = [line for line in lines if line.split("|")[1].endswith("·ads")]
    assert len(ads_lines) <= 6, ads_lines
    assert lines[0].endswith("start · sales, ads") and "finished · ok" in lines[-1]


def test_a_lost_fetch_is_one_warning():
    d1 = _days(2)[0]
    saved, tab_calls = {}, []
    fakes = _ads_fakes(set(), {}, saved, tab_calls,
                       fail_tabs={(d1, "keyword_table", "sponsored_products"): 99})
    with _captured_log() as lines, _patched(**fakes):
        _go(zr.run_ads(object(), TENANT, d1, d1, "all", True))
    warnings = [line for line in lines if line.startswith("WARNING")]
    assert len(warnings) == 1 and "products keywords" in warnings[0]


# ── the fetchers ─────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status: int, body: dict):
        self.status_code, self._body = status, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


class _Client:
    """Answers per city id in the request params; 'boom' cities 500, 'gone' raise AuthError."""

    def __init__(self, boom=(), gone=()):
        self.boom, self.gone = set(boom), set(gone)

    async def request(self, _method, _path, params=None, **_k):
        city = (params or {}).get("cityIds")
        if city in self.gone:
            raise AuthError("session gone")
        if city in self.boom:
            return _Resp(500, {})
        return _Resp(200, {"data": {"data": [_product()]}})


class _GoneClient:
    async def request(self, *_a, **_k):
        raise AuthError("session gone")


@contextlib.contextmanager
def _fast_fetchers():
    real = zs.asyncio
    zs.asyncio = _FastAsyncio()
    try:
        yield
    finally:
        zs.asyncio = real


def test_by_city_fetcher_reports_failed_cities():
    failed: list[str] = []
    with _fast_fetchers():
        out = _go(zs.fetch_product_performance_by_city(
            _Client(boom={"c2"}), "2026-10-01", "2026-10-01", IDS, ["c1", "c2"], failed=failed))
    assert list(out) == ["c1"] and failed == ["c2"]


def test_by_city_fetcher_and_po_items_let_auth_errors_through():
    for coro in (
        zs.fetch_product_performance_by_city(_Client(gone={"c1"}), "2026-10-01", "2026-10-01",
                                             IDS, ["c1"]),
        zs.fetch_po_items(_GoneClient(), ["po-1", "po-2"]),
    ):
        try:
            _go(coro)
        except AuthError:
            continue
        raise AssertionError("AuthError was swallowed")


class _PagedClient:
    """product-performance with `n` selling products, served `limit` at a time.
    `ignore_offset` mimics an API that repeats page 1."""

    def __init__(self, n: int, ignore_offset: bool = False):
        self.rows = [_product(f"pv{i}") for i in range(n)]
        self.ignore_offset, self.calls = ignore_offset, 0

    async def request(self, _method, _path, params=None, **_k):
        self.calls += 1
        off = 0 if self.ignore_offset else params["offset"]
        return _Resp(200, {"data": {"data": self.rows[off:off + params["limit"]]}})


def test_product_performance_pages_only_when_a_page_is_full():
    with _fast_fetchers():
        c = _PagedClient(12)
        assert len(_go(zs.fetch_product_performance(c, "2026-10-01", "2026-10-01", IDS))) == 12
        assert c.calls == 1                                   # a normal day: one call
        c = _PagedClient(120)
        assert len(_go(zs.fetch_product_performance(c, "2026-10-01", "2026-10-01", IDS))) == 120
        assert c.calls == 3                                   # 50 + 50 + 20 (P47)
        c = _PagedClient(50, ignore_offset=True)
        assert len(_go(zs.fetch_product_performance(c, "2026-10-01", "2026-10-01", IDS))) == 50
        assert c.calls == 2                                   # repeated page -> stop


def test_retry_call_repeats_only_what_it_is_told_to():
    from scraper.utils import retry as r
    real, r.asyncio = r.asyncio, _FastAsyncio()
    try:
        tries = []

        async def flaky():
            tries.append(1)
            if len(tries) < 3:
                raise RuntimeError("500")
            return "ok"

        assert _go(r.retry_call(flaky, waits=(1, 1, 1), retry_if=lambda e: True, label="x")) == "ok"
        assert len(tries) == 3

        tries.clear()

        async def always():
            tries.append(1)
            raise RuntimeError("500")

        for retry_if, expected in ((lambda e: False, 1), (lambda e: True, 3)):
            tries.clear()
            try:
                _go(r.retry_call(always, waits=(1, 1), retry_if=retry_if, label="x"))
            except RuntimeError:
                pass
            assert len(tries) == expected                     # 1 try + one per wait
    finally:
        r.asyncio = real


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} passed")
