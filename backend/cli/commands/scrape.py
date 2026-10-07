import asyncio
import time
import uuid
from datetime import date as _date, timedelta
from typing import Optional
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from app.core.database import AsyncSessionLocal
from app.utils.logger import logger
from platform_auth import service as auth_service
from platform_auth.errors import AUTH_EXPIRED_EXIT_CODE, AuthError
from scraper.utils.jobs import create_scrape_job, complete_scrape_job, fail_scrape_job
from scraper.utils.run_log import rupees, tag, tenant_slug, took
from scraper.platforms.zepto.dashboard_data.seller import run as zepto_run
from scraper.platforms.blinkit.dashboard_data.marketing.scraper import scrape
from scraper.platforms.blinkit.dashboard_data.marketing.parser import (
    parse_campaign,
    parse_campaign_daily,
    parse_campaign_detail,
    parse_campaign_keywords,
    parse_sponsored_sov,
    parse_brand_collection,
    parse_visibility_plan,
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
    save: bool = typer.Option(True, "--save/--no-save", help="Save results to PostgreSQL"),
):
    """Scrape the Blinkit marketing dashboard for a date window.

    One pass fetches the campaign list, each campaign's daily metric series + its
    keyword/recommendation breakdown, plus SOV / collections / plans. Use --from
    to backfill (e.g. --from 30 days ago); the daily run defaults to the last week
    so late metric revisions are picked up. Use --limit to smoke-test a few
    campaigns without the full-volume run.
    """
    asyncio.run(_scrape_blinkit(tenant_id, date_from, date_to, limit, save))


async def _scrape_blinkit(
    tenant_id: str, date_from: str | None, date_to: str | None, limit: int | None, save: bool
) -> None:
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
                raw = await scrape(storage_state, start, end, limit=limit)

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
                                              plans, keywords=keyword_bids)
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
                raw = await seller_hub_scraper.scrape_sales(
                    email, session.storage_state, time_range_filter=window
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


async def _scrape_instamart_sales(
    tenant_id: str,
    date_from: str | None,
    date_to: str | None,
    days_back: int | None,
    load: bool,
    headed: bool,
    keep_file: bool,
) -> None:
    """Scrape Instamart private sales (Brand Portal) into the seller tables.

    One report per run, at the portal's finest grain: day x store x item, plus
    the per-city brand metrics sheet. The portal only has data up to yesterday.

    Needs `cli auth credentials set instamart -t <tenant> --email <e>
    --extra account_id=<x-client-account-id>` to have been run once. The first
    scrape logs into the portal in a browser (reading the OTP from the shared
    inbox by itself) and reuses that session afterwards.

    Callable directly (used by both `instamart-sales` and the `instamart`
    master command — see `_scrape_instamart`), so all its errors surface as
    `typer.Exit(1)` rather than a bare return, letting a caller's own
    try/except around this call double as per-section failure isolation.
    """
    from pathlib import Path

    from platform_auth import store as auth_store
    from scraper.platforms.instamart.dashboard_data.seller import (
        endpoints as im_ep, parser as im_parser, scraper as im_scraper,
    )
    from scraper.platforms.instamart.dashboard_data.seller.session import PortalSession
    from scraper.platforms.instamart.dashboard_data.seller.storage import save_sales

    yesterday = _date.today() - timedelta(days=1)
    if days_back:
        start, end = yesterday - timedelta(days=days_back - 1), yesterday
    else:
        start = _date.fromisoformat(date_from) if date_from else yesterday
        end = _date.fromisoformat(date_to) if date_to else start
    if start > end:
        console.print("[red]--from is after --to[/red]")
        raise typer.Exit(1)
    span = (end - start).days + 1
    if span > im_ep.MAX_REPORT_DAYS:
        console.print(
            f"[red]{span} days requested; the portal allows at most "
            f"{im_ep.MAX_REPORT_DAYS} per report.[/red]"
        )
        raise typer.Exit(1)

    dest = Path(__file__).resolve().parents[2] / "staging" / "instamart_reports"

    job_id = None
    async with AsyncSessionLocal() as db:
        creds = await auth_store.get_credentials(db, tenant_id, "instamart")
        if not creds or not creds.email:
            console.print(
                "[red]No Instamart credentials for this tenant. Run:[/red]\n"
                "  cli auth credentials set instamart -t <tenant> --email <email> "
                "--extra account_id=<x-client-account-id>"
            )
            raise typer.Exit(1)
        account_id = (creds.extra or {}).get("account_id")
        if not account_id:
            console.print(
                "[red]No account_id configured. Every Brand Portal data call "
                "needs it:[/red]\n  cli auth credentials set instamart -t "
                f"{tenant_id} --email {creds.email} --extra account_id=<id>"
            )
            raise typer.Exit(1)

        try:
            console.print(
                f"[cyan]Instamart sales {start} → {end} "
                f"({span} day{'s' if span > 1 else ''})[/cyan]"
            )
            async with PortalSession(tenant_id, creds.email, account_id,
                                     headless=not headed) as portal:
                brand_account_id = (portal.brand_account_id()
                                    or (creds.extra or {}).get("brand_account_id"))
                if not brand_account_id:
                    console.print(
                        "[red]Could not resolve the brand-account id. Open the "
                        "portal once and pick the brand, or set it:[/red]\n"
                        "  cli auth credentials set instamart -t <tenant> "
                        "--email <email> --extra brand_account_id=<id>"
                    )
                    raise typer.Exit(1)
                console.print(f"  brand account: {brand_account_id}")
                console.print("  requesting the report…")
                path = await im_scraper.fetch_sales_report(
                    portal, brand_account_id, start, end, dest)

            console.print(f"  downloaded [green]{path.name}[/green]")
            store_rows, brand_rows = im_parser.parse(path)
            console.print(
                f"  parsed [bold]{len(store_rows)}[/bold] store rows, "
                f"[bold]{len(brand_rows)}[/bold] brand-city rows"
            )
            if store_rows:
                table = Table(title="Instamart sales")
                table.add_column("date"); table.add_column("GMV", justify="right")
                table.add_column("units", justify="right")
                table.add_column("stores", justify="right")
                by_day: dict = {}
                for r in store_rows:
                    d = by_day.setdefault(r["date"], {"gmv": 0.0, "u": 0, "s": set()})
                    d["gmv"] += r["gmv"]; d["u"] += r["units_sold"]
                    d["s"].add(r["store_id"])
                for day in sorted(by_day):
                    d = by_day[day]
                    table.add_row(str(day), f"{d['gmv']:,.0f}",
                                  str(d["u"]), str(len(d["s"])))
                console.print(table)

            if not load:
                console.print("[yellow]--no-load: nothing written to the DB[/yellow]")
            else:
                job_id = await create_scrape_job(
                    db, tenant_id, "instamart_seller_sales", "instamart")
                written = await save_sales(db, tenant_id, store_rows, brand_rows,
                                           uuid.UUID(job_id))
                await db.commit()
                total = written["store_daily"] + written["brand_city"]
                await complete_scrape_job(db, job_id, total)
                console.print(
                    f"[green]Saved {written['store_daily']} store rows + "
                    f"{written['brand_city']} brand-city rows[/green]"
                )
            # Deleted only here — after the commit above — so a failed
            # parse or load leaves the file on disk to retry from.
            if not keep_file:
                path.unlink(missing_ok=True)
        except typer.Exit:
            raise
        except Exception as e:
            if job_id:
                await fail_scrape_job(db, job_id, str(e))
            console.print(f"[red]Instamart scrape failed: {escape(str(e))}[/red]")
            raise typer.Exit(1)


@app.command("instamart-sales")
def scrape_instamart_sales(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    date_from: str = typer.Option(
        None, "--from",
        help="Start date YYYY-MM-DD (default: yesterday — the portal has nothing newer)",
    ),
    date_to: str = typer.Option(None, "--to", help="End date YYYY-MM-DD (default: --from)"),
    days_back: int = typer.Option(
        None, "--days-back",
        help=(
            "Trailing window ending yesterday, instead of --from/--to. Use 4 on a "
            "catch-up run: Instamart reconciles for up to 86 hours, and re-loading "
            "a date is harmless because the upsert key is (date, store, item)."
        ),
    ),
    load: bool = typer.Option(
        True, "--load/--no-load",
        help="Write to Postgres. --no-load just downloads the xlsx and reports counts.",
    ),
    headed: bool = typer.Option(
        False, "--headed", help="Show the browser (debugging the login form)."
    ),
    keep_file: bool = typer.Option(
        False, "--keep-file/--no-keep-file",
        help=(
            "Keep the downloaded xlsx under backend/staging/instamart_reports/. "
            "Off by default: every column of it is already in Postgres, and the "
            "portal rebuilds a report for any past range on request, so the file "
            "is a transport envelope rather than the record."
        ),
    ),
):
    """Scrape Instamart private sales only. See `instamart` for the combined
    sales + ads + PO command; this is the same section, standalone."""
    asyncio.run(_scrape_instamart_sales(
        tenant_id, date_from, date_to, days_back, load, headed, keep_file
    ))


async def _scrape_instamart_ads(tenant_id: str, days_back: int, headed: bool) -> None:
    """Scrape Instamart ads: campaigns (Brand Portal /api/v1/campaigns) into
    `instamart_ad_campaigns`, and the account-wide daily series
    (/api/v1/advertiser/metrics/batch) into `instamart_ad_account_daily`.

    Campaigns are LIFETIME totals per campaign, not a window - re-run any
    time, every campaign's row is replaced whole. The daily series is a real
    day-by-day account total (verified against the portal's own dashboard:
    GMV, impressions AND spend all reconciled exactly) - one call covers the
    whole `--days-back` range, so re-running widens or refreshes history
    rather than only ever adding "today".

    Also fetches product/keyword ad-asset performance (instamart_ad_product_daily,
    instamart_ad_keyword_daily) and the product catalogue (names + images,
    instamart_product_catalog) that powers the "Ad asset performance" card.
    Each product/keyword row also carries a campaign_id, one row per
    contributing campaign, for the card's Campaign column and drawer. There
    is no ad-type (campaign_type) filter or breakdown here — it existed
    earlier and was removed as unreliable; see asset_metrics.py's docstring.

    Needs the same `cli auth credentials set instamart ...` as `instamart-sales`,
    and reuses that same saved browser session. Callable directly — see the
    note on `_scrape_instamart_sales`.
    """
    from platform_auth import store as auth_store
    from scraper.platforms.instamart.dashboard_data.seller import account_metrics as im_daily
    from scraper.platforms.instamart.dashboard_data.seller import asset_metrics as im_assets
    from scraper.platforms.instamart.dashboard_data.seller import campaigns as im_campaigns
    from scraper.platforms.instamart.dashboard_data.seller.session import PortalSession

    job_id = None
    async with AsyncSessionLocal() as db:
        creds = await auth_store.get_credentials(db, tenant_id, "instamart")
        if not creds or not creds.email:
            console.print(
                "[red]No Instamart credentials for this tenant. Run:[/red]\n"
                "  cli auth credentials set instamart -t <tenant> --email <email> "
                "--extra account_id=<x-client-account-id>"
            )
            raise typer.Exit(1)
        account_id = (creds.extra or {}).get("account_id")
        if not account_id:
            console.print("[red]No account_id configured for this tenant.[/red]")
            raise typer.Exit(1)

        try:
            today = _date.today()
            start, end = today - timedelta(days=days_back), today

            async with PortalSession(tenant_id, creds.email, account_id,
                                     headless=not headed) as portal:
                console.print("[cyan]Fetching Instamart campaigns...[/cyan]")
                raw = await im_campaigns.fetch_campaigns(portal, account_id)

                console.print(f"[cyan]Fetching account-daily metrics {start} to {end}...[/cyan]")
                raw_daily = await im_daily.fetch_daily(portal, account_id, start, end)

                console.print(f"[cyan]Fetching product ad-performance {start} to {end}...[/cyan]")
                raw_products = await im_assets.fetch_products_daily(portal, account_id, start, end)

                console.print(f"[cyan]Fetching keyword ad-performance {start} to {end}...[/cyan]")
                raw_keywords = await im_assets.fetch_keywords_daily(portal, account_id, start, end)

                product_rows_pre = im_assets.parse_products_daily(raw_products)
                candidate_ids = sorted({r["candidate_id"] for r in product_rows_pre})
                console.print(f"[cyan]Fetching product catalogue for {len(candidate_ids)} product(s)...[/cyan]")
                raw_catalog = (
                    await im_assets.fetch_product_catalog(portal, account_id, candidate_ids)
                    if candidate_ids else []
                )

            rows = im_campaigns.parse_campaigns(raw)
            console.print(f"  parsed [bold]{len(rows)}[/bold] campaign(s)")

            daily_rows = im_daily.parse_daily(raw_daily)
            console.print(f"  parsed [bold]{len(daily_rows)}[/bold] daily row(s)")

            product_rows = product_rows_pre
            keyword_rows = im_assets.parse_keywords_daily(raw_keywords)
            catalog_rows = im_assets.parse_product_catalog(raw_catalog)
            console.print(
                f"  parsed [bold]{len(product_rows)}[/bold] product-daily row(s), "
                f"[bold]{len(keyword_rows)}[/bold] keyword-daily row(s), "
                f"[bold]{len(catalog_rows)}[/bold] catalogue row(s)"
            )

            if rows:
                table = Table(title="Instamart campaigns")
                for col in ("name", "status", "spend", "gmv", "impressions", "clicks"):
                    table.add_column(col, justify="right" if col not in ("name", "status") else "left")
                for r in rows:
                    table.add_row(
                        (r["name"] or "")[:35], r["status"] or "",
                        f"{r['spend']:,.0f}", f"{r['gmv']:,.0f}",
                        str(r["impressions"]), str(r["clicks"]),
                    )
                console.print(table)

            if daily_rows:
                dtable = Table(title="Instamart account daily")
                for col in ("date", "spend", "gmv", "impressions", "clicks"):
                    dtable.add_column(col, justify="right" if col != "date" else "left")
                for r in daily_rows:
                    dtable.add_row(
                        str(r["date"]), f"{r['spend']:,.0f}", f"{r['gmv']:,.0f}",
                        str(r["impressions"]), str(r["clicks"]),
                    )
                console.print(dtable)

            job_id = await create_scrape_job(db, tenant_id, "instamart_ad_campaigns", "instamart")
            written = await im_campaigns.save_campaigns(db, tenant_id, rows, uuid.UUID(job_id))
            written_daily = await im_daily.save_daily(db, tenant_id, daily_rows, uuid.UUID(job_id))
            written_products = await im_assets.save_products_daily(db, tenant_id, product_rows, uuid.UUID(job_id))
            written_keywords = await im_assets.save_keywords_daily(db, tenant_id, keyword_rows, uuid.UUID(job_id))
            written_catalog = await im_assets.save_product_catalog(db, tenant_id, catalog_rows)
            await db.commit()
            total_written = (
                written + written_daily + written_products + written_keywords + written_catalog
            )
            await complete_scrape_job(db, job_id, total_written)
            console.print(
                f"[green]Saved {written} campaign row(s) + {written_daily} daily row(s) + "
                f"{written_products} product row(s) + {written_keywords} keyword row(s) + "
                f"{written_catalog} catalogue row(s)[/green]"
            )
        except typer.Exit:
            raise
        except Exception as e:
            if job_id:
                await fail_scrape_job(db, job_id, str(e))
            console.print(f"[red]Instamart ads scrape failed: {escape(str(e))}[/red]")
            raise typer.Exit(1)


@app.command("instamart-ads")
def scrape_instamart_ads(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    days_back: int = typer.Option(
        30, "--days-back",
        help="How many trailing days of the account-wide daily series to (re)fetch.",
    ),
    headed: bool = typer.Option(
        False, "--headed", help="Show the browser (debugging the login form)."
    ),
):
    """Scrape Instamart ads only. See `instamart` for the combined
    sales + ads + PO command; this is the same section, standalone."""
    asyncio.run(_scrape_instamart_ads(tenant_id, days_back, headed))


async def _scrape_instamart_po(tenant_id: str, headed: bool, force_token: bool) -> None:
    """Scrape Instamart purchase orders from the Supply Portal
    (partner.instamart.in/im-vendor) — a SEPARATE portal from `instamart-ads`,
    talking to picker.swiggy.com, not brand-portal-service-http.swiggy.com.

    Reuses the same Brand Portal login `instamart-ads` uses: navigating that
    session to /im-vendor/po-dashboard makes the vendor app mint its own
    abacus-token, no separate credentials needed. Unlike the Brand Portal,
    that token works from plain HTTP calls once captured — see
    `dashboard_data/supply/session.py`'s docstring for how this was verified.

    Pulls every PO the account has ever raised (no date filter — the table
    is windowed at READ time, same pattern as Zepto's PO/GRN tables) plus
    every PO's line items. `instamart_po.grn_quantity / total_quantity` is
    the fill rate; there is no receipt-EVENT date anywhere in this data (see
    `app/models/instamart_po.py`), so a weekly trend has to bucket by
    `po_date` (when raised), not by when something actually arrived.

    Callable directly — see the note on `_scrape_instamart_sales`.
    """
    from platform_auth import store as auth_store
    from scraper.platforms.instamart.dashboard_data.supply import session as supply_session
    from scraper.platforms.instamart.dashboard_data.supply import fetch as supply_fetch
    from scraper.platforms.instamart.dashboard_data.supply import parser as supply_parser
    from scraper.platforms.instamart.dashboard_data.supply import storage as supply_storage
    import httpx

    # ⚠️ Each DB touch below opens its OWN short-lived session rather than
    # holding one open for the whole function. Verified live 2026-09-25:
    # the full fetch (2122 POs + 2122 sequential line-item calls, ~15+
    # minutes at the safe pace fetch.py uses) outlived a session held
    # open across it — asyncpg.InterfaceError, "cannot call
    # Transaction.rollback(): the underlying connection is closed" — the
    # exact same class of bug already documented (and left unfixed) on
    # the instamart-ads CLI's long throttled runs. Fixed HERE by never
    # letting a session sit idle through the network-bound phase.
    async with AsyncSessionLocal() as db:
        creds = await auth_store.get_credentials(db, tenant_id, "instamart")
    if not creds or not creds.email:
        console.print(
            "[red]No Instamart credentials for this tenant. Run:[/red]\n"
            "  cli auth credentials set instamart -t <tenant> --email <email> "
            "--extra account_id=<x-client-account-id>"
        )
        raise typer.Exit(1)
    account_id = (creds.extra or {}).get("account_id")
    if not account_id:
        console.print("[red]No account_id configured for this tenant's Instamart credentials.[/red]")
        raise typer.Exit(1)

    job_id = None
    try:
        async with AsyncSessionLocal() as db:
            job_id = await create_scrape_job(db, tenant_id, "instamart_po", platform="instamart")

        with console.status("[cyan]Getting a Supply Portal token...[/cyan]"):
            token, brand_company_id = await supply_session.get_token(
                tenant_id, creds.email, account_id,
                headless=not headed, force=force_token,
            )
        console.print(f"[green]Token ready (brand {brand_company_id}).[/green]")

        async with httpx.AsyncClient(timeout=30) as client:
            with console.status("[cyan]Fetching purchase orders...[/cyan]"):
                po_rows = await supply_fetch.fetch_all_purchase_orders(
                    client, token, brand_company_id
                )
            console.print(f"[green]{len(po_rows)} PO(s) fetched.[/green]")

            po_ids = [p["purchase_order_id"] for p in po_rows]
            with console.status(f"[cyan]Fetching line items for {len(po_ids)} PO(s)...[/cyan]"):
                raw_lines, failed_ids = await supply_fetch.fetch_all_po_lines(client, token, po_ids)

        item_rows = []
        for po_id, raw in raw_lines.items():
            item_rows.extend(supply_parser.parse_po_lines(raw, purchase_order_id=po_id))

        async with AsyncSessionLocal() as db:
            counts = await supply_storage.save_purchase_orders(
                db, tenant_id, po_rows, item_rows, uuid.UUID(job_id)
            )
            await db.commit()
            written = sum(counts.values())
            # A PO whose line items failed after retries still gets its
            # header row saved above (po_rows is unaffected by failed_ids)
            # — only its item rows are missing, same "save what came
            # back" principle as _scrape_zepto_po.
            await complete_scrape_job(db, job_id, written)

        # Bulk CSV export: the only source of a real per-line received
        # qty that survives a PO closing (listPurchaseOrderLines's
        # pending_qty resets to 0 on close — see InstamartPOItem's
        # docstring). Best-effort: a failure here doesn't fail the whole
        # scrape, since everything above already saved successfully.
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                with console.status("[cyan]Requesting the bulk PO export...[/cyan]"):
                    await supply_fetch.submit_po_export(client, token, brand_company_id)
                    file_url = await supply_fetch.fetch_po_export_url(client, token)
                if file_url:
                    csv_text = await supply_fetch.fetch_po_export_csv(client, file_url)
                    export_rows = supply_parser.parse_po_export_csv(csv_text)
                    async with AsyncSessionLocal() as db:
                        synced = await supply_storage.save_po_export(db, tenant_id, export_rows)
                        await db.commit()
                    console.print(f"[green]Export sync: {synced} line(s) got a real received/balanced qty.[/green]")
                else:
                    console.print("[yellow]Export job did not complete in time — skipped this run.[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Bulk export sync failed (PO data above is still saved): {e}[/yellow]")

        total_qty = sum(p["total_quantity"] for p in po_rows)
        grn_qty = sum(p["grn_quantity"] for p in po_rows)
        total_value = sum(p["value"] or 0.0 for p in po_rows)

        console.print("")
        console.print("[bold]Instamart Purchase Orders[/bold]")
        console.print(f"  POs: {len(po_rows)}   line items: {len(item_rows)}   value: Rs {total_value:,.0f}")
        if total_qty:
            console.print(f"  [bold]Fill rate: {grn_qty:,}/{total_qty:,} = {100 * grn_qty / total_qty:.1f}%[/bold]")
        console.print(f"  Saved to DB: {written} rows")

        if failed_ids:
            console.print(
                f"[yellow]{len(failed_ids)} PO(s) lost their line items after retries "
                f"— PO headers are saved, re-run to backfill items for: "
                f"{', '.join(failed_ids[:10])}{'...' if len(failed_ids) > 10 else ''}[/yellow]"
            )
    except typer.Exit:
        raise
    except Exception as e:
        if job_id:
            async with AsyncSessionLocal() as db:
                await fail_scrape_job(db, job_id, str(e))
        console.print(f"[red]Instamart PO scrape failed: {escape(str(e))}[/red]")
        raise typer.Exit(1)


@app.command("instamart-po")
def scrape_instamart_po(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    headed: bool = typer.Option(
        False, "--headed", help="Show the browser (debugging the login)."
    ),
    force_token: bool = typer.Option(
        False, "--force-token", help="Ignore the cached abacus-token and log in fresh."
    ),
):
    """Scrape Instamart purchase orders only. See `instamart` for the
    combined sales + ads + PO command; this is the same section, standalone."""
    asyncio.run(_scrape_instamart_po(tenant_id, headed, force_token))


@app.command("instamart")
def scrape_instamart_all(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    sales: bool = typer.Option(False, "--sales", help="Scrape sales only"),
    ads: bool = typer.Option(False, "--ads", help="Scrape ads only"),
    po: bool = typer.Option(False, "--po", help="Scrape POs only"),
    date_from: str = typer.Option(
        None, "--from", help="Sales start date YYYY-MM-DD (default: yesterday)"
    ),
    date_to: str = typer.Option(None, "--to", help="Sales end date YYYY-MM-DD (default: --from)"),
    sales_days_back: int = typer.Option(
        None, "--sales-days-back",
        help="Sales: trailing window ending yesterday, instead of --from/--to.",
    ),
    ads_days_back: int = typer.Option(
        30, "--ads-days-back", help="Ads: how many trailing days of the daily series to (re)fetch.",
    ),
    load: bool = typer.Option(
        True, "--load/--no-load", help="Sales: write to Postgres.",
    ),
    keep_file: bool = typer.Option(
        False, "--keep-file/--no-keep-file", help="Sales: keep the downloaded xlsx.",
    ),
    force_token: bool = typer.Option(
        False, "--force-token", help="PO: ignore the cached abacus-token and log in fresh.",
    ),
    headed: bool = typer.Option(
        False, "--headed", help="Show the browser (debugging the login form)."
    ),
):
    """Scrape ALL Instamart private data — sales, ads, POs. Pass --sales,
    --ads, --po, or none for all three.

    THE master Instamart command, mirroring `scrape zepto`: one command
    instead of three, so a VM cron or a manual check doesn't have to
    remember and chain `instamart-sales` / `instamart-ads` / `instamart-po`.

    Unlike Zepto, this does NOT exist to avoid session eviction — Instamart's
    Brand Portal session is a cached, refreshable 5-hour JWT (see
    platform_auth/registry.py) and the Supply Portal's abacus-token is
    independently cached too (supply/session.py), so running the three
    sections separately never forces a fresh login or kicks anyone off the
    portal the way Zepto's daily OTP does. Each section here still opens its
    own session/token exactly as it would standalone — this command saves
    typing, not browser launches.

    A section that fails does not abort the others, same as `scrape zepto`.
    The command exits non-zero if anything failed, so the job runner (once
    Instamart is registered in jobs/types.py — it is not yet) would record a
    failure rather than a silent gap.
    """
    asyncio.run(_scrape_instamart(
        tenant_id, sales, ads, po, date_from, date_to, sales_days_back,
        ads_days_back, load, keep_file, force_token, headed,
    ))


async def _scrape_instamart(
    tenant_id: str,
    sales_flag: bool,
    ads_flag: bool,
    po_flag: bool,
    date_from: str | None,
    date_to: str | None,
    sales_days_back: int | None,
    ads_days_back: int,
    load: bool,
    keep_file: bool,
    force_token: bool,
    headed: bool,
) -> None:
    # ⚠️ ONE asyncio.run() for all three sections, not one each — see the
    # caller. Each of AsyncSessionLocal's pooled asyncpg connections is bound
    # to the event loop that created it; a section run under its OWN
    # asyncio.run() call leaves connections behind in a now-closed loop, and
    # the NEXT section's asyncio.run() (a different loop) then blows up
    # tearing one down: "RuntimeError: Event loop is closed". Verified live
    # 2026-09-28 — the ads section failed with exactly this the first time
    # sales, ads and po each got their own asyncio.run(). Awaiting all three
    # directly inside one outer asyncio.run(), exactly like _scrape_zepto
    # does, keeps every connection in the same loop for the run's lifetime.
    run_all = not sales_flag and not ads_flag and not po_flag
    run_sales = sales_flag or run_all
    run_ads = ads_flag or run_all
    run_po = po_flag or run_all

    failed: list[str] = []
    ran: list[str] = []

    if run_sales:
        console.rule("[bold]Sales")
        logger.info("Instamart: sales section starting")
        try:
            await _scrape_instamart_sales(
                tenant_id, date_from, date_to, sales_days_back, load, headed, keep_file
            )
            ran.append("sales")
        except Exception as e:
            failed.append("sales")
            logger.error(f"Instamart sales section FAILED: {_why(e)}")
            console.print(f"[yellow]Sales failed — continuing: {_why(e)}[/yellow]")

    if run_ads:
        console.rule("[bold]Ads")
        logger.info("Instamart: ads section starting")
        try:
            await _scrape_instamart_ads(tenant_id, ads_days_back, headed)
            ran.append("ads")
        except Exception as e:
            failed.append("ads")
            logger.error(f"Instamart ads section FAILED: {_why(e)}")
            console.print(f"[yellow]Ads failed — continuing: {_why(e)}[/yellow]")

    if run_po:
        console.rule("[bold]PO")
        logger.info("Instamart: PO section starting")
        try:
            await _scrape_instamart_po(tenant_id, headed, force_token)
            ran.append("po")
        except Exception as e:
            failed.append("po")
            logger.error(f"Instamart PO section FAILED: {_why(e)}")
            console.print(f"[yellow]PO failed: {_why(e)}[/yellow]")

    if failed:
        logger.error(
            f"Instamart scrape finished with failures — ok: {', '.join(ran) or 'none'} "
            f"· failed: {', '.join(failed)}"
        )
        console.print(f"[red]Sections failed: {', '.join(failed)}[/red]")
        raise typer.Exit(1)
    logger.info(f"Instamart scrape complete — sections: {', '.join(ran)}")
    console.print("[green]Instamart scrape complete.[/green]")
