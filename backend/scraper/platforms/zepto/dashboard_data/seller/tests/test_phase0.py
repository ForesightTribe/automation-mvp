"""Zepto private scrape — Phase 0 fixes (2026-10-05, zepto-cm-exp/plans/PLAN-private-scrape.md).

  P1   ads scrape the 7 days up to yesterday, not yesterday alone — a missed run heals
  P28  a blank ads day is "not ready" only if it is yesterday; an older one is saved as
       zeros, unless we already hold real spend for it (then the stored rows stay)
  P29  every run sweeps every city for the newest day (so a new tenant, and a new
       city, are found); older days ask the known + swept cities (also P21)
  P44  lost sales fetches are re-checked once and, if still lost, fail the run
  P46  an expired session in the PO path reaches the CLI as AuthError (exit 3)

No network, no database: the Zepto fetchers, the DB session and the savers are fakes
patched into cli.commands.scrape for the length of one test.

Run:  python -m scraper.platforms.zepto.dashboard_data.seller.tests.test_phase0
"""
import asyncio
import contextlib
import uuid
from datetime import date, timedelta

import typer

import cli.commands.scrape as sc
from platform_auth.errors import AuthError
from scraper.platforms.zepto.dashboard_data.seller import scraper as zscraper

TENANT = str(uuid.UUID("fa53082e-7e83-424d-aab9-086fe1b4c680"))
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


@contextlib.contextmanager
def _patched(**attrs):
    """Patch attributes of cli.commands.scrape, restoring them afterwards."""
    base = {
        "asyncio": _FastAsyncio(),
        "AsyncSessionLocal": _DB,
        "create_scrape_job": _async(lambda *a, **k: str(uuid.uuid4())),
        "complete_scrape_job": _async(lambda *a, **k: None),
        "fail_scrape_job": _async(lambda *a, **k: None),
    }
    base.update(attrs)
    saved = {k: getattr(sc, k) for k in base}
    for k, v in base.items():
        setattr(sc, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(sc, k, v)


def _async(fn):
    async def wrapper(*a, **k):
        return fn(*a, **k)
    return wrapper


def _days(*back: int) -> list[str]:
    return [(date.today() - timedelta(days=b)).isoformat() for b in back]


def _exit_code(coro) -> int | None:
    """Run a CLI coroutine; None if it returned, else the typer.Exit code."""
    try:
        asyncio.run(coro)
    except typer.Exit as e:      # typer bundles its own click — not click.exceptions.Exit
        return e.exit_code
    return None


# ── P1 · the ads window ──────────────────────────────────────────────────────

def test_ads_window_defaults_to_the_7_days_up_to_yesterday():
    days = sc._zepto_ads_days(None, None, today=TODAY)
    assert days == [f"2026-09-{d}" for d in range(28, 31)] + [f"2026-10-0{d}" for d in range(1, 5)]
    assert len(days) == sc._ZEPTO_ADS_DAYS == 7


def test_ads_window_counts_back_from_to_and_honours_from():
    assert sc._zepto_ads_days(None, "2026-09-28", today=TODAY)[0] == "2026-09-22"
    assert sc._zepto_ads_days("2026-09-19", "2026-09-21", today=TODAY) == [
        "2026-09-19", "2026-09-20", "2026-09-21"]
    assert sc._zepto_ads_days("2026-09-22", "2026-09-21", today=TODAY) == []


def test_blinkit_seller_window_is_unchanged():
    # _date_range is shared with Blinkit's seller scrape and must stay "yesterday".
    assert sc._date_range(None, None) == _days(1)


# ── P28 · what a blank ads day means ─────────────────────────────────────────

def test_blank_day_verdicts():
    assert sc._zepto_blank_ads_day("2026-10-04", 0, today=TODAY) == "not_ready"      # yesterday
    assert sc._zepto_blank_ads_day("2026-10-05", 0, today=TODAY) == "not_ready"      # today
    assert sc._zepto_blank_ads_day("2026-09-25", 4200.0, today=TODAY) == "keep_stored"
    assert sc._zepto_blank_ads_day("2026-09-25", 0, today=TODAY) == "zero"           # all paused


def _campaign(cid: int, *, blank: bool) -> dict:
    v = "-" if blank else "100"
    return {"campaign_id": cid, "brand_id": "brand-1", "campaign_name": f"C{cid}",
            "spend": v, "impressions": v, "clicks": v}


def test_ads_section_saves_a_paused_brands_old_days_as_zero():
    zero_day, kept_day, normal_day, newest = _days(4, 3, 2, 1)
    blank = {zero_day, kept_day, newest}
    tab_calls: list[str] = []
    saved: dict = {}

    async def fetch_campaigns(_c, _b, day, _to, _cat):
        return [_campaign(1, blank=day in blank), _campaign(2, blank=day in blank)]

    async def fetch_tab(_c, _b, day, _to, _view, _cat):
        tab_calls.append(day)
        return []

    async def save_ads(_db, rows, kws, prods, bds):
        saved["rows"] = rows
        return {"campaigns": len(rows)}

    async def stored_spend(_db, _t, day):
        return 5000.0 if day == kept_day else 0.0

    with _patched(
        zepto_discover_ids=_async(lambda *_: {"brand_id": "brand-1", "brand_name": "Brik Oven"}),
        zepto_fetch_ad_campaigns=fetch_campaigns,
        zepto_fetch_ads_tabular=fetch_tab,
        zepto_fetch_campaign_catalog=_async(lambda *_: {"campaigns": [], "failed": []}),
        zepto_save_ad_results=save_ads,
        _zepto_stored_ad_spend=stored_spend,
    ):
        code = _exit_code(sc._scrape_zepto_ads(
            TENANT, zero_day, newest, "all", True, storage_state=object()))

    assert code is None
    by_day = {}
    for r in saved["rows"]:
        by_day.setdefault(r["date"].isoformat(), []).append(r)
    assert sorted(by_day) == [zero_day, normal_day]          # newest skipped, kept day untouched
    assert all(r["spend"] == 0 for r in by_day[zero_day])    # genuine zeros, not a hole
    assert set(tab_calls) == {normal_day}                    # no tab calls for blank days
    assert len(tab_calls) == 6 * 3                           # 6 views x 3 categories


# ── P29 + P44 · the sales section ────────────────────────────────────────────

IDS = {
    "brand_id": "brand-1", "brand_name": "Sereko",
    "subcategory_ids": [], "subcategory_names": [],
    "city_ids": ["c1", "c2", "c3"],
    "city_list": [{"cityID": "c1", "cityName": "Mumbai"},
                  {"cityID": "c2", "cityName": "Delhi"},
                  {"cityID": "c3", "cityName": "Pune"}],
}
OVERVIEW = {"headers": {"gmv": {"value": 0}, "units": {"value": 0}}}


def _product(pv: str = "pv-1") -> dict:
    return {"productVariantId": pv, "productName": "Sereko Serum", "gmv": 500, "qtySold": 2}


def _sales_fakes(*, known: list[str], sells: set, fail: dict, product_fail: dict | None = None):
    """sells: cities with sales; fail: {(day, city): times to fail before answering}."""
    calls: list[tuple[str, tuple]] = []
    saved: dict = {}
    fail = dict(fail)
    product_fail = dict(product_fail or {})

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
        saved.update(products=prods, cities=cities)
        return len(prods) + len(cities)

    patches = dict(
        zepto_discover_ids=_async(lambda *_: IDS),
        zepto_fetch_sales_overview=_async(lambda *_: OVERVIEW),
        parse_zepto_sales_daily=lambda *a: [],
        zepto_fetch_product_performance=products,
        zepto_fetch_product_perf_by_city=by_city,
        zepto_save_sales_results=save,
        _zepto_known_cities=_async(lambda *_: list(known)),
    )
    return patches, calls, saved


def test_new_tenant_sweeps_every_city_once_then_uses_the_sellers():
    d1, d2, d3 = _days(3, 2, 1)
    patches, calls, saved = _sales_fakes(known=[], sells={"c2"}, fail={})
    with _patched(**patches):
        code = _exit_code(sc._scrape_zepto_sales(
            TENANT, d1, d3, False, True, storage_state=object()))

    assert code is None
    assert calls[0] == (d3, ("c1", "c2", "c3"))              # one sweep, last day only
    assert calls[1:] == [(d1, ("c2",)), (d2, ("c2",))]       # then just the seller
    assert sorted(r["date"].isoformat() for r in saved["cities"]) == [d1, d2, d3]


def test_every_run_sweeps_the_newest_day_and_catches_a_new_city():
    # c1 has sold before; c3 starts selling now. The newest day is swept in full, so
    # c3 is found on its first day and the older day is asked about both (P21).
    d1, d2 = _days(2, 1)
    patches, calls, saved = _sales_fakes(known=["c1"], sells={"c1", "c3"}, fail={})
    with _patched(**patches):
        assert _exit_code(sc._scrape_zepto_sales(
            TENANT, d1, d2, False, True, storage_state=object())) is None
    assert calls == [(d2, ("c1", "c2", "c3")), (d1, ("c1", "c3"))]
    assert len(saved["cities"]) == 4


def test_all_cities_sweeps_every_day():
    d1, d2 = _days(2, 1)
    patches, calls, _ = _sales_fakes(known=["c1"], sells={"c1"}, fail={})
    with _patched(**patches):
        assert _exit_code(sc._scrape_zepto_sales(
            TENANT, d1, d2, True, True, storage_state=object())) is None
    assert calls == [(d1, ("c1", "c2", "c3")), (d2, ("c1", "c2", "c3"))]


def test_a_city_that_fails_once_is_recovered_and_the_run_passes():
    d1, d2 = _days(2, 1)
    patches, calls, saved = _sales_fakes(known=["c1", "c2"], sells={"c1", "c2"},
                                         fail={(d1, "c1"): 1})
    with _patched(**patches):
        code = _exit_code(sc._scrape_zepto_sales(
            TENANT, d1, d2, False, True, storage_state=object()))
    assert code is None
    assert (d1, ("c1",)) in calls                            # the re-check
    assert len(saved["cities"]) == 4                         # 2 cities x 2 days, none missing


def test_lost_sales_fetches_fail_the_run_after_saving_what_came_back():
    d1, d2 = _days(2, 1)
    patches, _, saved = _sales_fakes(known=["c1", "c2"], sells={"c1", "c2"},
                                     fail={(d2, "c2"): 99}, product_fail={d1: 99})
    with _patched(**patches):
        code = _exit_code(sc._scrape_zepto_sales(
            TENANT, d1, d2, False, True, storage_state=object()))
    assert code == 1                                         # used to exit 0
    assert len(saved["cities"]) == 3                         # the rest was still saved
    assert [r["period_start"].isoformat() for r in saved["products"]] == [d2]


def test_auth_error_in_sales_is_not_swallowed():
    d1 = _days(1)[0]
    patches, _, _ = _sales_fakes(known=["c1"], sells={"c1"}, fail={})

    async def dead(*_a, **_k):
        raise AuthError("re-login exhausted")

    patches["zepto_fetch_product_performance"] = dead
    with _patched(**patches):
        try:
            asyncio.run(sc._scrape_zepto_sales(TENANT, d1, d1, False, True, storage_state=object()))
        except AuthError:
            return
    raise AssertionError("AuthError was swallowed")


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
    """Answers per city id found in the request params; 'boom' cities 500,
    'gone' cities raise AuthError."""

    def __init__(self, boom=(), gone=()):
        self.boom, self.gone = set(boom), set(gone)

    async def request(self, _method, _path, params=None, **_k):
        city = (params or {}).get("cityIds")
        if city in self.gone:
            raise AuthError("session gone")
        if city in self.boom:
            return _Resp(500, {})
        return _Resp(200, {"data": {"data": [_product()]}})


def test_by_city_fetcher_reports_failed_cities():
    failed: list[str] = []
    with _patched():
        zscraper.asyncio, real = _FastAsyncio(), zscraper.asyncio
        try:
            out = asyncio.run(zscraper.fetch_product_performance_by_city(
                _Client(boom={"c2"}), "2026-10-01", "2026-10-01", IDS, ["c1", "c2"],
                failed=failed))
        finally:
            zscraper.asyncio = real
    assert list(out) == ["c1"] and failed == ["c2"]


def test_by_city_fetcher_and_po_items_let_auth_errors_through():
    for coro in (
        zscraper.fetch_product_performance_by_city(
            _Client(gone={"c1"}), "2026-10-01", "2026-10-01", IDS, ["c1"]),
        zscraper.fetch_po_items(_GoneClient(), ["po-1", "po-2"]),
    ):
        try:
            asyncio.run(coro)
        except AuthError:
            continue
        raise AssertionError("AuthError was swallowed")


class _GoneClient:
    async def request(self, *_a, **_k):
        raise AuthError("session gone")


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} passed")
