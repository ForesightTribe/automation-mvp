"""Zepto private scrape — the run: one login, then sales, PO and ads.

Moved out of `cli/commands/scrape.py` in Phase 1 (2026-10-05,
zepto-cm-exp/plans/PLAN-private-scrape.md §6). The CLI keeps flags and exit codes;
everything that fetches, parses, retries, saves and LOGS is here, so it can be tested
without a terminal and new work (per-campaign keyword detail) has a place to go.

Shape (same four files as Blinkit's seller scrape, plus this one):
    endpoints.py   URLs and constants
    scraper.py     HTTP only
    parser.py      raw -> rows, pure
    storage.py     upserts, and the two reads the run needs
    run.py         the loops — this file

Each section returns a `SectionResult`. One result drives the exit code (anything lost
-> 1, auth gone -> 3) and the `scrape_jobs` row (P35: a run that lost fetches used to
complete its row as success and then exit 1).

Logging follows scraper/utils/run_log.py: one INFO line per step, tagged
`zepto·<tenant>·<section>`; per-request detail at DEBUG.

Zepto has ONE console behind ONE login, so it is one job and one command, with every
section on a single session — each Zepto login logs the client's own dashboard out.
"""
import asyncio
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Awaitable, Callable

import httpx

from app.core.database import AsyncSessionLocal
from app.utils.logger import logger
from campaign_manager.marketplaces.zepto.transport import setup
from platform_auth.errors import AuthError
from scraper.platforms.zepto.dashboard_data.seller import endpoints as ep
from scraper.platforms.zepto.dashboard_data.seller import parser as zp
from scraper.platforms.zepto.dashboard_data.seller import scraper as zs
from scraper.platforms.zepto.dashboard_data.seller import storage as zst
from scraper.utils.jobs import complete_scrape_job, create_scrape_job, fail_scrape_job
from scraper.utils.run_log import rupees, short, tag, tenant_slug, took

# Gap between per-day calls. Paces multi-day windows: a burst of back-to-back requests
# is the kind of pattern this site's WAF reacts to.
DAY_GAP_S = 1.5

# How long a section waits before replaying the fetches it lost. Longer than the
# fetchers' own 5xx ladders on purpose: by the time a fetch has exhausted those, the
# fault is not a two-second blip. Only what fails the replay too fails the run.
RECHECK_WAIT_S = 20

# Default windows (P37). Ads: the 3 days up to yesterday — more than one, so a failed
# or interrupted run heals on the next run (P1: one day lost every missed day for good);
# not 7, because each ads day costs ~19 calls / ~1m50s and a 7-day window made a run
# ~17 min (P54, Deepansh 2026-10-06). A day missed for 3 runs in a row, or attribution
# revised after 3 days, needs a manual `--from` re-run. Sales: 8 days, Zepto recomputes
# days late. PO: 30 days back through TODAY — POs are forward-looking, an order raised
# today expires in ~3 weeks.
ADS_DAYS = 3
SALES_DAYS = 8
PO_DAYS = 30

Lost = list[tuple[str, Callable[[], Awaitable[None]]]]


@dataclass
class SectionResult:
    """What one section did."""
    name: str
    window: str = ""
    saved: bool = True
    written: dict[str, int] = field(default_factory=dict)
    lost: list[str] = field(default_factory=list)       # failed twice -> the run fails
    recovered: list[str] = field(default_factory=list)  # failed once, fine on re-check
    not_ready: list[str] = field(default_factory=list)  # Zepto has not computed it yet
    error: str | None = None                            # the section aborted

    @property
    def ok(self) -> bool:
        return self.error is None and not self.lost


def _days(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def _md(day: str) -> str:
    """'2026-09-29' -> '09-29' — the year is noise in a daily log."""
    return day[5:]


class _Recoveries:
    """The client's own recovery counters, read as a difference across a section, so
    the summary can say "3 WAF renewals" instead of logging each one."""

    def __init__(self, client):
        self.client = client
        self.remint0 = getattr(client, "remint_count", 0)
        self.reauth0 = getattr(client, "reauth_count", 0)

    def note(self) -> str:
        bits = []
        remints = getattr(self.client, "remint_count", 0) - self.remint0
        reauths = getattr(self.client, "reauth_count", 0) - self.reauth0
        if remints:
            bits.append(f"{remints} WAF renewal(s)")
        if reauths:
            bits.append(f"{reauths} re-login(s)")
        return (" · " + " · ".join(bits)) if bits else ""


async def _recheck(lost: Lost, recovered: list[str]) -> Lost:
    """Replay every lost fetch once, after RECHECK_WAIT_S. Returns what is still lost.
    An AuthError is not a lost fetch — the session is gone — so it propagates."""
    if not lost:
        return lost
    logger.info(f"re-check · {len(lost)} lost fetch(es) in {RECHECK_WAIT_S}s")
    await asyncio.sleep(RECHECK_WAIT_S)
    still: Lost = []
    for label, fn in lost:
        try:
            await fn()
        except AuthError:
            raise
        except Exception as e:
            logger.debug(f"{label} failed on re-check: {e}")
            still.append((label, fn))
        else:
            recovered.append(label)
        await asyncio.sleep(DAY_GAP_S)
    logger.info(f"re-check · {len(lost) - len(still)} of {len(lost)} recovered")
    return still


async def _finish(db, job_id: str, res: SectionResult, recoveries: _Recoveries) -> None:
    """Close the `scrape_jobs` row from the result (P35) and log the section's last line:
    success only when nothing was lost; otherwise failed, naming what was lost, with the
    rows that DID land."""
    total = sum(res.written.values())
    if res.lost:
        await fail_scrape_job(
            db, job_id, f"partial: {len(res.lost)} fetch(es) lost — {short(res.lost)}",
            records_written=total,
        )
        logger.warning(f"lost after re-check: {short(res.lost)}")
    else:
        await complete_scrape_job(db, job_id, total)
    saved = f"saved {total:,} rows" if res.saved else "not saved (--no-save)"
    logger.info(f"done · {saved}{recoveries.note()}")


# ── the run ──────────────────────────────────────────────────────────────────

async def run(
    tenant_id: str,
    *,
    sales: bool = True,
    po: bool = True,
    ads: bool = True,
    date_from: str | None = None,
    date_to: str | None = None,
    po_days_back: int = PO_DAYS,
    category: str = "all",
    all_cities: bool = False,
    save: bool = True,
    on_section: Callable[[SectionResult], None] | None = None,
) -> list[SectionResult]:
    """One login, then each chosen section in turn on the same client.

    A section that fails does not stop the others — one flaky endpoint costs its own
    data, not the run. An `AuthError` does stop everything: the session is gone and no
    later section can work either; the CLI turns it into exit 3 (`auth_expired`).
    """
    started = time.monotonic()
    async with AsyncSessionLocal() as db:
        slug = await tenant_slug(db, tenant_id)
    wanted = [n for n, w in (("sales", sales), ("po", po), ("ads", ads)) if w]

    with tag("zepto", slug):
        logger.info(f"start · {', '.join(wanted)}")
        # ensure() the session, then mint the WAF token. The client recovers PER CALL
        # (401 -> re-login, 202/429 -> re-mint): the account is shared and on 2026-09-01
        # the session was evicted three times in ten minutes.
        _, _, client = await setup(str(tenant_id))
        logger.info("session ready")

        plan = {
            "sales": lambda: run_sales(client, tenant_id, date_from, date_to, all_cities, save),
            "po": lambda: run_po(client, tenant_id, po_days_back, save),
            "ads": lambda: run_ads(client, tenant_id, date_from, date_to, category, save),
        }
        results: list[SectionResult] = []
        for name in wanted:
            with tag("zepto", slug, name):
                try:
                    res = await plan[name]()
                except AuthError:
                    raise
                except Exception as e:             # sections catch their own; belt and braces
                    res = SectionResult(name, error=str(getattr(e, "orig", None) or e))
                if res.error:
                    # ERROR, not WARNING: the alert matches severity>=ERROR.
                    logger.error(f"FAILED · {res.error}")
            results.append(res)
            if on_section:
                on_section(res)

        failed = [r.name for r in results if not r.ok]
        if failed:
            logger.error(f"finished · FAILED: {', '.join(failed)} · {took(started)}")
        else:
            logger.info(f"finished · ok · {took(started)}")
    return results


# ── sales ────────────────────────────────────────────────────────────────────

async def run_sales(client, tenant_id: str, date_from: str | None, date_to: str | None,
                    all_cities: bool, save: bool) -> SectionResult:
    """Brand totals per day, per-product sales per day, and the per-city split."""
    yesterday = date.today() - timedelta(days=1)
    end = date.fromisoformat(date_to) if date_to else yesterday
    start = (date.fromisoformat(date_from) if date_from
             else date.today() - timedelta(days=SALES_DAYS))
    res = SectionResult("sales", saved=save)
    recoveries = _Recoveries(client)

    async with AsyncSessionLocal() as db:
        job_id = await create_scrape_job(db, tenant_id, "zepto_seller_sales", platform="zepto")
        try:
            ids = await zs.discover_ids(client)

            # Zepto computes a day once each morning; ask too early and the overview
            # comes back without totals (NoDataYet). Drop the newest day and ask again
            # once, rather than throwing the whole window away (P45) — the next run's
            # window covers the day that was not ready.
            data = None
            for _ in range(2):
                try:
                    data = await zs.fetch_sales_overview(client, start.isoformat(),
                                                         end.isoformat(), ids)
                    break
                except zs.NoDataYet:
                    res.not_ready.append(end.isoformat())
                    logger.info(f"{_md(end.isoformat())} not computed by Zepto yet · left for the next run")
                    if end <= start:
                        break
                    end -= timedelta(days=1)
            res.window = f"{start}..{end}"
            if data is None:
                # Not a failure — only a matter of timing; the job completes empty.
                await _finish(db, job_id, res, recoveries)
                return res
            days = _days(start, end)
            logger.info(f"overview {_md(start.isoformat())}→{_md(end.isoformat())} · "
                        f"{len(days)} days · GMV {data['headers']['gmv']['value']} · "
                        f"{data['headers']['units']['value']} units")

            product_rows: list[dict] = []
            lost: Lost = []

            async def _product_day(day: str) -> None:
                products = await zs.fetch_product_performance(client, day, day, ids)
                product_rows.extend(zp.parse_product_perf(products, tenant_id, job_id, day, day))

            # Per-SKU sales are fetched one day at a time so rows land at day grain;
            # the overview already returns the whole window by day in one call.
            for i, day in enumerate(days, 1):
                try:
                    await _product_day(day)
                except AuthError:
                    raise
                except Exception as e:
                    logger.info(f"products {_md(day)} failed ({e}) · re-check later")
                    lost.append((f"products {day}", lambda day=day: _product_day(day)))
                if i < len(days):
                    await asyncio.sleep(DAY_GAP_S)
            logger.info(f"products · {len(days)} days · {len(product_rows)} rows")

            daily_rows = zp.parse_sales_daily(data, ids, tenant_id, job_id,
                                              start.isoformat(), end.isoformat())
            city_rows = await _city_split(db, client, tenant_id, job_id, ids, days,
                                          all_cities, lost)

            lost = await _recheck(lost, res.recovered)
            res.lost = [label for label, _ in lost]

            if save:
                res.written = {"sales rows": await zst.save_sales_results(
                    db, daily_rows, product_rows, city_rows)}
            await _finish(db, job_id, res, recoveries)
        except AuthError:
            await fail_scrape_job(db, job_id, "auth_expired")
            raise
        except Exception as e:
            await fail_scrape_job(db, job_id, str(e))
            res.error = str(e)
    return res


async def _city_split(db, client, tenant_id: str, job_id: str, ids: dict, days: list[str],
                      all_cities: bool, lost: Lost) -> list[dict]:
    """Zepto sales per product per city per day — `zepto_seller_product_city_daily` rows.

    Why it is its own scrape: SKU x city x day is the only Zepto source with city AND
    category on one row (the Analytics category-x-city heatmap), but Zepto answers
    sales by city ONE CITY PER CALL, and an account lists ~145 cities. Blinkit's sales
    call carries the city on every row, so Blinkit has none of this.

    The rule: sweep EVERY city for the newest day of the window (~145 calls, ~2.5 min),
    and ask only the cities known to sell (+ any the sweep just found) for the older
    days, which are re-scrapes. Each day gets one full sweep, the run after it
    happens, so a city that starts selling is caught on its first day. This replaced
    "only ever ask the cities that sold before", which never asked a new city (Hosur
    went unnoticed for weeks, P21) and, for a new tenant, asked none at all (Sereko:
    21 days of sales, 0 city rows — P29). `all_cities` sweeps every city on every day
    (a one-off backfill).

    A city whose call fails goes on `lost` as (label, replay); the section's re-check
    retries it once, then fails the run (P44). The replay adds to the returned list,
    so the re-check must run before the save.
    """
    rows: list[dict] = []
    city_names = {c["cityID"]: c["cityName"] for c in ids.get("city_list", [])}

    async def _city_day(day: str, cities: list[str]) -> list[str]:
        failed: list[str] = []
        by_city = await zs.fetch_product_performance_by_city(client, day, day, ids, cities,
                                                             failed=failed)
        rows.extend(zp.parse_product_city(by_city, city_names, tenant_id, job_id, day))
        return failed

    def _queue(day: str, failed: list[str]) -> None:
        for city in failed:
            async def _again(day=day, city=city) -> None:
                if await _city_day(day, [city]):
                    raise RuntimeError(f"city {city} failed again")
            name = city_names.get(city, city)
            logger.info(f"cities {_md(day)} · {name} failed · re-check later")
            lost.append((f"{name} {day}", _again))

    if not days:
        return rows
    if all_cities:
        targets, city_days = ids["city_ids"], days
        logger.info(f"cities · every one of {len(targets)} on all {len(days)} days (--all-cities)")
    else:
        sweep_day = days[-1]
        _queue(sweep_day, await _city_day(sweep_day, ids["city_ids"]))
        swept = {r["city_id"] for r in rows}
        known = set(await zst.known_cities(db, tenant_id))
        targets, city_days = sorted(known | swept), days[:-1]
        new = sorted(swept - known)
        logger.info(f"cities · sweep {_md(sweep_day)}: {len(swept)} of {len(ids['city_ids'])} "
                    f"selling, {len(new)} new"
                    + (f" ({', '.join(city_names.get(c, c) for c in new)})" if new else ""))
        await asyncio.sleep(DAY_GAP_S)

    if targets:
        for i, day in enumerate(city_days, 1):
            _queue(day, await _city_day(day, targets))
            if i < len(city_days):
                await asyncio.sleep(DAY_GAP_S)
    n = len({r['city_id'] for r in rows})
    logger.info(f"cities · {n} {'city' if n == 1 else 'cities'} · {len(rows)} rows")
    return rows


# ── purchase orders ──────────────────────────────────────────────────────────

async def run_po(client, tenant_id: str, po_days_back: int, save: bool) -> SectionResult:
    """Purchase orders, goods receipts, shipping notices and PO lines.

    The window runs through TODAY, unlike sales and ads: POs are forward-looking, so
    stopping at yesterday would miss the orders that most need acting on.
    """
    start = date.today() - timedelta(days=po_days_back)
    end = date.today()
    res = SectionResult("po", window=f"{start}..{end}", saved=save)
    recoveries = _Recoveries(client)

    async with AsyncSessionLocal() as db:
        job_id = await create_scrape_job(db, tenant_id, "zepto_po", platform="zepto")
        try:
            # Each endpoint independently: asn/filter 500'd on 2026-08-27 and aborting
            # discarded 74 POs and 72 GRNs that had already come back.
            async def _try(label: str, coro):
                try:
                    return await coro
                except AuthError:
                    raise              # not a flaky endpoint — the session is gone (P46)
                except Exception as e:
                    res.lost.append(label)
                    logger.info(f"{label} failed after retries ({e}) · continuing without it")
                    return []

            f, t = start.isoformat(), end.isoformat()
            raw_pos = await _try("po/filter", zs.fetch_pos(client, f, t))
            raw_grns = await _try("grn/filter", zs.fetch_grns(client, f, t))
            raw_asns = await _try("asn/filter", zs.fetch_asns(client, f, t))

            pos = zp.parse_pos(raw_pos, tenant_id, job_id)
            grns = zp.parse_grns(raw_grns, tenant_id, job_id)
            asns = zp.parse_asns(raw_asns, tenant_id, job_id)
            logger.info(f"last {po_days_back} days · {len(pos)} POs · {len(grns)} GRNs · "
                        f"{len(asns)} ASNs")

            # One GET per PO: carries unit_price (cost) and mrp, which appear on no
            # other Zepto endpoint, plus per-SKU fill rate.
            items = zp.parse_po_items(
                await zs.fetch_po_items(client, [p["po_id"] for p in pos]), tenant_id, job_id)
            po_q = sum(g["po_qty"] or 0 for g in grns)
            grn_q = sum(g["grn_qty"] or 0 for g in grns)
            fill = f" · fill {100 * grn_q / po_q:.0f}%" if po_q else ""
            logger.info(f"lines · {len(items)} across {len(pos)} POs · "
                        f"value {rupees(sum(p['total_value'] or 0.0 for p in pos))}{fill}")

            if save:
                res.written = await zst.save_po_results(db, pos, grns, asns, items)
            await _finish(db, job_id, res, recoveries)
        except AuthError:
            await fail_scrape_job(db, job_id, "auth_expired")
            raise
        except Exception as e:
            await fail_scrape_job(db, job_id, str(e))
            res.error = str(e)
    return res


# ── ads ──────────────────────────────────────────────────────────────────────

def ads_window(date_from: str | None, date_to: str | None, today: date | None = None) -> list[str]:
    """--from..--to, defaulting to the ADS_DAYS days up to --to (itself defaulting to
    yesterday). Counted back from --to, so `--to` alone still gives a full window."""
    today = today or date.today()
    end = date.fromisoformat(date_to) if date_to else today - timedelta(days=1)
    start = date.fromisoformat(date_from) if date_from else end - timedelta(days=ADS_DAYS - 1)
    return _days(start, end) if start <= end else []


def blank_ads_day(day: str, stored_spend: float, today: date | None = None) -> str:
    """What to do with a day whose campaign list came back blank — no spend,
    impressions or clicks on ANY campaign — twice, 6 s apart.

    Blank means one of three things, and the response cannot say which: Zepto has not
    computed the day yet; ads-bff's transient all-"-" glitch; or every campaign really
    spent nothing (all paused). The old rule called all three "not ready" and skipped
    the day, so a brand with everything paused lost every day, silently, under green
    runs (Brik Oven 09-19 -> 09-28, P28). Decided by date instead:

      not_ready    yesterday or later — may genuinely not exist yet. Skipped; the
                   ads window fetches it again on the next run.
      keep_stored  an older day we already hold real spend for — a blank answer for
                   it can only be the glitch. Skipped, the stored rows stay.
      zero         an older day with no stored spend — the brand spent nothing.
                   Saved as zeros, so the day exists instead of being a hole.
    """
    today = today or date.today()
    if date.fromisoformat(day) >= today - timedelta(days=1):
        return "not_ready"
    return "keep_stored" if stored_spend > 0 else "zero"


def _has_any(day_rows: list[dict]) -> bool:
    return any(r["spend"] or r["impressions"] or r["clicks"] for r in day_rows)


def _is_auth_status(exc: Exception) -> bool:
    """A 401/403 that survived the client's own re-login (P34: this used to be a search
    for "401" in the exception TEXT)."""
    return (isinstance(exc, httpx.HTTPStatusError)
            and exc.response is not None and exc.response.status_code in (401, 403))


class _SessionGone(Exception):
    pass


async def run_ads(client, tenant_id: str, date_from: str | None, date_to: str | None,
                  category: str, save: bool) -> SectionResult:
    """Per day: the campaign list (operational fields + spend) and six analytics views
    per ad category (campaign, keyword, product, retail category, city, page) — plus,
    once per run, the campaign CATALOGUE the campaign manager reads.

    The campaign list ignores the category filter, so it is fetched once per day; the
    analytics views DO partition by it (the tabs return disjoint data).
    """
    categories = list(ep.ADS_CATEGORIES) if category == "all" else [category]
    days = ads_window(date_from, date_to)
    res = SectionResult("ads", saved=save,
                        window=f"{days[0]}..{days[-1]}" if days else "")
    if not days:
        res.error = f"empty ads window: --from {date_from} is after --to {date_to}"
        return res
    recoveries = _Recoveries(client)

    async with AsyncSessionLocal() as db:
        job_id = await create_scrape_job(db, tenant_id, "zepto_ads", platform="zepto")
        job_closed = False
        try:
            brand_id = (await zs.discover_ids(client))["brand_id"]
            logger.info(f"{_md(days[0])}→{_md(days[-1])} · {len(days)} days · "
                        f"{', '.join(c.replace('sponsored_', '') for c in categories)}")

            rows: list[dict] = []
            kw_rows: list[dict] = []
            prod_rows: list[dict] = []
            bd_rows: list[dict] = []
            kept_stored: list[str] = []    # blank older day, stored spend kept (glitch)
            zero_days: list[str] = []      # blank older day, saved as genuine zeros
            lost: Lost = []
            catalog: dict = {}
            auth_fails = 0

            def _note(exc: Exception) -> None:
                # A dead session fails every remaining call; carrying on burned ~150
                # requests to save nothing, three times. One auth failure can be a blip;
                # three in a row is the session gone — stop and keep what was fetched.
                nonlocal auth_fails
                if _is_auth_status(exc):
                    auth_fails += 1
                    if auth_fails >= 3:
                        raise _SessionGone(
                            "3 consecutive auth failures — the Zepto session is gone. Saved "
                            "what was fetched; run `cli auth login zepto --tenant <id>` and "
                            "scrape the missing days.")
                else:
                    auth_fails = 0

            async def _attempt(label: str, fn) -> None:
                """Run one fetch+parse step; queue it for the re-check if it fails."""
                try:
                    await fn()
                except (AuthError, _SessionGone):
                    raise
                except Exception as e:
                    logger.info(f"{label} failed ({e}) · re-check later")
                    lost.append((label, fn))
                    _note(e)

            def _day_campaigns(day: str) -> dict:
                # Read out of `rows`, not captured, so an analytics fetch replayed by
                # the re-check patches the rows the first pass collected.
                return {r["campaign_id"]: r for r in rows if r["date"].isoformat() == day}

            async def _campaign_list(day: str) -> None:
                camps = await zs.fetch_ad_campaigns(client, brand_id, day, day, categories[0])
                day_rows = zp.parse_ad_campaigns(camps, tenant_id, job_id, day, categories[0])
                # ads-bff sometimes returns every metric as "-", then real figures
                # seconds later. Retry once; still bare -> blank_ads_day decides (P28).
                if day_rows and not _has_any(day_rows):
                    await asyncio.sleep(6)
                    camps = await zs.fetch_ad_campaigns(client, brand_id, day, day, categories[0])
                    day_rows = zp.parse_ad_campaigns(camps, tenant_id, job_id, day, categories[0])
                    if not _has_any(day_rows):
                        verdict = blank_ads_day(day, await zst.stored_ad_spend(db, tenant_id, day))
                        if verdict == "zero":
                            if day not in zero_days:
                                zero_days.append(day)
                            rows.extend(day_rows)
                            return
                        skipped = res.not_ready if verdict == "not_ready" else kept_stored
                        if day not in skipped:
                            skipped.append(day)
                        return
                # Extended BEFORE the tabs, so _day_campaigns can find the day's rows.
                rows.extend(day_rows)

            async def _day_tabs(day: str) -> None:
                """The six analytics views per category; each its own _attempt, so one
                lost view does not cost the other five."""
                for cat in categories:
                    short_cat = cat.replace("sponsored_", "")

                    async def _analytics(cat=cat, day=day) -> None:
                        tab = await zs.fetch_ads_tabular(client, brand_id, day, day,
                                                         ep.ADS_VIEW_CAMPAIGN, cat)
                        by_id = _day_campaigns(day)
                        for cid, patch in zp.parse_ad_tabular_campaigns(tab).items():
                            row = by_id.get(cid)
                            if row is None:
                                logger.warning(
                                    f"campaign {cid} is in the {cat} analytics table but "
                                    f"not in the campaign list for {day} — metrics dropped")
                                continue
                            row.update(patch)
                            # The tabs partition properly, unlike the list, so this is
                            # the campaign's real category.
                            row["campaign_category"] = cat

                    async def _keywords(cat=cat, day=day) -> None:
                        kws = await zs.fetch_ads_tabular(client, brand_id, day, day,
                                                         ep.ADS_VIEW_KEYWORD, cat)
                        kw_rows.extend(zp.parse_ad_keywords(kws, tenant_id, job_id, day, cat, brand_id))

                    async def _products(cat=cat, day=day) -> None:
                        tab = await zs.fetch_ads_tabular(client, brand_id, day, day,
                                                         ep.ADS_VIEW_PRODUCT, cat)
                        prod_rows.extend(zp.parse_ad_products(tab, tenant_id, job_id, day, cat, brand_id))

                    for label, fn in ((f"{_md(day)} {short_cat} analytics", _analytics),
                                      (f"{_md(day)} {short_cat} keywords", _keywords),
                                      (f"{_md(day)} {short_cat} products", _products)):
                        await _attempt(label, fn)
                        await asyncio.sleep(DAY_GAP_S)

                    # Retail category / city / page: one shape, one parser.
                    for view, dim in ((ep.ADS_VIEW_CATEGORY, "category"),
                                      (ep.ADS_VIEW_CITY, "city"),
                                      (ep.ADS_VIEW_PAGE, "page")):
                        async def _breakdown(cat=cat, day=day, view=view, dim=dim) -> None:
                            tab = await zs.fetch_ads_tabular(client, brand_id, day, day, view, cat)
                            bd_rows.extend(zp.parse_ad_breakdown(tab, tenant_id, job_id, day,
                                                                 cat, brand_id, dim))
                        await _attempt(f"{_md(day)} {short_cat} {dim}", _breakdown)
                        await asyncio.sleep(DAY_GAP_S)

            async def _day(day: str) -> None:
                """The list, then the tabs. Raises if the LIST is lost — the tabs mean
                nothing without it, so the whole day is one re-check item."""
                await _campaign_list(day)
                # A blank day skips the tabs: with no spend anywhere they can only come
                # back empty (a paused brand would spend ~18 calls a day on nothing).
                if day in res.not_ready:
                    logger.info(f"{_md(day)} · not computed by Zepto yet · skipped")
                    return
                if day in kept_stored:
                    logger.info(f"{_md(day)} · came back blank · kept the stored rows")
                    return
                if day in zero_days:
                    logger.info(f"{_md(day)} · no ad activity · saved as zero")
                    return
                await asyncio.sleep(DAY_GAP_S)
                await _day_tabs(day)
                day_rows = _day_campaigns(day).values()
                logger.info(f"{_md(day)} · {len(day_rows)} campaigns · "
                            f"{rupees(sum(r['spend'] for r in day_rows))} spend")

            # The campaign CATALOGUE — every campaign's current configuration, for the
            # campaign manager. Once per run: it is "now", not a series.
            async def _catalog() -> None:
                catalog.clear()
                catalog.update(await zs.fetch_campaign_catalog(client))
                kws = sum(len(d.get("keyword_config") or []) for d in (catalog.get("details") or {}).values())
                logger.info(f"catalogue · {len(catalog.get('campaigns') or [])} campaigns · "
                            f"{len(catalog.get('details') or {})} with detail · {kws} keywords")

            auth_error: AuthError | None = None
            session_note = None
            try:
                for day in days:
                    await _attempt(f"{_md(day)} campaign list", lambda day=day: _day(day))
                await _attempt("catalogue", _catalog)
                lost = await _recheck(lost, res.recovered)
            except _SessionGone as e:
                session_note = str(e)
            except AuthError as e:
                # Re-login exhausted. Save what was fetched, then fail as auth_expired.
                auth_error = e

            res.lost = [label for label, _ in lost]
            # A campaign whose detail read failed even on retry keeps its last good
            # detail and gets a list-only row — still a lost fetch.
            res.lost += [f"catalogue detail {cid}" for cid in catalog.get("failed") or []]

            if save:
                res.written = dict(await zst.save_ad_results(db, rows, kw_rows, prod_rows, bd_rows))
                if catalog.get("campaigns"):
                    cat_written = await zst.save_campaign_catalog(
                        db, *zp.parse_campaign_catalog(catalog, tenant_id, job_id))
                    res.written["catalogue campaigns"] = cat_written.get("campaigns", 0)
                    res.written["catalogue keywords"] = cat_written.get("keywords", 0)
            if auth_error is not None:
                await fail_scrape_job(db, job_id, "auth_expired",
                                      records_written=sum(res.written.values()))
                job_closed = True
                raise auth_error
            if session_note:
                res.lost.append("session gone — remaining fetches skipped")
                logger.warning(session_note)

            # Totals on de-duplicated rows, matching what storage writes.
            unique = list({r["upsert_key"]: r for r in rows}.values())
            logger.info(f"total · {rupees(sum(r['spend'] for r in unique))} spend · "
                        f"{sum(r['clicks'] for r in unique):,} clicks · "
                        f"{rupees(sum(r.get('revenue') or 0 for r in unique))} revenue · "
                        f"{len(unique)} campaign rows · {len({r['upsert_key'] for r in kw_rows})} "
                        f"keyword rows")
            await _finish(db, job_id, res, recoveries)
        except AuthError:
            if not job_closed:                 # e.g. brand discovery, before the loop
                await fail_scrape_job(db, job_id, "auth_expired")
            raise
        except Exception as e:
            await fail_scrape_job(db, job_id, str(e))
            res.error = str(e)
    return res
