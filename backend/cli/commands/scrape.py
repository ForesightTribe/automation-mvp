import asyncio
import time
from datetime import date as _date, timedelta
from typing import Optional
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from app.core.database import AsyncSessionLocal
from app.utils.logger import logger
from app.utils.time import now_ist
from platform_auth import service as auth_service
from platform_auth import store as auth_store
from platform_auth.errors import AUTH_EXPIRED_EXIT_CODE, AuthError
from scraper.utils.jobs import create_scrape_job, complete_scrape_job, fail_scrape_job
from scraper.platforms.instamart.dashboard_data import run as instamart_run
from scraper.utils.run_log import rupees, tag, tenant_slug, took
from scraper.platforms.zepto.dashboard_data.seller import run as zepto_run
from scraper.platforms.blinkit.dashboard_data.marketing.scraper import scrape
from scraper.platforms.blinkit.dashboard_data.marketing.parser import (
    parse_campaign,
    parse_campaign_daily,
    parse_campaign_detail,
    parse_campaign_detail_day,
    parse_campaign_keywords,
    parse_sponsored_sov,
    parse_brand_collection,
    parse_visibility_plan,
    stamp_budgets,
)
from scraper.platforms.blinkit.dashboard_data.marketing.storage import save_scrape_results
from scraper.platforms.blinkit.dashboard_data.seller import scraper as seller_scraper
from scraper.platforms.blinkit.dashboard_data.seller.parser import (
    parse_sale_row,
    parse_sales_summary,
    parse_po_row,
    parse_po_item,
    parse_po_summary,
    parse_soh_row,
    parse_scorecard_weekly,
    parse_scorecard_facility,
    parse_scorecard_key_sku,
)
from scraper.platforms.blinkit.dashboard_data.seller.storage import (
    save_scrape_results as seller_save_results,
    save_po_results,
    save_soh_results,
    save_scorecard_results,
)
from scraper.platforms.blinkit.dashboard_data.seller_hub import scraper as seller_hub_scraper
from scraper.platforms.blinkit.dashboard_data.seller_hub.parser import (
    parse_sales_by_product as parse_seller_hub_sales_by_product,
    parse_sales_orders as parse_seller_hub_sales_orders,
)
from scraper.platforms.blinkit.dashboard_data.seller_hub.storage import (
    save_sales_results as save_seller_hub_sales_results,
)

app = typer.Typer(help="Run scrapers and view results.")
console = Console()

@app.command("blinkit")
def scrape_blinkit(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    date_from: str = typer.Option(None, "--from", help="Start date YYYY-MM-DD (default: 7 days ago)"),
    date_to: str = typer.Option(None, "--to", help="End date YYYY-MM-DD (default: today)"),
    limit: int = typer.Option(None, "--limit", help="Test mode: only the N most-active campaigns"),
    keyword_days: int = typer.Option(
        3, "--keyword-days",
        help="Days of keyword performance asked one day at a time, newest first (never today). "
             "0 = every day of the window — use with --from to backfill.",
    ),
    save: bool = typer.Option(True, "--save/--no-save", help="Save results to PostgreSQL"),
):
    """Scrape the Blinkit marketing dashboard for a date window.

    One pass fetches the campaign list, each campaign's daily metric series + its
    keyword/recommendation breakdown, plus SOV / collections / plans. Use --from
    to backfill (e.g. --from 30 days ago); the daily run defaults to the last week
    so late metric revisions are picked up. Use --limit to smoke-test a few
    campaigns without the full-volume run.
    """
    asyncio.run(_scrape_blinkit(tenant_id, date_from, date_to, limit, save,
                                keyword_days or None))


async def _scrape_blinkit(
    tenant_id: str, date_from: str | None, date_to: str | None, limit: int | None, save: bool
, kw_days: int | None = 3) -> None:
    """Logs follow scraper/utils/run_log.py: step lines tagged `blinkit·<tenant>·marketing`,
    no spinner, no printed tables."""
    start = _date.fromisoformat(date_from) if date_from else _date.today() - timedelta(days=7)
    end = _date.fromisoformat(date_to) if date_to else _date.today()
    snapshot_date = end.isoformat()
    started = time.monotonic()

    async with AsyncSessionLocal() as db:
        slug = await tenant_slug(db, tenant_id)
        with tag("blinkit", slug, "marketing"):
            job_id = None
            try:
                logger.info(f"start · {start}→{end}" + (f" · first {limit} campaigns" if limit else ""))
                # ensure() = load → probe → refresh → re-login, doing the least work
                # that yields a session known to work. Replaces a bare load, which
                # happily returned a session that had died days earlier and let the
                # scrape fail deep inside Playwright instead.
                storage_state = (await auth_service.ensure(db, tenant_id, "blinkit")).storage_state

                job_id = await create_scrape_job(db, tenant_id, "blinkit_marketing")
                raw = await scrape(storage_state, start, end, limit=limit, kw_days=kw_days)

                campaign_detail = raw.get("campaign_detail") or {}
                cities = raw.get("cities") or {}
                campaigns = [
                    parse_campaign(c, tenant_id, job_id,
                                   detail=campaign_detail.get(c["id"]), cities=cities)
                    for c in raw["campaigns"]
                ]
                type_by_id = {c["id"]: c.get("campaign_type") for c in raw["campaigns"]}

                keyword_bids = [
                    row
                    for cid, attrs in (raw.get("keyword_attributes") or {}).items()
                    for row in parse_campaign_keywords(
                        attrs, campaign_detail.get(cid) or {}, cid, tenant_id, job_id
                    )
                ]

                daily = [
                    parse_campaign_daily(row, cid, type_by_id.get(cid), tenant_id, job_id)
                    for cid, rows in raw["daily"].items()
                    for row in rows
                ]
                detail = [
                    d
                    for cid, report in raw["detail"].items()
                    for d in parse_campaign_detail(
                        report, cid, type_by_id.get(cid), snapshot_date, tenant_id, job_id
                    )
                ]
                # Keyword performance per day (B6).
                detail_days = [
                    d
                    for cid, by_day in (raw.get("detail_days") or {}).items()
                    for day, report in by_day.items()
                    for d in parse_campaign_detail_day(
                        report, cid, type_by_id.get(cid), day, tenant_id, job_id)
                ]
                # B8: today's budgets go on yesterday's rows, the only budget history there is.
                budgets = stamp_budgets(
                    daily, campaign_detail, (now_ist().date() - timedelta(days=1)).isoformat())
                sov = [
                    parse_sponsored_sov(s, tenant_id, job_id, snapshot_date)
                    for s in raw["sponsored_sov"]
                ]
                collections = [parse_brand_collection(c, tenant_id, job_id) for c in raw["brand_collections"]]
                plans = [parse_visibility_plan(p, tenant_id, job_id) for p in raw["visibility_plans"]]

                city_targeted = sum(1 for c in campaigns if c.get("cities"))
                logger.info(
                    f"parsed · {len(campaigns)} campaigns ({city_targeted} city-targeted) · "
                    f"{len(daily)} daily rows · {len(detail)} detail rows · "
                    f"{len(detail_days)} keyword-day rows · {budgets} budgets recorded · "
                    f"{len(keyword_bids)} keyword × match-type bid rows · sov {len(sov)} · "
                    f"collections {len(collections)} · plans {len(plans)}"
                )
                below = [r for r in keyword_bids
                         if r["match_type"] == "EXACT" and r.get("current_cpm") is not None
                         and r.get("min_bid") is not None and r["current_cpm"] < r["min_bid"]]
                if below:
                    logger.info(f"{len(below)} live EXACT bid(s) sit below Blinkit's published minimum")

                if save:
                    await save_scrape_results(db, campaigns, daily, detail, sov, collections,
                                              plans, keywords=keyword_bids,
                                              detail_days=detail_days)
                # Closed either way: a --no-save run used to leave this row `running`
                # forever (the phantom scrape_jobs of checklist A9).
                await complete_scrape_job(db, job_id)
                logger.info(f"done · {'saved' if save else 'not saved (--no-save)'} · {took(started)}")

            except typer.Exit:
                raise
            except AuthError:
                # Must escape the generic handler below. cli/main.py turns AuthError
                # into exit code 3, which the job runner records as `auth_expired` —
                # collapsing it into typer.Exit(1) here would bury every auth failure
                # among anonymous exit_1s, which is exactly how the seller breakage
                # went unnoticed for weeks.
                if job_id:
                    await fail_scrape_job(db, job_id, "auth_expired")
                logger.error("FAILED · login gone (auth_expired)")
                raise
            except Exception as e:
                # For DB errors, e.orig is the short asyncpg message; str(e) would dump
                # the entire (huge) statement + params, flooding the log.
                err = getattr(e, "orig", None) or e
                if job_id:
                    await fail_scrape_job(db, job_id, str(err))
                logger.error(f"FAILED · {err}")
                raise typer.Exit(1)


# ── Blinkit Seller ─────────────────────────────────────────────────────────────

@app.command("blinkit-seller")
def scrape_blinkit_seller(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    date_from: str = typer.Option(None, "--from", help="Sales start date YYYY-MM-DD (default: the 4 days up to --to)"),
    date_to: str = typer.Option(None, "--to", help="Sales end date YYYY-MM-DD (default: yesterday)"),
    sales: bool = typer.Option(False, "--sales", help="Scrape sales data"),
    po: bool = typer.Option(False, "--po", help="Scrape PO data"),
    soh: bool = typer.Option(False, "--soh", help="Scrape stock on hand"),
    po_days_back: int = typer.Option(90, "--po-days-back", help="Rolling window for PO fetch"),
    refetch_po_items: bool = typer.Option(
        False, "--refetch-po-items",
        help="Re-fetch line items for every PO in the window (one-time backfill of stale received qty)",
    ),
    save: bool = typer.Option(True, "--save/--no-save", help="Save results to MongoDB"),
):
    """Scrape Blinkit seller data. Pass --sales, --po, --soh, or none to run all three."""
    asyncio.run(_scrape_blinkit_seller(tenant_id, date_from, date_to, sales, po, soh, po_days_back, refetch_po_items, save))


# Blinkit seller sales: re-scrape the 4 days up to yesterday on every run (Deepansh,
# 2026-10-07; was yesterday only), so a failed or missed run heals on the next one — same
# reasoning as Zepto's re-scrape windows. A day missed 4 runs running needs a --from re-run.
BLINKIT_SALES_DAYS = 4


def _date_range(date_from: str | None, date_to: str | None) -> list[str]:
    """--from..--to; --to defaults to yesterday, --from to the BLINKIT_SALES_DAYS days up to
    --to (counted back from --to, so `--to` alone still gives a full window)."""
    end = _date.fromisoformat(date_to) if date_to else _date.today() - timedelta(days=1)
    start = (_date.fromisoformat(date_from) if date_from
             else end - timedelta(days=BLINKIT_SALES_DAYS - 1))
    days = (end - start).days + 1
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]


async def _scrape_blinkit_seller(
    tenant_id: str,
    date_from: str | None,
    date_to: str | None,
    sales_flag: bool,
    po_flag: bool,
    soh_flag: bool,
    po_days_back: int,
    refetch_po_items: bool,
    save: bool,
) -> None:
    """Logs follow scraper/utils/run_log.py: step lines tagged `blinkit·<tenant>·sales|po|soh`."""
    run_all = not sales_flag and not po_flag and not soh_flag
    run_sales = sales_flag or run_all
    run_po = po_flag or run_all
    run_soh = soh_flag or run_all
    saved = "saved" if save else "not saved (--no-save)"
    failed_days: list[str] = []

    async with AsyncSessionLocal() as db:
        slug = await tenant_slug(db, tenant_id)
        storage_state = (
            await auth_service.ensure(db, tenant_id, "blinkit_seller")
        ).storage_state

        # ── Sales (loops per day) ──────────────────────────────────────────────
        if run_sales:
            with tag("blinkit", slug, "sales"):
                days = _date_range(date_from, date_to)
                for day in days:
                    job_id = None
                    try:
                        job_id = await create_scrape_job(db, tenant_id, "blinkit_seller_sales")
                        raw = await seller_scraper.scrape(storage_state, day)

                        parsed_sales = [parse_sale_row(r, tenant_id, job_id, raw["date"]) for r in raw["sales"]]
                        summary = parse_sales_summary(raw, tenant_id, job_id, raw["date"])

                        if save:
                            await seller_save_results(db, parsed_sales, summary)
                        await complete_scrape_job(db, job_id)
                        logger.info(
                            f"{summary['date']} · {len(parsed_sales)} rows · "
                            f"{summary['distinct_skus']} SKUs · {summary['distinct_categories']} "
                            f"categories · {saved}"
                        )

                    except Exception as e:
                        if job_id:
                            await fail_scrape_job(db, job_id, str(e))
                        logger.error(f"{day} FAILED · {e}")
                        if len(days) == 1:
                            raise typer.Exit(1)
                        # One bad day must not cost the others — but it must fail the
                        # run (below, after PO and SOH): a multi-day window used to
                        # exit 0 here, which the runner recorded as success.
                        failed_days.append(day)

        # ── PO (runs once) ────────────────────────────────────────────────────
        if run_po:
            with tag("blinkit", slug, "po"):
                po_job_id = None
                try:
                    # po_number -> (po_state, total_grn_quantity) for the targeted
                    # item refetch: a changed GRN or non-terminal state means the
                    # line items may have moved and must be re-pulled.
                    known_pos: dict[str, tuple[str | None, int | None]] = {}
                    if save:
                        import uuid as _uuid
                        from sqlmodel import select as _select
                        from app.models.blinkit_seller import BlinkitPO as _BlinkitPO
                        rows = await db.execute(
                            _select(
                                _BlinkitPO.po_number,
                                _BlinkitPO.po_state,
                                _BlinkitPO.total_grn_quantity,
                            ).where(_BlinkitPO.tenant_id == _uuid.UUID(tenant_id))
                        )
                        known_pos = {pn: (state, grn) for pn, state, grn in rows.all()}
                    logger.info(
                        f"last {po_days_back} days · {len(known_pos)} POs already stored · "
                        + ("re-fetching all line items" if refetch_po_items
                           else "re-fetching changed / in-flight line items")
                    )

                    po_job_id = await create_scrape_job(db, tenant_id, "blinkit_seller_po")
                    raw_po = await seller_scraper.scrape_po(
                        storage_state,
                        po_days_back=po_days_back,
                        known_pos=known_pos,
                        refetch_all_items=refetch_po_items,
                    )

                    pos = [parse_po_row(r, tenant_id, po_job_id) for r in raw_po["pos"]]
                    po_items = [
                        parse_po_item(it, r["po_number"], tenant_id, po_job_id)
                        for r in raw_po["pos"]
                        for it in r.get("items", [])
                    ]
                    snapshot = parse_po_summary(
                        raw_po["po_summary"], tenant_id, po_job_id, raw_po["po_window_start"]
                    )

                    if save:
                        await save_po_results(db, pos, po_items, snapshot)
                    await complete_scrape_job(db, po_job_id)
                    logger.info(
                        f"{len(pos)} POs · {len(po_items)} line items · raised "
                        f"{snapshot.get('total_raised', 0)} · scheduled {snapshot.get('scheduled', 0)} · "
                        f"amount {rupees(snapshot.get('po_amount', 0))} · {saved}"
                    )

                except Exception as e:
                    if po_job_id:
                        await fail_scrape_job(db, po_job_id, str(e))
                    logger.error(f"FAILED · {e}")
                    raise typer.Exit(1)

        # ── SOH (runs once) ───────────────────────────────────────────────────
        if run_soh:
            with tag("blinkit", slug, "soh"):
                soh_job_id = None
                try:
                    soh_job_id = await create_scrape_job(db, tenant_id, "blinkit_seller_soh")
                    raw_soh = await seller_scraper.scrape_soh(storage_state)

                    rows = [parse_soh_row(r, tenant_id, soh_job_id, raw_soh["date"]) for r in raw_soh["rows"]]

                    if save:
                        await save_soh_results(db, rows)
                    await complete_scrape_job(db, soh_job_id)
                    logger.info(f"{raw_soh['date']} · {len(rows)} SKU × facility rows · {saved}")

                except Exception as e:
                    if soh_job_id:
                        await fail_scrape_job(db, soh_job_id, str(e))
                    logger.error(f"FAILED · {e}")
                    raise typer.Exit(1)

    if failed_days:
        with tag("blinkit", slug, "sales"):
            logger.error(f"{len(failed_days)} sales day(s) failed: {', '.join(failed_days)} — "
                         "re-run them with --from/--to")
        raise typer.Exit(1)


# ── Blinkit Seller Hub (seller.blinkit.com — NEW domain) ───────────────────────

@app.command("blinkit-seller-hub")
def scrape_blinkit_seller_hub(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    sales: bool = typer.Option(False, "--sales", help="Scrape sales data"),
    save: bool = typer.Option(True, "--save/--no-save", help="Save results to PostgreSQL"),
    window: str = typer.Option(
        seller_hub_scraper.DEFAULT_WINDOW, "--window", "-w",
        help='Time window, must be one of the account\'s own presets: "Last 7 days", '
             '"Last 30 days", or a named month like "September 2026" (for manual backfill '
             '— the account\'s filters list only goes back a few months; anything older '
             "isn't available from Blinkit at all).",
    ),
):
    """Scrape Blinkit's NEW seller dashboard (seller.blinkit.com/seller-hub) —
    for tenants Blinkit has migrated off partnersbiz.com (see `blinkit-seller`
    for everyone else). Currently sales-only; pass --sales or none runs it.

    Writes to blinkit_seller_hub_sales_by_product_ro and
    ..._sales_order_ro, NOT blinkit_seller_sales — the old dashboard's sales
    API can't produce this domain's grains at all. (Scope narrowed
    2026-10-01: the daily/city/category chart tables are no longer written —
    fully derivable from ..._sales_order_ro now; their old rows are left in
    place, untouched, just not updated.)

    Defaults to "Last 30 days", not the dashboard's own "Last 7 days" — real
    day-grain data either way (verified live), so a normal scheduled run
    now self-heals any gap under a month instead of losing missed days for
    good. Pass --window with a named month to manually backfill further back.
    """
    asyncio.run(_scrape_blinkit_seller_hub(tenant_id, sales, save, window))


async def _scrape_blinkit_seller_hub(tenant_id: str, sales_flag: bool, save: bool, window: str) -> None:
    # Sales is the only pillar built so far, so it always runs — --sales exists
    # now so a future pillar (Product Expansion, etc.) can gate behind it
    # without a breaking CLI change later.
    del sales_flag

    async with AsyncSessionLocal() as db:
        slug = await tenant_slug(db, tenant_id)
        with tag("blinkit", slug, "seller-hub"):
            session = await auth_service.ensure(db, tenant_id, "blinkit_seller_new")
            email = session.email
            if not email:
                logger.error("FAILED · no email on the blinkit_seller_new session")
                raise typer.Exit(1)
            if not session.storage_state or not session.storage_state.get("cookies"):
                logger.error(
                    "FAILED · no storage_state cookies on the blinkit_seller_new session — it "
                    "may never have completed a real login. Run `cli auth login blinkit_seller_new`."
                )
                raise typer.Exit(1)

            job_id = None
            try:
                job_id = await create_scrape_job(db, tenant_id, "blinkit_seller_hub_sales")
                try:
                    raw = await seller_hub_scraper.scrape_sales(
                        email, session.storage_state, time_range_filter=window
                    )
                except seller_hub_scraper.SessionDead as e:
                    # The probe passed but the scrape was logged out (Sereko,
                    # 2026-10-06). ensure() has already returned, so its auto-login
                    # never runs — force one here and retry once. A failed login
                    # raises and fails the job as before; the breaker still applies.
                    logger.warning(f"Seller-hub session died after its probe ({e}) — logging in again")
                    await auth_store.mark_failed(
                        db, tenant_id, "blinkit_seller_new", "logged out mid-scrape",
                        login_attempt=False,
                    )
                    session = await auth_service.login(db, tenant_id, "blinkit_seller_new", auto=True)
                    raw = await seller_hub_scraper.scrape_sales(
                        session.email or email, session.storage_state, time_range_filter=window
                    )

                by_product = parse_seller_hub_sales_by_product(
                    raw["products"], raw["window_label"], tenant_id, job_id
                )
                orders = parse_seller_hub_sales_orders(raw.get("orders") or [], tenant_id, job_id)

                written = 0
                if save:
                    written = await save_seller_hub_sales_results(db, by_product, orders)
                await complete_scrape_job(db, job_id, written)
                logger.info(
                    f"sales · {raw['window_label']} · {len(by_product)} product rows · "
                    f"{len(orders)} order rows · {'saved' if save else 'not saved (--no-save)'}"
                )
            except Exception as e:
                if job_id:
                    await fail_scrape_job(db, job_id, str(e))
                logger.error(f"FAILED · {e}")
                raise typer.Exit(1)


# ── Blinkit Scorecard ──────────────────────────────────────────────────────────

@app.command("blinkit-scorecard")
def scrape_blinkit_scorecard(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    week: str = typer.Option(None, "--week", help="Week start date YYYY-MM-DD (must be a Monday, default: last Monday)"),
    save: bool = typer.Option(True, "--save/--no-save", help="Save results to MongoDB"),
):
    """Scrape Blinkit scorecard (fill rates). Data refreshes every Monday."""
    asyncio.run(_scrape_blinkit_scorecard(tenant_id, week, save))


async def _scrape_blinkit_scorecard(tenant_id: str, week: str | None, save: bool) -> None:
    async with AsyncSessionLocal() as db:
        slug = await tenant_slug(db, tenant_id)
        with tag("blinkit", slug, "scorecard"):
            job_id = None
            try:
                storage_state = (
                    await auth_service.ensure(db, tenant_id, "blinkit_seller")
                ).storage_state

                job_id = await create_scrape_job(db, tenant_id, "blinkit_seller_scorecard")
                raw = await seller_scraper.scrape_scorecard(storage_state, week=week)

                manufacturer_id = raw["manufacturer_id"]
                from_date = raw["from_date_ist"]

                weekly = parse_scorecard_weekly(raw, tenant_id, job_id)
                facilities = [
                    parse_scorecard_facility(f, tenant_id, job_id, manufacturer_id, from_date)
                    for f in raw["facilities"]
                ]
                key_skus = [
                    parse_scorecard_key_sku(s, tenant_id, job_id, manufacturer_id, from_date)
                    for s in raw["key_skus"]
                ]

                if save:
                    await save_scorecard_results(db, weekly, facilities, key_skus)
                await complete_scrape_job(db, job_id)
                overall = weekly.get("overall", {})
                logger.info(
                    f"week of {weekly['from_date_ist']} · fill {overall.get('fill_rate', 0):.1f}% · "
                    f"weighted {overall.get('weighted_fill_rate_percent', 0):.1f}% · "
                    f"rank {overall.get('manufacturer_rank', '—')} · {len(facilities)} facilities · "
                    f"{len(key_skus)} key SKUs · {'saved' if save else 'not saved (--no-save)'}"
                )

            except typer.Exit:
                raise
            except AuthError:
                # See the note in _scrape_blinkit — must not collapse into exit 1.
                if job_id:
                    await fail_scrape_job(db, job_id, "auth_expired")
                logger.error("FAILED · login gone (auth_expired)")
                raise
            except Exception as e:
                if job_id:
                    await fail_scrape_job(db, job_id, str(e))
                logger.error(f"FAILED · {e}")
                raise typer.Exit(1)


# ── Public search scraping ────────────────────────────────────────────────────

@app.command("public")
def scrape_public(
    keyword: str = typer.Option(..., "--keyword", "-k", help="Search keyword (e.g. 'cola', 'sunflower oil')"),
    brand: str = typer.Option(..., "--brand", "-b", help="Brand slug for classification (e.g. 'dobra')"),
    city: str = typer.Option("bengaluru", "--city", "-c", help="City name from the store catalogue (`cli locations list`)"),
    platform: str = typer.Option("all", "--platform", "-p", help="Platform: blinkit (zepto and instamart are local-first: use public-run)"),
    aliases: Optional[str] = typer.Option(None, "--aliases", help="Comma-separated brand name aliases (e.g. 'dobra,dobra cola')"),
    tenant_id: str = typer.Option(None, "--tenant", "-t", help="Tenant (client) UUID — required to --save (per-tenant storage)"),
    save: bool = typer.Option(False, "--save/--no-save", help="Save results to PostgreSQL (requires --tenant)"),
):
    """Scrape public product search results — no login required.

    ONE keyword at ONE store, for a quick look. The store is a real one from the
    catalogue (the lowest merchant_id in the city), not a hardcoded coordinate.

    The `--all-zones` flag was removed with `scraper/utils/cities.py` (2026-09-04): it
    iterated that file's placeholder zone lists, and the catalogue's equivalent is every
    store in the city — 162 in Bengaluru, which is a full run, not an ad-hoc look. Use
    `cli scrape public-run` for that, or `cli explore` for an ad-hoc multi-city sweep.

    Without --save it just scrapes and prints (no tenant needed). With --save it
    writes per-tenant header+detail rows (search_snapshots + search_listings) and
    opens a scrape_job, so --tenant is required.
    """
    alias_list = [a.strip() for a in aliases.split(",")] if aliases else None
    asyncio.run(_scrape_public(keyword, brand, city, platform, alias_list, tenant_id, save))


async def _scrape_public(
    keyword: str,
    brand_slug: str,
    city_slug: str,
    platform: str,
    aliases: list[str] | None,
    tenant_id: str | None,
    save: bool,
) -> None:
    from scraper.utils.locations import resolve_city, city_names
    from scraper.platforms.blinkit.public_data import scraper as bl_scraper, parser as bl_parser, storage as bl_storage

    # Zepto and Instamart are deliberately NOT here. This command writes straight
    # to Postgres, which is the opposite of the local-first staging path both are
    # built on (scrape -> SQLite -> `cli scrape load`), and ad-hoc one-off queries
    # are already served by the Explorer. Supporting them here would mean a
    # second, divergent write path for the same data. (Instamart was listed until
    # 2026-09-17, backed by a scraper that hit swiggy.com and a storage module that
    # was a no-op — it never wrote a row.)
    SUPPORTED = {"blinkit"}
    LOCAL_FIRST = {"zepto", "instamart"}

    platforms_to_run = ["blinkit"] if platform == "all" else [platform]
    local_first = [p for p in platforms_to_run if p in LOCAL_FIRST]
    if local_first:
        mp = local_first[0]
        console.print(
            f"[red]{mp} is not supported by this command.[/red]\n"
            f"  It writes directly to Postgres; the {mp} public scrape is "
            "local-first.\n"
            f"  Use  [cyan]cli scrape public-run -m {mp} --city <city>[/cyan]  "
            "for a real run,\n"
            "  or the Explorer for an ad-hoc one-off."
        )
        raise typer.Exit(1)
    invalid = [p for p in platforms_to_run if p not in SUPPORTED]
    if invalid:
        console.print(f"[red]Unknown platform(s): {', '.join(invalid)}[/red]")
        raise typer.Exit(1)

    scrapers = {
        "blinkit": (bl_scraper, bl_parser, bl_storage),
    }

    if save and not tenant_id:
        console.print("[red]--tenant is required with --save (storage is per-tenant).[/red]")
        raise typer.Exit(1)

    async with AsyncSessionLocal() as db:
        job_id = None
        rows_written = 0
        if save:
            job_id = await create_scrape_job(db, tenant_id, "public_search", "blinkit")

        try:
            for plat in platforms_to_run:
                # The store comes from the catalogue, per marketplace — so "not available"
                # now means we genuinely hold no active store for that pair, rather than
                # a hardcoded table's opinion. Instamart has no catalogue rows at all,
                # which this reports honestly instead of scraping an invented point.
                store = await resolve_city(db, plat, city_slug)
                if store is None:
                    known = await city_names(db, plat)
                    if known:
                        console.print(
                            f"  [dim]{plat}: no active store in '{city_slug}'. "
                            f"{len(known)} cities available, e.g. "
                            f"{', '.join(known[:6])}…[/dim]"
                        )
                    else:
                        console.print(
                            f"  [dim]{plat}: no stores in the catalogue at all — "
                            f"nothing to scrape. Populate it with `cli sync`.[/dim]"
                        )
                    continue

                scraper_mod, parser_mod, storage_mod = scrapers[plat]
                area = store.location_name or store.city
                console.print(
                    f"\n[bold cyan]{store.city} — {area}[/bold cyan]  "
                    f"[dim]{plat} · store {store.merchant_id}[/dim]"
                )

                with console.status(f"  [cyan]Scraping {plat}…[/cyan]"):
                    raw = await scraper_mod.scrape(
                        keyword=keyword,
                        brand_slug=brand_slug,
                        city_slug=store.city,
                        zone=area,
                        pincode=store.pincode or "",
                        lat=store.lat,
                        lon=store.lon,
                        aliases=aliases,
                    )
                result = parser_mod.parse(raw)
                _print_public_result(plat, result)

                if save:
                    rows_written += await storage_mod.save(db, result, tenant_id, job_id)

            if save:
                await complete_scrape_job(db, job_id, rows_written)
                console.print(f"\n[green]Saved {rows_written} rows[/green] (job {job_id})")
        except Exception as e:
            if save and job_id:
                await fail_scrape_job(db, job_id, str(e))
            raise


def _validate_marketplace(mp: str) -> str:
    """Normalise + check a --marketplace value against the wired providers.

    Fails fast rather than falling back: a typo'd marketplace silently scraping
    Blinkit would write real rows under the wrong platform.
    """
    from scraper.public import providers

    slug = (mp or "").strip().lower()
    try:
        providers.get_provider(slug)
    except ValueError as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1)
    return slug


@app.command("public-run")
def public_run(
    tenant_id: str = typer.Option(None, "--tenant", "-t", help="Tenant (client) UUID — omit with --all"),
    all_tenants: bool = typer.Option(False, "--all", help="Run every active tenant"),
    marketplace: str = typer.Option(..., "--marketplace", "-m", help="Marketplace to scrape: blinkit | zepto | instamart (required — never assumed)"),
    cap: int = typer.Option(None, "--cap", help="Max products per search (default: tenant keyword_cap, else the platform floor)"),
    keyword: str = typer.Option(None, "--keyword", "-k", help="Only this keyword (subset of the watchlist)"),
    city: str = typer.Option(None, "--city", "-c", help="Only locations in this city slug"),
    resume: bool = typer.Option(False, "--resume", help="Continue this tenant's last incomplete run on this marketplace (skip already-scraped stores)"),
    workers: int = typer.Option(5, "--workers", "-w", help="Concurrent browser workers (pool size). ~5–6 for Blinkit. Ignored on Zepto, which is single-worker by design."),
    no_load: bool = typer.Option(False, "--no-load", help="Stage only; don't push to the database afterwards"),
):
    """Orchestrate a tenant's full watchlist (keywords × locations), all sourced
    from the DB (watchlist + tenant_locations). Writes per-tenant snapshot+listing
    rows under one scrape_job per tenant. --marketplace selects the platform (its
    locations, its engine). --keyword/--city narrow a run to a single keyword or
    city. --resume picks up an interrupted run. --workers sets the concurrent
    browser pool size.
    """
    if not tenant_id and not all_tenants:
        console.print("[red]Provide --tenant <id> or --all.[/red]")
        raise typer.Exit(1)
    if resume and all_tenants:
        console.print("[red]--resume works with a single --tenant, not --all.[/red]")
        raise typer.Exit(1)
    mp = _validate_marketplace(marketplace)
    asyncio.run(_public_run(tenant_id, all_tenants, cap, keyword, city, resume, workers, no_load, mp_slug=mp))


async def _auto_load(summary: dict, no_load: bool) -> None:
    """Push one finished scrape's staging file into Postgres, inline.

    Called right after each tenant's scrape (including inside a --all sweep, via the
    orchestrator's on_tenant_done hook) so a later tenant failing can never strand an
    earlier tenant's data. Deliberately NON-FATAL: the rows are already safe on disk,
    so a load failure leaves the file pending and prints the recovery command rather
    than failing the run.

    Only clean runs auto-load. A crashed/partial run still holds real data, but
    sweeping it in unnoticed is the accident worth avoiding — same rule
    `scrape load --all` follows. See docs/staging.md.
    """
    if no_load:
        return
    name = summary.get("staging_file")
    if not name:
        return

    from scraper.public import loader, staging

    if summary.get("status") != "success":
        # `partial` = stores left unattempted or coverage under the floor; `failed` =
        # nothing scraped. Either way the file stays on disk: --resume finishes it,
        # and only a finished run is pushed without a human looking at it.
        ref = staging.ref(name)
        console.print(
            f"[yellow]Not auto-loading {name}[/yellow] — the run is "
            f"[bold]{summary.get('status')}[/bold]: {escape(summary.get('note') or '')}"
        )
        console.print(
            f"  continue it : re-run the same command with [bold]--resume[/bold]\n"
            f"  load as-is  : [bold]python -m cli scrape load --file {ref}[/bold]\n"
            f"  throw away  : [bold]python -m cli scrape discard --file {ref}[/bold]"
        )
        return

    try:
        path = staging.resolve(name)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Auto-load skipped:[/red] {escape(str(e))}")
        return

    console.print(f"[dim]Loading {name} into the database…[/dim]")
    try:
        res = await loader.load_with_retry(path)
    except Exception as e:
        err = getattr(e, "orig", None) or e
        console.print(f"[red]Auto-load FAILED:[/red] {escape(str(err))[:300]}")
        console.print(
            f"[dim]Nothing was written; the scrape is safe on disk. Retry with "
            f"[/dim][bold]python -m cli scrape load --file {staging.ref(path)}[/bold]"
        )
        return
    console.print(
        f"[green]Loaded[/green] {res['total']:,} rows "
        f"({res['snapshots']:,} snapshots, {res['listings']:,} listings, "
        f"{res['skus']:,} sku rows)"
    )


async def _public_run(
    tenant_id: str | None, all_tenants: bool, cap: int | None,
    keyword: str | None, city: str | None, resume: bool, workers: int,
    no_load: bool = False, *, mp_slug: str,
) -> None:
    from scraper.public import orchestrator

    async def _after(summary: dict) -> None:
        await _auto_load(summary, no_load)

    async with AsyncSessionLocal() as db:
        if all_tenants:
            # Load each tenant the moment its scrape finishes, not at the end of the
            # sweep — on a weekly scheduled run, tenant 7 failing must not strand the
            # six already scraped.
            summaries = await orchestrator.run_all(
                db, cap, keyword, city, workers, on_tenant_done=_after, mp_slug=mp_slug
            )
        else:
            summaries = [await orchestrator.run_tenant(
                db, tenant_id, cap, keyword, city, resume, workers, mp_slug=mp_slug
            )]
            await _after(summaries[0])

    if not summaries:
        console.print("[yellow]No active tenants to run.[/yellow]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Tenant")
    table.add_column("MP")
    table.add_column("Keywords", justify="right")
    table.add_column("Locations", justify="right")
    table.add_column("Snapshots", justify="right")
    table.add_column("Rows", justify="right")
    _public_outcome_columns(table)
    for s in summaries:
        table.add_row(
            s["tenant_id"][:8], s.get("mp_slug", mp_slug),
            str(s["keywords"]), str(s["locations"]),
            str(s["snapshots"]), str(s["rows"]),
            *_public_outcome_cells(s),
        )
    console.print(table)
    _exit_on_public_outcome(summaries)


def _public_outcome_columns(table: Table) -> None:
    """The columns that say whether a public scrape is WHOLE — shared by the keyword
    and own-SKU summaries so the two read the same way."""
    table.add_column("Coverage", justify="right")
    table.add_column("Blocked", justify="right")
    table.add_column("Errors", justify="right")
    table.add_column("Missing", justify="right")
    table.add_column("Status")


def _public_outcome_cells(s: dict) -> list[str]:
    """Coverage · blocked · errors · missing · status for one run summary.

    `Missing` is the only column that means data is absent: pairs that failed even
    after the backlog retry, plus whole stores no worker lived to reach. `Blocked`
    (rate limits waited out) and `Errors` (failed requests, often recovered by the
    backlog pass) cost time, not necessarily data."""
    status = s.get("status") or "?"
    colour = {"success": "green", "skipped": "dim", "partial": "yellow",
              "failed": "red"}.get(status, "yellow")
    cov = s.get("coverage_pct")
    blocked = str(s.get("blocked", 0))
    by_kind = s.get("blocks_by_kind") or {}
    if by_kind:
        # Which mechanism, not just how many — the three want different remedies.
        blocked += " (" + ", ".join(
            f"{k} {n}" for k, n in sorted(by_kind.items(), key=lambda kv: -kv[1])) + ")"
    missing = []
    if s.get("unrecovered"):
        missing.append(f"{s['unrecovered']:,} pairs")
    if s.get("unattempted"):
        missing.append(f"{s['unattempted']:,} stores")
    return [
        "[dim]—[/dim]" if cov is None else f"{cov}%",
        blocked,
        str(s.get("errors", 0)),
        f"[red]{' + '.join(missing)}[/red]" if missing else "0",
        f"[{colour}]{status}[/{colour}]",
    ]


def _exit_on_public_outcome(summaries: list[dict]) -> None:
    """Exit non-zero unless every run was a clean success (or had nothing to do).

    The runner supervises this command as a subprocess and sees ONLY its exit code.
    Exiting 0 regardless is what let a scrape that reached 0 of 169 stores show green
    in the jobs table — so no alert, and no overdue-schedule warning either. `partial`
    gets its own code so the jobs table can say so."""
    from scraper.public import outcome

    code = outcome.exit_code([s.get("status") for s in summaries])
    if code:
        raise typer.Exit(code)


@app.command("public-skus")
def public_skus(
    tenant_id: str = typer.Option(None, "--tenant", "-t", help="Tenant (client) UUID — omit with --all"),
    all_tenants: bool = typer.Option(False, "--all", help="Run every active tenant"),
    marketplace: str = typer.Option(..., "--marketplace", "-m", help="Marketplace to scrape: blinkit | zepto | instamart (required — never assumed)"),
    cap: int = typer.Option(None, "--brand-cap", help="Override brand_cap for this run (default: per-tenant, else the platform floor)"),
    city: str = typer.Option(None, "--city", "-c", help="Only locations in this city slug"),
    resume: bool = typer.Option(False, "--resume", help="Continue this tenant's last incomplete run on this marketplace (skip scraped stores)"),
    workers: int = typer.Option(5, "--workers", "-w", help="Concurrent browser workers (pool size). Ignored on Zepto, which is single-worker by design."),
    no_load: bool = typer.Option(False, "--no-load", help="Stage only; don't push to the database afterwards"),
):
    """Targeted own-SKU scrape: search each tenant's brand name, paginate its whole
    catalog, and write per-product rows to sku_snapshots (price/mrp/discount/stock/
    inventory/rating), keyed on product_id. Complements `public-run` (which covers
    SoV/rank + competitors). --marketplace selects the platform. --resume picks up
    an interrupted run.
    """
    if not tenant_id and not all_tenants:
        console.print("[red]Provide --tenant <id> or --all.[/red]")
        raise typer.Exit(1)
    if resume and all_tenants:
        console.print("[red]--resume works with a single --tenant, not --all.[/red]")
        raise typer.Exit(1)
    mp = _validate_marketplace(marketplace)
    asyncio.run(_public_skus(tenant_id, all_tenants, cap, city, resume, workers, no_load, mp_slug=mp))


async def _public_skus(
    tenant_id: str | None, all_tenants: bool, cap: int | None,
    city: str | None, resume: bool, workers: int, no_load: bool = False,
    *, mp_slug: str,
) -> None:
    from scraper.public import targeted

    async def _after(summary: dict) -> None:
        await _auto_load(summary, no_load)

    async with AsyncSessionLocal() as db:
        if all_tenants:
            summaries = await targeted.run_all_targeted(
                db, cap, city, workers, on_tenant_done=_after, mp_slug=mp_slug
            )
        else:
            summaries = [await targeted.run_targeted(
                db, tenant_id, cap, city, resume, workers, mp_slug=mp_slug
            )]
            await _after(summaries[0])

    if not summaries:
        console.print("[yellow]No active tenants to run.[/yellow]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Tenant")
    table.add_column("MP")
    table.add_column("Brands", justify="right")
    table.add_column("Locations", justify="right")
    table.add_column("SKU Rows", justify="right")
    _public_outcome_columns(table)
    for s in summaries:
        table.add_row(
            s["tenant_id"][:8], s.get("mp_slug", mp_slug),
            str(s["brands"]), str(s["locations"]),
            str(s["rows"]),
            *_public_outcome_cells(s),
        )
    console.print(table)
    _exit_on_public_outcome(summaries)


def _print_public_result(platform: str, result: dict) -> None:
    sov = result.get("brand_sov_pct", 0)
    rank = result.get("brand_rank")
    total = result.get("total_results", 0)
    brand_count = result.get("brand_product_count", 0)

    rank_str = f"#{rank}" if rank else "not ranked"
    colour = "green" if sov >= 20 else ("yellow" if sov >= 5 else "red")

    console.print(
        f"  [bold]{platform}[/bold]  "
        f"total={total}  brand={brand_count}  "
        f"rank={rank_str}  sov=[{colour}]{sov}%[/{colour}]"
    )

    brand_prods = result.get("brand_products", [])
    if brand_prods:
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("#", style="dim", width=4)
        table.add_column("Product")
        table.add_column("Price", justify="right")
        for p in brand_prods:
            price_str = f"₹{p['price']:.0f}" if p.get("price") else "—"
            table.add_row(str(p.get("position", "")), p.get("name", ""), price_str)
        console.print(table)

    comps = result.get("competitors", [])[:3]
    if comps:
        comp_names = ", ".join(f"{c['name']} ({c['count_in_results']})" for c in comps)
        console.print(f"  [dim]Top competitors: {comp_names}[/dim]")


# ── Staging: local SQLite → Postgres ─────────────────────────────────────────

@app.command("staged")
def staged_list(
    pending_only: bool = typer.Option(False, "--pending", help="Only runs not yet loaded"),
    marketplace: str = typer.Option(None, "--marketplace", "-m", help="Only runs from this marketplace"),
):
    """List local staging files from public scrapes (what `scrape load` would push).

    Public scrapes write to a local SQLite file, not straight to Postgres — a long
    run no longer dies with the database. See docs/staging.md.
    """
    from scraper.public import staging

    mp = (marketplace or "").strip().lower() or None
    runs = staging.pending(mp_slug=mp) if pending_only else staging.list_runs(mp_slug=mp)
    if not runs:
        console.print("[dim]No staging files.[/dim]")
        return

    table = Table(show_header=True, header_style="bold",
                  title=f"Staging files — {len(runs)}")
    table.add_column("Date")
    table.add_column("Time")
    table.add_column("MP")
    table.add_column("Kind")
    table.add_column("Stores", justify="right")
    # Pairs answered ÷ pairs the run set out to do. "Stores" alone cannot say a run
    # is whole — a store counts after ONE keyword. Blank on files staged before the
    # pair counts existed.
    table.add_column("Cover", justify="right")
    table.add_column("Rows", justify="right")
    table.add_column("Err", justify="right")
    table.add_column("State")
    table.add_column("Ref", style="dim")
    for r in runs:
        started, loaded = r["started_at"] or "", r["loaded_at"]
        date, _, tm = started.partition("T")
        done, want = r.get("stores_done"), r.get("stores_total")
        stores = f"{done:,}/{want:,}" if done is not None and want else (
            f"{done:,}" if done is not None else "[dim]—[/dim]")
        # A partial run is not automatically bad — 500 of 2059 stores is still 500
        # stores of real data. Flag it, let the human decide.
        if done is not None and want and done < want:
            stores = f"[yellow]{stores}[/yellow]"
        errs = r.get("errors")
        err_txt = "[dim]—[/dim]" if errs is None else (
            f"[red]{errs:,}[/red]" if errs else "0")
        status = {"success": "[green]ok[/green]", "failed": "[red]failed[/red]"} \
            .get(r["status"], f"[yellow]{r['status']}[/yellow]")
        where = "[green]loaded[/green]" if loaded else "[yellow]pending[/yellow]"
        p_done, p_want = r.get("pairs_done"), r.get("pairs_total")
        cover = "[dim]—[/dim]"
        if p_done is not None and p_want:
            pct = round(p_done / p_want * 100, 1)
            cover = f"{pct}%" if r["status"] == "success" else f"[yellow]{pct}%[/yellow]"
        table.add_row(
            date, tm[:5], r["mp_slug"],
            r["kind"].replace("public_", ""),
            stores, cover, f"{r['rows']:,}", err_txt,
            f"{status} · {where}",
            staging.ref(r["path"]),
        )
    console.print(table)
    n_pending = sum(1 for r in runs if not r["loaded_at"])
    n_bad = sum(1 for r in runs if not r["loaded_at"] and r["status"] != "success")
    if n_pending:
        console.print(f"[yellow]{n_pending} file(s) not yet in the database.[/yellow] "
                      f"Push with [bold]python -m cli scrape load[/bold]")
    if n_bad:
        console.print(
            f"[red]{n_bad} pending file(s) did not finish cleanly.[/red] Finish one by "
            f"re-running its scrape with [bold]--resume[/bold], or review before loading — "
            f"drop one with [bold]python -m cli scrape discard --file <name>[/bold]"
        )


@app.command("load")
def load_staged(
    file: str = typer.Option(None, "--file", "-f", help="Which file — the Ref from `scrape staged` (default: all pending, oldest first)"),
    all_pending: bool = typer.Option(False, "--all", help="Load every pending file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be loaded, write nothing"),
    keep: int = typer.Option(None, "--keep", help=f"Loaded files to retain per tenant+kind+marketplace (default {5})"),
):
    """Push staged public-scrape results into Postgres.

    Each file is loaded in ONE all-or-nothing transaction: if the connection drops
    the whole thing rolls back and nothing is written, so re-running is always safe
    (public data is append-only with no upsert — a partial load would duplicate).

    With no --file, loads every pending file oldest-first.
    """
    from scraper.public import staging

    if file:
        try:
            path = staging.resolve(file)
        except (FileNotFoundError, ValueError) as e:
            console.print(f"[red]{escape(str(e))}[/red]")
            console.print("[dim]List them with `python -m cli scrape staged`.[/dim]")
            raise typer.Exit(1)
        # Carry the run row and counts, not just the path. Without them --dry-run
        # renders every column as "?" / 0 for a --file target no matter what the
        # file holds — which reads as "this file is empty" and invites discarding
        # a good run. The load itself only needs the path; the preview needs the
        # rest to be worth anything.
        targets = [next((r for r in staging.all_runs() if r["path"] == path),
                        {"path": path})]
    else:
        targets = list(reversed(staging.pending()))   # oldest first
        if not targets:
            console.print("[dim]Nothing pending — all staging files are loaded.[/dim]")
            return
        if len(targets) > 1 and not all_pending and not dry_run:
            console.print(
                f"[yellow]{len(targets)} files pending.[/yellow] "
                f"Pass --all to load them all, or --file <name> for one:"
            )
            for t in targets:
                console.print(f"   {t['path'].name}  ({t['rows']:,} rows)")
            raise typer.Exit(1)
        # A run that crashed may still hold data worth keeping, so this is never an
        # automatic skip — but sweeping one into the DB unnoticed via --all is the
        # exact accident worth blocking. Force a deliberate choice.
        unclean = [t for t in targets if t.get("status") != "success"]
        if unclean and not dry_run:
            console.print(
                f"[red]{len(unclean)} pending file(s) did not finish cleanly:[/red]"
            )
            for t in unclean:
                done, want = t.get("stores_done"), t.get("stores_total")
                cover = f", {done}/{want} stores" if done is not None and want else ""
                console.print(
                    f"   [red]{t['status']}[/red]  {t['path'].name}  "
                    f"({t['rows']:,} rows{cover}, {t.get('errors') or 0} errors)"
                )
            console.print(
                "\nPartial data is often still worth loading — but decide per file:\n"
                "  [bold]python -m cli scrape load --file <name>[/bold]     load it anyway\n"
                "  [bold]python -m cli scrape discard --file <name>[/bold]  throw it away"
            )
            raise typer.Exit(1)

    if dry_run:
        table = Table(show_header=True, header_style="bold", title="DRY RUN — nothing written")
        table.add_column("File")
        table.add_column("MP")
        table.add_column("Kind")
        table.add_column("Snapshots", justify="right")
        table.add_column("Listings", justify="right")
        table.add_column("SKU rows", justify="right")
        for t in targets:
            c = t.get("counts") or {}
            table.add_row(t["path"].name, t.get("mp_slug", "?"), t.get("kind", "?"),
                          f"{c.get('search_snapshots', 0):,}",
                          f"{c.get('search_listings', 0):,}",
                          f"{c.get('sku_snapshots', 0):,}")
        console.print(table)
        return

    asyncio.run(_load_staged([t["path"] for t in targets], keep))


async def _load_staged(paths, keep) -> None:
    from scraper.public import loader, staging

    if keep is not None:
        staging.KEEP_PER_KIND = keep

    from sqlalchemy.exc import DBAPIError

    results, failed = [], []
    for p in paths:
        console.print(f"[dim]Loading {p.name} …[/dim]")
        # Retry once on a DB-level failure. Safe by construction: the load is one
        # all-or-nothing transaction, so a failed attempt wrote nothing. Each attempt
        # gets a FRESH session — a dropped connection can't be reused, and the old
        # session's pool entry is poisoned.
        for attempt in (1, 2):
            try:
                async with AsyncSessionLocal() as db:
                    results.append(await loader.load_file(db, p))
                break
            except DBAPIError as e:
                err = getattr(e, "orig", None) or e
                if attempt == 1:
                    console.print(
                        f"[yellow]Connection failed — retrying once:[/yellow] "
                        f"{escape(str(err))[:120]}"
                    )
                    continue
                failed.append((p.name, str(err)))
                console.print(f"[red]FAILED[/red] {p.name}: {escape(str(err))[:300]}")
                console.print("[dim]Nothing was written — rerun the same command to retry.[/dim]")
            except Exception as e:
                failed.append((p.name, str(e)))
                console.print(f"[red]FAILED[/red] {p.name}: {escape(str(e))[:300]}")
                console.print("[dim]Nothing was written — rerun the same command to retry.[/dim]")
                break

    if results:
        table = Table(show_header=True, header_style="bold", title="Loaded")
        table.add_column("File")
        table.add_column("MP")
        table.add_column("Kind")
        table.add_column("Snapshots", justify="right")
        table.add_column("Listings", justify="right")
        table.add_column("SKU rows", justify="right")
        table.add_column("Total", justify="right")
        for r in results:
            table.add_row(r["file"], r["mp_slug"], r["kind"], f"{r['snapshots']:,}",
                          f"{r['listings']:,}", f"{r['skus']:,}", f"{r['total']:,}")
        console.print(table)
        pruned = sum(r["pruned"] for r in results)
        if pruned:
            console.print(f"[dim]Pruned {pruned} old staging file(s).[/dim]")
    if failed:
        console.print(f"[red]{len(failed)} file(s) failed to load.[/red]")
        raise typer.Exit(1)


@app.command("discard")
def discard_staged(
    file: str = typer.Option(..., "--file", "-f", help="Which file — the Ref from `scrape staged`, or a filename/path"),
    force: bool = typer.Option(False, "--force", help="Skip the confirmation prompt"),
):
    """Delete a staging file without loading it.

    For a file that was never loaded this destroys scraped data held nowhere else —
    hence the prompt. Use it to drop a bad run (wrong city, wrong cap, a crash that
    produced nothing useful) so `scrape load --all` can't sweep it into the database.
    """
    from scraper.public import staging

    try:
        path = staging.resolve(file)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        console.print("[dim]List them with `python -m cli scrape staged`.[/dim]")
        raise typer.Exit(1)

    match = next((r for r in staging.list_runs() if r["path"].resolve() == path.resolve()), None)
    if match is None:
        console.print(f"[red]{path.name} is not a readable staging file.[/red]")
        raise typer.Exit(1)

    loaded = match["loaded_at"]
    console.print(
        f"\n  [bold]{path.name}[/bold]\n"
        f"  kind    : {match['kind']}\n"
        f"  scraped : {(match['started_at'] or '').replace('T', ' ')[:16]}\n"
        f"  status  : {match['status']}   errors: {match.get('errors') or 0}\n"
        f"  rows    : {match['rows']:,}\n"
        f"  loaded  : {'yes — ' + loaded[:16].replace('T', ' ') if loaded else 'NO'}\n"
    )
    if loaded:
        console.print("[dim]Already in the database — deleting only removes the local backup.[/dim]")
    else:
        console.print(
            f"[red]NOT loaded.[/red] These {match['rows']:,} rows exist nowhere else — "
            f"deleting is irreversible."
        )
    if not force and not typer.confirm("Delete this file?"):
        console.print("[dim]Cancelled.[/dim]")
        raise typer.Exit(0)

    staging.discard(path)
    console.print(f"[green]Deleted[/green] {path.name}")



# ── Zepto (one seller console: sales, PO, ads) ───────────────────────────────

@app.command("zepto")
def scrape_zepto(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    date_from: str = typer.Option(None, "--from", help="Sales/ads start date YYYY-MM-DD (default: sales 4 days ago; ads the 3 days up to --to)"),
    date_to: str = typer.Option(None, "--to", help="Sales/ads end date YYYY-MM-DD (default: yesterday)"),
    sales: bool = typer.Option(False, "--sales", help="Scrape sales data"),
    po: bool = typer.Option(False, "--po", help="Scrape PO/ASN/GRN data"),
    ads: bool = typer.Option(False, "--ads", help="Scrape ads data"),
    category: str = typer.Option(
        "all", "--category",
        help=(
            "Ads only: sponsored_products | sponsored_display | sponsored_brands "
            "| all. Leave at 'all' — the three tabs return DISJOINT campaigns, so "
            "anything narrower silently drops the others' spend."
        ),
    ),
    po_days_back: int = typer.Option(
        30, "--po-days-back",
        help=(
            "Rolling window for the PO fetch, counted back from TODAY. Separate "
            "from --from/--to because POs are forward-looking: an order raised "
            "today expires in three weeks, so the PO window must include today "
            "while the sales window stops at yesterday."
        ),
    ),
    all_cities: bool = typer.Option(False, "--all-cities", help="Sales: sweep every city on every day (a one-off backfill; every run already sweeps the newest day)"),
    save: bool = typer.Option(True, "--save/--no-save", help="Save results to PostgreSQL"),
):
    """Scrape ALL Zepto private data. Pass --sales, --po, --ads, or none for all three.

    THE Zepto command. Blinkit needs separate commands because it has two
    dashboards behind two separate logins; Zepto has ONE console covering sales,
    PO and ads, so it gets one command — and one login, which matters because
    each Zepto login logs out whoever is on the client's Zepto dashboard.

    The work happens in scraper/platforms/zepto/dashboard_data/seller/run.py;
    this command only parses flags, prints each section's report and turns the
    results into the exit code: 0 = everything landed, 1 = a section failed or
    lost fetches (what came back is still saved), 3 = the login is gone.

    The sections keep their own windows on purpose: sales (the 4 days) and ads (the
    3 days up to --to) stop at yesterday, because Zepto computes a day once each
    morning; PO runs --po-days-back through TODAY, because POs are
    forward-looking. A section that fails does not stop the others.
    """
    try:
        results = asyncio.run(_scrape_zepto(
            tenant_id, date_from, date_to, sales, po, ads, po_days_back,
            category, all_cities, save,
        ))
    except AuthError as e:
        # ⚠️ This duplicates cli/main.py's global AuthError handler ON PURPOSE,
        # because that handler never runs. It sits behind
        # `if __name__ == "__main__"`, and `python -m cli` executes
        # cli/__main__.py — which does `from cli.main import app; app()` — so
        # cli/main.py is imported as a module and the guard is never true.
        # Measured: 0 jobs with exit_code 3 and 0 with error='auth_expired'
        # across 6,094 runs. Every auth failure had been landing as an
        # anonymous exit 1.
        #
        # Scoped to Zepto deliberately. Fixing the global path is a one-line
        # change to cli/__main__.py, but it alters how EVERY command surfaces
        # exceptions — including Blinkit's, which is live production on the VM.
        logger.error(
            f"AUTH FAILURE — the Zepto scrape could not authenticate ({type(e).__name__}: {e}). "
            "Check: cli auth status -t <tenant> · Fix: cli auth login zepto -t <tenant> "
            "(or cli auth reset zepto -t <tenant> if the breaker is open)"
        )
        raise typer.Exit(AUTH_EXPIRED_EXIT_CODE)

    # A run that lost anything must not exit 0. The alert only ever sees the exit
    # code: it fires on the RUNNER's own log (`log_id("foresight_runner") AND
    # severity>=ERROR`), and a scraper's output ships with no severity field at all
    # (deploy/ops-agent-logging.yaml) — so the runner's "job exited non-zero" ERROR
    # is the only route to it.
    if any(not r.ok for r in results):
        raise typer.Exit(1)


async def _scrape_zepto(
    tenant_id: str, date_from: str | None, date_to: str | None,
    sales: bool, po: bool, ads: bool, po_days_back: int,
    category: str, all_cities: bool, save: bool,
) -> list:
    """No spinner, no printed report: the run's log IS the output
    (scraper/utils/run_log.py)."""
    run_all = not (sales or po or ads)
    return await zepto_run.run(
        tenant_id,
        sales=sales or run_all, po=po or run_all, ads=ads or run_all,
        date_from=date_from, date_to=date_to, po_days_back=po_days_back,
        category=category, all_cities=all_cities, save=save,
    )


def _why(e: Exception) -> str:
    """A readable reason for a failed section (used by the Instamart command).

    typer.Exit stringifies to its exit code — "1" — which told the reader
    nothing. A section that raised it has already printed and logged its own
    reason, so say that rather than repeating a bare number.
    """
    if isinstance(e, typer.Exit):
        return "section reported failure (see its own error above)"
    return str(getattr(e, "orig", None) or e)


# ── Instamart (Brand Portal: sales + ads · Supply Portal: POs) ────────────────

@app.command("instamart")
def scrape_instamart(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    sales: bool = typer.Option(False, "--sales", help="Scrape sales"),
    ads: bool = typer.Option(False, "--ads", help="Scrape ads"),
    po: bool = typer.Option(False, "--po", help="Scrape purchase orders"),
    date_from: str = typer.Option(
        None, "--from", help="Sales start date YYYY-MM-DD (default: yesterday — the portal has nothing newer)"
    ),
    date_to: str = typer.Option(None, "--to", help="Sales end date YYYY-MM-DD (default: --from)"),
    sales_days_back: int = typer.Option(
        None, "--sales-days-back",
        help=(
            "Sales: trailing window ending yesterday, instead of --from/--to. Use 4 on a "
            "catch-up run: Instamart reconciles for up to 86 hours, and re-loading a date "
            "is harmless — the upsert key is (date, store, item)."
        ),
    ),
    ads_days_back: int = typer.Option(
        instamart_run.ADS_DAYS, "--ads-days-back",
        help="Ads: how many trailing days of the daily series to (re)fetch.",
    ),
    load: bool = typer.Option(
        True, "--load/--no-load",
        help="Sales: write to Postgres. --no-load only downloads the xlsx and reports counts.",
    ),
    keep_file: bool = typer.Option(
        False, "--keep-file/--no-keep-file",
        help=(
            "Sales: keep the downloaded xlsx under backend/staging/instamart_reports/. Off "
            "by default — every column is in Postgres and the portal rebuilds any past report."
        ),
    ),
    force_token: bool = typer.Option(
        False, "--force-token", help="PO: ignore the cached abacus-token and log in fresh.",
    ),
    po_all_lines: bool = typer.Option(
        False, "--po-all-lines",
        help="PO: re-fetch line items for EVERY PO (~15 min), not only new or changed ones.",
    ),
    headed: bool = typer.Option(False, "--headed", help="Show the browser (debugging the login)."),
):
    """Scrape ALL Instamart private data — sales, ads, POs. Pass --sales, --ads,
    --po, or none for all three.

    The work happens in scraper/platforms/instamart/dashboard_data/run.py; this
    command only parses flags and turns the results into the exit code:
    0 = everything landed, 1 = a section failed or lost fetches (what came back
    is still saved), 3 = the login is gone. A section that fails does not stop
    the others.

    Needs `cli auth credentials set instamart -t <tenant> --email <e> --extra
    account_id=<x-client-account-id>` once; the portal login (OTP read from the
    shared inbox) is reused after that.
    """
    run_all = not (sales or ads or po)
    _instamart_exit(instamart_run.run(
        tenant_id,
        sales=sales or run_all, ads=ads or run_all, po=po or run_all,
        date_from=date_from, date_to=date_to, sales_days_back=sales_days_back,
        ads_days_back=ads_days_back, load=load, keep_file=keep_file,
        force_token=force_token, po_all_lines=po_all_lines, headed=headed,
    ))


@app.command("instamart-sales")
def scrape_instamart_sales(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    date_from: str = typer.Option(None, "--from", help="Start date YYYY-MM-DD (default: yesterday)"),
    date_to: str = typer.Option(None, "--to", help="End date YYYY-MM-DD (default: --from; max 31 days)"),
    sales_days_back: int = typer.Option(
        None, "--days-back", help="Trailing window ending yesterday, instead of --from/--to."),
    load: bool = typer.Option(True, "--load/--no-load", help="--no-load only downloads and counts."),
    keep_file: bool = typer.Option(False, "--keep-file/--no-keep-file", help="Keep the downloaded xlsx."),
    headed: bool = typer.Option(False, "--headed", help="Show the browser (debugging the login)."),
):
    """Instamart sales only — same as `scrape instamart --sales`. For more than
    31 days use `scrape instamart-backfill`."""
    _instamart_exit(instamart_run.run(
        tenant_id, sales=True, ads=False, po=False, date_from=date_from, date_to=date_to,
        sales_days_back=sales_days_back, load=load, keep_file=keep_file, headed=headed,
    ))


@app.command("instamart-ads")
def scrape_instamart_ads(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    ads_days_back: int = typer.Option(
        instamart_run.ADS_DAYS, "--days-back", help="Trailing days of the daily series to (re)fetch."),
    headed: bool = typer.Option(False, "--headed", help="Show the browser (debugging the login)."),
):
    """Instamart ads only — same as `scrape instamart --ads`. For a fixed past
    range use `scrape instamart-backfill --ads`."""
    _instamart_exit(instamart_run.run(
        tenant_id, sales=False, ads=True, po=False, ads_days_back=ads_days_back, headed=headed,
    ))


@app.command("instamart-po")
def scrape_instamart_po(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    force_token: bool = typer.Option(False, "--force-token", help="Ignore the cached abacus-token."),
    po_all_lines: bool = typer.Option(
        False, "--all-lines", help="Re-fetch line items for EVERY PO (~15 min), not only changed ones."),
    headed: bool = typer.Option(False, "--headed", help="Show the browser (debugging the login)."),
):
    """Instamart purchase orders only — same as `scrape instamart --po`."""
    _instamart_exit(instamart_run.run(
        tenant_id, sales=False, ads=False, po=True, force_token=force_token,
        po_all_lines=po_all_lines, headed=headed,
    ))


@app.command("instamart-backfill")
def scrape_instamart_backfill(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    date_from: str = typer.Option(..., "--from", help="Start date YYYY-MM-DD"),
    date_to: str = typer.Option(None, "--to", help="End date YYYY-MM-DD (default: yesterday)"),
    sales: bool = typer.Option(False, "--sales", help="Backfill sales"),
    ads: bool = typer.Option(False, "--ads", help="Backfill ads"),
    po: bool = typer.Option(False, "--po", help="Backfill purchase orders (every PO, every line item)"),
    load: bool = typer.Option(True, "--load/--no-load", help="Sales: --no-load only downloads and counts."),
    keep_file: bool = typer.Option(False, "--keep-file/--no-keep-file", help="Sales: keep the xlsx files."),
    headed: bool = typer.Option(False, "--headed", help="Show the browser (debugging the login)."),
):
    """Re-fetch Instamart data for a past date range. Pass --sales, --ads,
    --po, or none for all three.

    Sales is split into reports of at most 31 days, each saved as its own job,
    so any range works. Ads fetches the daily series over the range. PO has no
    date filter: it re-fetches every PO with every line item. Re-loading a date
    is harmless — rows are overwritten, never duplicated. Exit codes as
    `scrape instamart`.
    """
    try:
        start = _date.fromisoformat(date_from)
        end = _date.fromisoformat(date_to) if date_to else _date.today() - timedelta(days=1)
    except ValueError as e:
        raise typer.BadParameter(f"dates must be YYYY-MM-DD ({e})")
    if start > end:
        raise typer.BadParameter("--from is after --to")
    run_all = not (sales or ads or po)
    _instamart_exit(instamart_run.backfill(
        tenant_id, start, end, sales=sales or run_all, ads=ads or run_all, po=po or run_all,
        load=load, keep_file=keep_file, headed=headed,
    ))


def _instamart_exit(coro) -> None:
    """Run an Instamart coroutine in ONE asyncio.run (see instamart_run._run_steps)
    and turn its results into the exit code: 0 ok, 1 a section failed, 3 login gone."""
    try:
        results = asyncio.run(coro)
    except AuthError as e:
        # cli/main.py's global AuthError handler never runs (see scrape_zepto).
        logger.error(
            f"AUTH FAILURE — the Instamart scrape could not authenticate ({type(e).__name__}: {e}). "
            "Check: cli auth status -t <tenant> · Fix: cli auth login instamart -t <tenant>"
        )
        raise typer.Exit(AUTH_EXPIRED_EXIT_CODE)
    if any(not r.ok for r in results):
        raise typer.Exit(1)
