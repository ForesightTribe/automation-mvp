"""Zepto private scrape — the run: one login, then sales, PO and ads.

Moved out of `cli/commands/scrape.py` in Phase 1 (2026-10-05,
zepto-cm-exp/plans/PLAN-private-scrape.md §6). The CLI keeps flags, printing and exit
codes; everything that fetches, parses, retries and saves is here, so it can be tested
without a terminal and new work (per-campaign keyword detail) has somewhere to go that
is not a 450-line CLI function.

Shape (same four files as Blinkit's seller scrape, plus this one):
    endpoints.py   URLs and constants
    scraper.py     HTTP only
    parser.py      raw -> rows, pure
    storage.py     upserts, and the two reads the run needs
    run.py         the loops — this file

Each section returns a `SectionResult` and never prints. One result drives three things
that used to disagree: the exit code (anything lost -> 1, auth gone -> 3), the
`scrape_jobs` row (P35: a run that lost fetches used to complete its row as success and
then exit 1), and the report the CLI prints.

Zepto has ONE console behind ONE login, so it is one job and one command, with every
section on a single session — each Zepto login logs the client's own dashboard out.
"""
import asyncio
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

# Gap between per-day calls. Paces multi-day windows: a burst of back-to-back requests
# is the kind of pattern this site's WAF reacts to.
DAY_GAP_S = 1.5

# How long a section waits before replaying the fetches it lost. Longer than the
# fetchers' own 5xx ladders on purpose: by the time a fetch has exhausted those, the
# fault is not a two-second blip. Only what fails the replay too fails the run.
RECHECK_WAIT_S = 20

# Default windows (P37). Ads: the 7 days up to yesterday — like Blinkit's ads, so a
# missed run heals and late attribution lands (P1). Sales: 8 days, Zepto recomputes
# days late. PO: 30 days back through TODAY — POs are forward-looking, an order raised
# today expires in ~3 weeks.
ADS_DAYS = 7
SALES_DAYS = 8
PO_DAYS = 30

Progress = Callable[[str], None]
Lost = list[tuple[str, Callable[[], Awaitable[None]]]]


@dataclass
class SectionResult:
    """What one section did. `lines` are (level, text) for the CLI to print —
    level is "info", "good" or "warn"; no markup in the text."""
    name: str
    window: str = ""
    saved: bool = True
    written: dict[str, int] = field(default_factory=dict)
    lost: list[str] = field(default_factory=list)       # failed twice -> the run fails
    recovered: list[str] = field(default_factory=list)  # failed once, fine on re-check
    not_ready: list[str] = field(default_factory=list)  # Zepto has not computed it yet
    error: str | None = None                            # the section aborted
    lines: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and not self.lost

    def say(self, text: str, level: str = "info") -> None:
        self.lines.append((level, text))


def _noop(_msg: str) -> None:
    return None


def _days(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def _short(items: list[str], n: int = 5) -> str:
    return ", ".join(items[:n]) + (" …" if len(items) > n else "")


async def _recheck(lost: Lost, recovered: list[str], progress: Progress, what: str) -> Lost:
    """Replay every lost fetch once, after RECHECK_WAIT_S. Returns what is still lost.
    An AuthError is not a lost fetch — the session is gone — so it propagates."""
    if not lost:
        return lost
    progress(f"{len(lost)} {what} fetch(es) lost — re-checking in {RECHECK_WAIT_S}s")
    await asyncio.sleep(RECHECK_WAIT_S)
    still: Lost = []
    for label, fn in lost:
        progress(f"Re-checking {label}")
        try:
            await fn()
        except AuthError:
            raise
        except Exception as e:
            logger.warning(f"Zepto {what} {label} failed on re-check: {e}")
            still.append((label, fn))
        else:
            recovered.append(label)
        await asyncio.sleep(DAY_GAP_S)
    return still


async def _finish(db, job_id: str, res: SectionResult) -> None:
    """Close the `scrape_jobs` row from the result (P35): success only when nothing
    was lost; otherwise failed, naming what was lost, with the rows that DID land."""
    total = sum(res.written.values())
    if res.lost:
        await fail_scrape_job(
            db, job_id, f"partial: {len(res.lost)} fetch(es) lost — {_short(res.lost)}",
            records_written=total,
        )
    else:
        await complete_scrape_job(db, job_id, total)


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
    progress: Progress | None = None,
    on_section: Callable[[SectionResult], None] | None = None,
) -> list[SectionResult]:
    """One login, then each chosen section in turn on the same client.

    A section that fails does not stop the others — one flaky endpoint costs its own
    data, not the run. An `AuthError` does stop everything: the session is gone and no
    later section can work either; the CLI turns it into exit 3 (`auth_expired`).
    """
    progress = progress or _noop
    progress("Pre-flight: Zepto session…")
    # ensure() the session, then mint the WAF token. The client recovers PER CALL
    # (401 -> re-login, 202/429 -> re-mint): the account is shared and on 2026-09-01
    # the session was evicted three times in ten minutes.
    _, _, client = await setup(str(tenant_id))

    plan = [
        ("sales", sales, lambda: run_sales(client, tenant_id, date_from, date_to,
                                           all_cities, save, progress)),
        ("po", po, lambda: run_po(client, tenant_id, po_days_back, save, progress)),
        ("ads", ads, lambda: run_ads(client, tenant_id, date_from, date_to, category,
                                     save, progress)),
    ]
    results: list[SectionResult] = []
    for name, wanted, go in plan:
        if not wanted:
            continue
        logger.info(f"Zepto: {name} section starting")
        try:
            res = await go()
        except AuthError:
            raise
        except Exception as e:                 # sections catch their own; belt and braces
            res = SectionResult(name, error=str(getattr(e, "orig", None) or e))
        if not res.ok:
            # ERROR, not WARNING: the alert matches severity>=ERROR, and this line is
            # what names WHICH section broke.
            logger.error(
                f"Zepto {name} section FAILED: "
                + (res.error or f"{len(res.lost)} fetch(es) lost — {_short(res.lost)}")
            )
        results.append(res)
        if on_section:
            on_section(res)
    return results


# ── sales ────────────────────────────────────────────────────────────────────

async def run_sales(client, tenant_id: str, date_from: str | None, date_to: str | None,
                    all_cities: bool, save: bool, progress: Progress = _noop) -> SectionResult:
    """Brand totals per day, per-product sales per day, and the per-city split."""
    yesterday = date.today() - timedelta(days=1)
    end = date.fromisoformat(date_to) if date_to else yesterday
    start = (date.fromisoformat(date_from) if date_from
             else date.today() - timedelta(days=SALES_DAYS))
    res = SectionResult("sales", saved=save)

    async with AsyncSessionLocal() as db:
        job_id = await create_scrape_job(db, tenant_id, "zepto_seller_sales", platform="zepto")
        try:
            progress("Discovering brand / city / category ids")
            ids = await zs.discover_ids(client)

            # Zepto computes a day once each morning; ask too early and the overview
            # comes back without totals (NoDataYet). Drop the newest day and ask again
            # once, rather than throwing the whole window away (P45) — the next run's
            # window covers the day that was not ready.
            data = None
            for _ in range(2):
                progress(f"Sales overview {start}..{end}")
                try:
                    data = await zs.fetch_sales_overview(client, start.isoformat(),
                                                         end.isoformat(), ids)
                    break
                except zs.NoDataYet:
                    res.not_ready.append(end.isoformat())
                    if end <= start:
                        break
                    end -= timedelta(days=1)
            res.window = f"{start}..{end}"
            if data is None:
                # Not a failure — only a matter of timing; the job completes empty.
                res.say(f"Zepto has not computed {_short(res.not_ready)} yet — "
                        "nothing to scrape this run", "warn")
                await _finish(db, job_id, res)
                return res
            days = _days(start, end)

            product_rows: list[dict] = []
            lost: Lost = []

            async def _product_day(day: str) -> None:
                products = await zs.fetch_product_performance(client, day, day, ids)
                product_rows.extend(zp.parse_product_perf(products, tenant_id, job_id, day, day))

            # Per-SKU sales are fetched one day at a time so rows land at day grain;
            # the overview already returns the whole window by day in one call.
            for i, day in enumerate(days, 1):
                progress(f"Product breakdown {day} ({i}/{len(days)})")
                try:
                    await _product_day(day)
                except AuthError:
                    raise
                except Exception as e:
                    logger.warning(f"Zepto product-performance failed for {day}: {e}")
                    lost.append((f"products {day}", lambda day=day: _product_day(day)))
                if i < len(days):
                    await asyncio.sleep(DAY_GAP_S)

            daily_rows = zp.parse_sales_daily(data, ids, tenant_id, job_id,
                                              start.isoformat(), end.isoformat())
            city_rows = await _city_split(db, client, tenant_id, job_id, ids, days,
                                          all_cities, lost, res, progress)

            lost = await _recheck(lost, res.recovered, progress, "sales")
            res.lost = [label for label, _ in lost]

            if save:
                res.written = {"sales rows": await zst.save_sales_results(
                    db, daily_rows, product_rows, city_rows)}
            await _finish(db, job_id, res)
        except AuthError:
            await fail_scrape_job(db, job_id, "auth_expired")
            raise
        except Exception as e:
            await fail_scrape_job(db, job_id, str(e))
            res.error = str(e)
            return res

    gmv = data["headers"]["gmv"]["value"]
    units = data["headers"]["units"]["value"]
    res.say(f"GMV {gmv}   Units {units}   ({len(daily_rows)} days)")
    res.say(f"Product rows {len(product_rows)} over {len(days)} day(s)   "
            f"Product-by-city rows {len(city_rows)}")
    if city_rows:
        by_name: dict[str, float] = {}
        for r in city_rows:
            by_name[r["city_name"] or r["city_id"]] = by_name.get(r["city_name"] or r["city_id"], 0) + r["gmv"]
        top = sorted(by_name.items(), key=lambda kv: -kv[1])
        res.say("Cities: " + ", ".join(f"{n} ₹{v:,.0f}" for n, v in top[:3])
                + (f" (+{len(top) - 3} more)" if len(top) > 3 else ""))
    if res.not_ready:
        res.say(f"Not computed by Zepto yet, left for the next run: {_short(res.not_ready)}", "warn")
    return res


async def _city_split(db, client, tenant_id: str, job_id: str, ids: dict, days: list[str],
                      all_cities: bool, lost: Lost, res: SectionResult,
                      progress: Progress) -> list[dict]:
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
            lost.append((f"{city_names.get(city, city)} {day}", _again))

    if not days:
        return rows
    if all_cities:
        targets, city_days = ids["city_ids"], days
    else:
        sweep_day = days[-1]
        progress(f"Sweeping all {len(ids['city_ids'])} cities for {sweep_day}")
        _queue(sweep_day, await _city_day(sweep_day, ids["city_ids"]))
        swept = {r["city_id"] for r in rows}
        known = set(await zst.known_cities(db, tenant_id))
        targets, city_days = sorted(known | swept), days[:-1]
        new = sorted(swept - known)
        logger.info(f"Zepto: city sweep for {sweep_day} — {len(swept)} selling, {len(new)} new: "
                    f"{', '.join(city_names.get(c, c) for c in new) or 'none'}")
        res.say(f"City sweep {sweep_day}: {len(swept)} selling city(ies)"
                + (f", new: {', '.join(city_names.get(c, c) for c in new)}" if new else ""))
        await asyncio.sleep(DAY_GAP_S)

    if targets:
        for i, day in enumerate(city_days, 1):
            progress(f"Product-by-city {day} ({i}/{len(city_days)}), {len(targets)} cities")
            _queue(day, await _city_day(day, targets))
            if i < len(city_days):
                await asyncio.sleep(DAY_GAP_S)
    return rows


# ── purchase orders ──────────────────────────────────────────────────────────

async def run_po(client, tenant_id: str, po_days_back: int, save: bool,
                 progress: Progress = _noop) -> SectionResult:
    """Purchase orders, goods receipts, shipping notices and PO lines.

    The window runs through TODAY, unlike sales and ads: POs are forward-looking, so
    stopping at yesterday would miss the orders that most need acting on.
    """
    start = date.today() - timedelta(days=po_days_back)
    end = date.today()
    res = SectionResult("po", window=f"{start}..{end}", saved=save)

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
                    logger.warning(f"Zepto {label} failed, continuing without it: {e}")
                    return []

            f, t = start.isoformat(), end.isoformat()
            progress(f"POs {f}..{t}")
            raw_pos = await _try("po/filter", zs.fetch_pos(client, f, t))
            progress(f"GRNs {f}..{t}")
            raw_grns = await _try("grn/filter", zs.fetch_grns(client, f, t))
            progress(f"ASNs {f}..{t}")
            raw_asns = await _try("asn/filter", zs.fetch_asns(client, f, t))

            pos = zp.parse_pos(raw_pos, tenant_id, job_id)
            grns = zp.parse_grns(raw_grns, tenant_id, job_id)
            asns = zp.parse_asns(raw_asns, tenant_id, job_id)

            # One GET per PO: carries unit_price (cost) and mrp, which appear on no
            # other Zepto endpoint, plus per-SKU fill rate.
            progress(f"Line items for {len(pos)} POs")
            items = zp.parse_po_items(
                await zs.fetch_po_items(client, [p["po_id"] for p in pos]), tenant_id, job_id)

            if save:
                res.written = await zst.save_po_results(db, pos, grns, asns, items)
            await _finish(db, job_id, res)
        except AuthError:
            await fail_scrape_job(db, job_id, "auth_expired")
            raise
        except Exception as e:
            await fail_scrape_job(db, job_id, str(e))
            res.error = str(e)
            return res

    res.say(f"POs {len(pos)}   units ordered {sum(p['total_qty'] or 0 for p in pos):,}   "
            f"value ₹{sum(p['total_value'] or 0.0 for p in pos):,.0f}")
    res.say(f"GRNs {len(grns)}   units received {sum(g['grn_qty'] or 0 for g in grns):,}   "
            f"ASNs {len(asns)}   PO lines {len(items)}")
    po_q = sum(g["po_qty"] or 0 for g in grns)
    grn_q = sum(g["grn_qty"] or 0 for g in grns)
    if po_q:
        res.say(f"Fill rate {grn_q:,}/{po_q:,} = {100 * grn_q / po_q:.1f}%")
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
                   7-day window fetches it again on the next run.
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
                  category: str, save: bool, progress: Progress = _noop) -> SectionResult:
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

    async with AsyncSessionLocal() as db:
        job_id = await create_scrape_job(db, tenant_id, "zepto_ads", platform="zepto")
        job_closed = False
        try:
            progress("Discovering brand")
            brand_id = (await zs.discover_ids(client))["brand_id"]

            rows: list[dict] = []
            kw_rows: list[dict] = []
            prod_rows: list[dict] = []
            bd_rows: list[dict] = []
            kept_stored: list[str] = []    # blank older day, stored spend kept (glitch)
            zero_days: list[str] = []      # blank older day, saved as genuine zeros
            lost: Lost = []
            catalog: dict = {}
            total_calls = len(days) * (1 + 6 * len(categories))
            n = 0
            auth_fails = 0

            def _tick(msg: str) -> None:
                nonlocal n
                n += 1
                progress(f"{msg} ({n}/{total_calls})" if n <= total_calls else f"{msg} (re-check)")

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
                    logger.warning(f"Zepto {label} failed: {e}")
                    lost.append((label, fn))
                    _note(e)

            def _day_campaigns(day: str) -> dict:
                # Read out of `rows`, not captured, so an analytics fetch replayed by
                # the re-check patches the rows the first pass collected.
                return {r["campaign_id"]: r for r in rows if r["date"].isoformat() == day}

            async def _campaign_list(day: str) -> None:
                _tick(f"Campaigns {day}")
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
                    async def _analytics(cat=cat, day=day) -> None:
                        _tick(f"Analytics {cat} {day}")
                        tab = await zs.fetch_ads_tabular(client, brand_id, day, day,
                                                         ep.ADS_VIEW_CAMPAIGN, cat)
                        by_id = _day_campaigns(day)
                        for cid, patch in zp.parse_ad_tabular_campaigns(tab).items():
                            row = by_id.get(cid)
                            if row is None:
                                logger.warning(
                                    f"Zepto campaign {cid} is in the {cat} analytics table "
                                    f"but not in the campaign list for {day} — metrics dropped")
                                continue
                            row.update(patch)
                            # The tabs partition properly, unlike the list, so this is
                            # the campaign's real category.
                            row["campaign_category"] = cat

                    async def _keywords(cat=cat, day=day) -> None:
                        _tick(f"Keywords {cat} {day}")
                        kws = await zs.fetch_ads_tabular(client, brand_id, day, day,
                                                         ep.ADS_VIEW_KEYWORD, cat)
                        kw_rows.extend(zp.parse_ad_keywords(kws, tenant_id, job_id, day, cat, brand_id))

                    async def _products(cat=cat, day=day) -> None:
                        _tick(f"Products {cat} {day}")
                        tab = await zs.fetch_ads_tabular(client, brand_id, day, day,
                                                         ep.ADS_VIEW_PRODUCT, cat)
                        prod_rows.extend(zp.parse_ad_products(tab, tenant_id, job_id, day, cat, brand_id))

                    for label, fn in ((f"{cat}/{day} analytics", _analytics),
                                      (f"{cat}/{day} keywords", _keywords),
                                      (f"{cat}/{day} products", _products)):
                        await _attempt(label, fn)
                        await asyncio.sleep(DAY_GAP_S)

                    # Retail category / city / page: one shape, one parser.
                    for view, dim in ((ep.ADS_VIEW_CATEGORY, "category"),
                                      (ep.ADS_VIEW_CITY, "city"),
                                      (ep.ADS_VIEW_PAGE, "page")):
                        async def _breakdown(cat=cat, day=day, view=view, dim=dim) -> None:
                            _tick(f"{dim.title()} {cat} {day}")
                            tab = await zs.fetch_ads_tabular(client, brand_id, day, day, view, cat)
                            bd_rows.extend(zp.parse_ad_breakdown(tab, tenant_id, job_id, day,
                                                                 cat, brand_id, dim))
                        await _attempt(f"{cat}/{day} {dim}", _breakdown)
                        await asyncio.sleep(DAY_GAP_S)

            async def _day(day: str) -> None:
                """The list, then the tabs. Raises if the LIST is lost — the tabs mean
                nothing without it, so the whole day is one re-check item."""
                await _campaign_list(day)
                # A blank day skips the tabs: with no spend anywhere they can only come
                # back empty (a paused brand would spend ~18 calls a day on nothing).
                if day in res.not_ready or day in kept_stored or day in zero_days:
                    return
                await asyncio.sleep(DAY_GAP_S)
                await _day_tabs(day)

            # The campaign CATALOGUE — every campaign's current configuration, for the
            # campaign manager. Once per run: it is "now", not a series.
            async def _catalog() -> None:
                _tick("Campaign catalogue")
                catalog.clear()
                catalog.update(await zs.fetch_campaign_catalog(client))

            auth_error: AuthError | None = None
            session_note = None
            try:
                for day in days:
                    await _attempt(day, lambda day=day: _day(day))
                await _attempt("campaign catalogue", _catalog)
                lost = await _recheck(lost, res.recovered, progress, "ads")
            except _SessionGone as e:
                session_note = str(e)
            except AuthError as e:
                # Re-login exhausted. Save what was fetched, then fail as auth_expired.
                auth_error, session_note = e, f"Zepto auth failed mid-run: {e}"

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
                res.say(session_note, "warn")
            await _finish(db, job_id, res)
        except AuthError:
            if not job_closed:                 # e.g. brand discovery, before the loop
                await fail_scrape_job(db, job_id, "auth_expired")
            raise
        except Exception as e:
            await fail_scrape_job(db, job_id, str(e))
            res.error = str(e)
            return res

    # Report on de-duplicated rows, matching what storage writes.
    unique = list({r["upsert_key"]: r for r in rows}.values())
    kw_u = list({r["upsert_key"]: r for r in kw_rows}.values())
    prod_u = list({r["upsert_key"]: r for r in prod_rows}.values())
    bd_u = {r["upsert_key"] for r in bd_rows}
    res.say(f"Categories: {', '.join(categories)}")
    res.say(f"Campaign rows {len(unique)}   Spend ₹{sum(r['spend'] for r in unique):,.0f}   "
            f"Clicks {sum(r['clicks'] for r in unique):,}   "
            f"Revenue ₹{sum(r.get('revenue') or 0 for r in unique):,.0f}")
    res.say(f"Keywords {len(kw_u)} row(s), spend ₹{sum(k['spend'] for k in kw_u):,.0f}   "
            f"Products {len(prod_u)} row(s), spend ₹{sum(k['spend'] for k in prod_u):,.0f}   "
            f"Breakdown {len(bd_u)} row(s)")
    if catalog.get("campaigns"):
        res.say(f"Catalogue: {len(catalog['campaigns'])} campaign(s), "
                f"{len(catalog.get('details') or {})} with full detail"
                + (f", {len(catalog['failed'])} detail read(s) failed" if catalog.get("failed") else ""))
    if res.not_ready:
        res.say(f"{len(res.not_ready)} day(s) not computed by Zepto yet, skipped (the next "
                f"run fetches them): {_short(res.not_ready)}", "warn")
    if zero_days:
        res.say(f"{len(zero_days)} day(s) with no ad activity on any campaign, saved as "
                f"zero: {_short(zero_days)}")
    if kept_stored:
        res.say(f"{len(kept_stored)} day(s) came back blank but already have stored spend "
                f"— kept the stored rows: {_short(kept_stored)}", "warn")
    return res
