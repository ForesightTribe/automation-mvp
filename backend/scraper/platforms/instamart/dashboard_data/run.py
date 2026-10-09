"""Instamart private scrape — the run: sales, ads and purchase orders.

Moved out of `cli/commands/scrape.py` (2026-10-06), on the Zepto pattern
(zepto/dashboard_data/seller/run.py). The CLI keeps flags and exit codes;
everything that fetches, parses, saves and LOGS is here.

Two consoles behind one login:

    seller/   Brand Portal   sales report + ads     WASM-signed, through a browser page
    supply/   Supply Portal  purchase orders        abacus-token, plain httpx

    endpoints.py   URLs and constants
    scraper.py     HTTP only
    parser.py      raw -> rows, pure
    storage.py     upserts
    run.py         the loops — this file (shared by both consoles)

`run` is the daily scrape; `backfill` re-fetches a past date range (sales split
into report-sized chunks, ads over the same range, PO with every line item).
Both go through `_run_steps`.

Each section returns a `SectionResult`; a section that fails does not stop the
others, and any failure makes the CLI exit 1. Logging follows
scraper/utils/run_log.py: one INFO line per step, tagged
`instamart·<tenant>·<section>`; per-request detail at DEBUG.

⚠️ Never hold a DB session idle across a long network phase: on 2026-09-25 the
PO fetch (~2,100 POs + one line-item call each, 15+ min) outlived the session
holding it — asyncpg "the underlying connection is closed". The one exception
is `PortalSession`, which needs its session for the life of the browser (it
renews the portal token mid-run and saves the browser state at exit); every
WRITE still goes through a fresh, short-lived session.
"""
import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import httpx

from app.core.database import AsyncSessionLocal
from app.utils.logger import logger
from platform_auth import store as auth_store
from platform_auth.errors import AuthError
from scraper.platforms.instamart.dashboard_data.seller import endpoints as seller_ep
from scraper.platforms.instamart.dashboard_data.seller import parser as seller_parser
from scraper.platforms.instamart.dashboard_data.seller import scraper as seller_scraper
from scraper.platforms.instamart.dashboard_data.seller import storage as seller_storage
from scraper.platforms.instamart.dashboard_data.seller.session import PortalSession
from scraper.platforms.instamart.dashboard_data.supply import parser as supply_parser
from scraper.platforms.instamart.dashboard_data.supply import scraper as supply_scraper
from scraper.platforms.instamart.dashboard_data.supply import session as supply_session
from scraper.platforms.instamart.dashboard_data.supply import storage as supply_storage
from scraper.utils.jobs import complete_scrape_job, create_scrape_job, fail_scrape_job
from scraper.utils.run_log import rupees, short, tag, tenant_slug, took

PLATFORM = "instamart"

# One section's work, given the credentials.
Step = Callable[["_Creds"], Awaitable["SectionResult"]]

# Ads: trailing days of the daily series re-fetched each run.
ADS_DAYS = 30

# How long the PO section waits before replaying the line-item calls it lost —
# longer than the fetcher's own 5/15/30 s ladder on purpose. Only what fails the
# replay too fails the run.
RECHECK_WAIT_S = 20

# Where the sales xlsx lands (deleted after a successful load unless --keep-file).
REPORT_DIR = Path(__file__).resolve().parents[4] / "staging" / "instamart_reports"

_CREDS_HINT = ("cli auth credentials set instamart -t <tenant> --email <email> "
               "--extra account_id=<x-client-account-id>")


@dataclass
class SectionResult:
    """What one section did."""
    name: str
    window: str = ""
    saved: bool = True
    written: dict[str, int] = field(default_factory=dict)
    lost: list[str] = field(default_factory=list)   # failed twice -> the run fails
    error: str | None = None                        # the section aborted

    @property
    def ok(self) -> bool:
        return self.error is None and not self.lost


class _Creds:
    def __init__(self, email: str, account_id: str, extra: dict):
        self.email = email
        self.account_id = account_id
        self.extra = extra


async def _credentials(tenant_id: str) -> _Creds:
    """The one Instamart credential row both consoles log in with. Raises with
    the command that fixes it when it is missing."""
    async with AsyncSessionLocal() as db:
        creds = await auth_store.get_credentials(db, tenant_id, PLATFORM)
    if not creds or not creds.email:
        raise RuntimeError(f"no Instamart credentials for this tenant — run: {_CREDS_HINT}")
    extra = creds.extra or {}
    if not extra.get("account_id"):
        raise RuntimeError(f"no account_id configured — every portal call needs it: {_CREDS_HINT}")
    return _Creds(creds.email, extra["account_id"], extra)


def _error(e: Exception) -> str:
    return str(getattr(e, "orig", None) or e)


async def _fail_job(job_id: str | None, error: str) -> None:
    if job_id:
        async with AsyncSessionLocal() as db:
            await fail_scrape_job(db, job_id, error)


# ── the run ──────────────────────────────────────────────────────────────────

async def run(
    tenant_id: str,
    *,
    sales: bool = True,
    ads: bool = True,
    po: bool = True,
    date_from: str | None = None,
    date_to: str | None = None,
    sales_days_back: int | None = None,
    ads_days_back: int = ADS_DAYS,
    load: bool = True,
    keep_file: bool = False,
    force_token: bool = False,
    po_all_lines: bool = False,
    headed: bool = False,
) -> list[SectionResult]:
    """The daily scrape: each chosen section once."""
    steps: list[tuple[str, Step]] = []
    if sales:
        steps.append(("sales", lambda c: run_sales(tenant_id, c, date_from, date_to,
                                                   sales_days_back, load, keep_file, headed)))
    if ads:
        end = date.today()
        start = end - timedelta(days=ads_days_back)
        steps.append(("ads", lambda c: run_ads(tenant_id, c, start, end, headed)))
    if po:
        steps.append(("po", lambda c: run_po(tenant_id, c, force_token, po_all_lines, headed)))
    return await _run_steps(tenant_id, steps)


async def backfill(
    tenant_id: str,
    date_from: date,
    date_to: date,
    *,
    sales: bool = True,
    ads: bool = True,
    po: bool = True,
    load: bool = True,
    keep_file: bool = False,
    headed: bool = False,
) -> list[SectionResult]:
    """Re-fetch a past range. Sales: one report per `report_chunks` chunk (the
    portal caps a report at MAX_REPORT_DAYS), each its own job, ending no later
    than yesterday. Ads: the daily series over the same range (campaigns are
    lifetime totals anyway). PO: the API has no date filter, so every PO, with
    every PO's line items. Re-loading a date is harmless: the upsert keys
    overwrite."""
    steps: list[tuple[str, Step]] = []
    if sales:
        for a, b in report_chunks(date_from, min(date_to, date.today() - timedelta(days=1))):
            steps.append(("sales", lambda c, a=a, b=b: run_sales(
                tenant_id, c, a.isoformat(), b.isoformat(), None, load, keep_file, headed)))
    if ads:
        steps.append(("ads", lambda c: run_ads(
            tenant_id, c, date_from, min(date_to, date.today()), headed)))
    if po:
        steps.append(("po", lambda c: run_po(tenant_id, c, False, True, headed)))
    return await _run_steps(tenant_id, steps)


def report_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """[start, end] as consecutive chunks of at most MAX_REPORT_DAYS days."""
    chunks: list[tuple[date, date]] = []
    while start <= end:
        stop = min(start + timedelta(days=seller_ep.MAX_REPORT_DAYS - 1), end)
        chunks.append((start, stop))
        start = stop + timedelta(days=1)
    return chunks


async def _run_steps(tenant_id: str, steps: list[tuple[str, Step]]) -> list[SectionResult]:
    """Each step in turn, in ONE event loop — AsyncSessionLocal's pooled
    connections are bound to the loop that made them; a section per asyncio.run()
    failed the next one with "Event loop is closed" (verified 2026-09-28)."""
    started = time.monotonic()
    async with AsyncSessionLocal() as db:
        slug = await tenant_slug(db, tenant_id)
    names = [n for n, _ in steps]
    wanted = [n if names.count(n) == 1 else f"{n} ×{names.count(n)}"
              for n in dict.fromkeys(names)]

    with tag(PLATFORM, slug):
        logger.info(f"start · {', '.join(wanted)}")
        results: list[SectionResult] = []
        creds: _Creds | None = None
        creds_error: str | None = None
        try:
            creds = await _credentials(tenant_id)
        except Exception as e:
            creds_error = _error(e)

        for name, step in steps:
            with tag(PLATFORM, slug, name):
                if creds is None:
                    res = SectionResult(name, error=creds_error)
                else:
                    try:
                        res = await step(creds)
                    except AuthError:
                        raise
                    except Exception as e:          # sections catch their own; belt and braces
                        res = SectionResult(name, error=_error(e))
                if res.error:
                    # ERROR, not WARNING: the alert matches severity>=ERROR.
                    logger.error(f"FAILED · {res.error}")
            results.append(res)

        failed = [r.name for r in results if not r.ok]
        if failed:
            logger.error(f"finished · FAILED: {', '.join(failed)} · {took(started)}")
        else:
            logger.info(f"finished · ok · {took(started)}")
    return results


# ── sales (Brand Portal report) ──────────────────────────────────────────────

def sales_window(date_from: str | None, date_to: str | None, days_back: int | None,
                 today: date | None = None) -> tuple[date, date]:
    """`days_back` days ending yesterday; else --from (default yesterday) to --to
    (default --from). The portal has nothing newer than yesterday."""
    yesterday = (today or date.today()) - timedelta(days=1)
    if days_back:
        return yesterday - timedelta(days=days_back - 1), yesterday
    start = date.fromisoformat(date_from) if date_from else yesterday
    end = date.fromisoformat(date_to) if date_to else start
    return start, end


async def run_sales(tenant_id: str, creds: _Creds, date_from: str | None, date_to: str | None,
                    days_back: int | None, load: bool, keep_file: bool,
                    headed: bool) -> SectionResult:
    """One report per run at the portal's finest grain (day x store x item), plus
    the per-city brand sheet. The `scrape_jobs` row is opened only when loading."""
    start, end = sales_window(date_from, date_to, days_back)
    span = (end - start).days + 1
    res = SectionResult("sales", window=f"{start}..{end}", saved=load)
    if start > end:
        res.error = "--from is after --to"
        return res
    if span > seller_ep.MAX_REPORT_DAYS:
        res.error = (f"{span} days requested; the portal allows at most "
                     f"{seller_ep.MAX_REPORT_DAYS} per report")
        return res

    job_id = None
    try:
        logger.info(f"{start}→{end} · {span} day{'s' if span > 1 else ''} · requesting the report")
        async with AsyncSessionLocal() as db:
            async with PortalSession(db, tenant_id, creds.email, creds.account_id,
                                     headless=not headed) as portal:
                brand_account_id = portal.brand_account_id() or creds.extra.get("brand_account_id")
                if not brand_account_id:
                    res.error = ("could not resolve the brand-account id — open the portal once "
                                 "and pick the brand, or set --extra brand_account_id=<id>")
                    return res
                path = await seller_scraper.fetch_sales_report(
                    portal, brand_account_id, start, end, REPORT_DIR)

        store_rows, brand_rows = seller_parser.parse(path)
        gmv = sum(r["gmv"] for r in store_rows)
        units = sum(r["units_sold"] for r in store_rows)
        logger.info(f"report · {len(store_rows)} store rows · {len(brand_rows)} brand-city rows · "
                    f"GMV {rupees(gmv)} · {units:,} units · "
                    f"{len({r['store_id'] for r in store_rows})} stores")

        if load:
            async with AsyncSessionLocal() as db:
                job_id = await create_scrape_job(db, tenant_id, "instamart_seller_sales", PLATFORM)
                res.written = await seller_storage.save_sales(
                    db, tenant_id, store_rows, brand_rows, uuid.UUID(job_id))
                await db.commit()
                await complete_scrape_job(db, job_id, sum(res.written.values()))
            logger.info(f"done · saved {sum(res.written.values()):,} rows")
        else:
            logger.info("done · not saved (--no-load)")
        # Deleted only here — after the commit — so a failed parse or load leaves
        # the file on disk to retry from.
        if not keep_file:
            path.unlink(missing_ok=True)
    except AuthError:
        await _fail_job(job_id, "auth_expired")
        raise
    except Exception as e:
        await _fail_job(job_id, _error(e))
        res.error = _error(e)
    return res


# ── ads (Brand Portal) ───────────────────────────────────────────────────────

async def run_ads(tenant_id: str, creds: _Creds, start: date, end: date,
                  headed: bool) -> SectionResult:
    """Campaigns (LIFETIME totals — every row replaced whole), the account-wide
    daily series, product and keyword performance per campaign per day, and the
    product catalogue (names + images) for every product that showed up."""
    res = SectionResult("ads", window=f"{start}..{end}")
    if start > end:
        res.error = "--from is after --to"
        return res
    account_id = creds.account_id

    job_id = None
    try:
        async with AsyncSessionLocal() as db:
            async with PortalSession(db, tenant_id, creds.email, account_id,
                                     headless=not headed) as portal:
                raw_campaigns = await seller_scraper.fetch_campaigns(portal, account_id)
                logger.info(f"campaigns · {len(raw_campaigns)}")
                raw_daily = await seller_scraper.fetch_account_daily(portal, account_id, start, end)
                logger.info(f"account daily {start}→{end} · {len(raw_daily)} days")
                raw_products = await seller_scraper.fetch_products_daily(portal, account_id, start, end)
                raw_keywords = await seller_scraper.fetch_keywords_daily(portal, account_id, start, end)
                product_rows = seller_parser.parse_products_daily(raw_products)
                keyword_rows = seller_parser.parse_keywords_daily(raw_keywords)
                logger.info(f"assets · {len(product_rows)} product rows · "
                            f"{len(keyword_rows)} keyword rows")
                candidate_ids = sorted({r["candidate_id"] for r in product_rows})
                raw_catalog = (await seller_scraper.fetch_product_catalog(portal, candidate_ids)
                               if candidate_ids else [])
                logger.info(f"catalogue · {len(raw_catalog)} of {len(candidate_ids)} products")

        campaign_rows = seller_parser.parse_campaigns(raw_campaigns)
        daily_rows = seller_parser.parse_account_daily(raw_daily)
        catalog_rows = seller_parser.parse_product_catalog(raw_catalog)
        logger.info(f"total · {rupees(sum(r['spend'] for r in daily_rows))} spend · "
                    f"{rupees(sum(r['gmv'] for r in daily_rows))} GMV · "
                    f"{sum(r['clicks'] for r in daily_rows):,} clicks over {len(daily_rows)} days")

        async with AsyncSessionLocal() as db:
            job_id = await create_scrape_job(db, tenant_id, "instamart_ad_campaigns", PLATFORM)
            jid = uuid.UUID(job_id)
            res.written = {
                "campaigns": await seller_storage.save_campaigns(db, tenant_id, campaign_rows, jid),
                "account daily": await seller_storage.save_account_daily(db, tenant_id, daily_rows, jid),
                "product daily": await seller_storage.save_products_daily(db, tenant_id, product_rows, jid),
                "keyword daily": await seller_storage.save_keywords_daily(db, tenant_id, keyword_rows, jid),
                "catalogue": await seller_storage.save_product_catalog(db, tenant_id, catalog_rows),
            }
            await db.commit()
            await complete_scrape_job(db, job_id, sum(res.written.values()))
        logger.info(f"done · saved {sum(res.written.values()):,} rows")
    except AuthError:
        await _fail_job(job_id, "auth_expired")
        raise
    except Exception as e:
        await _fail_job(job_id, _error(e))
        res.error = _error(e)
    return res


# ── purchase orders (Supply Portal) ──────────────────────────────────────────

async def run_po(tenant_id: str, creds: _Creds, force_token: bool, all_lines: bool,
                 headed: bool) -> SectionResult:
    """Every PO the account has ever raised (the API has no date filter — the
    tables are windowed at READ time), line items for the POs that are new or
    changed, then the bulk CSV export's received/balanced qty (best-effort: it
    never fails the section).

    Line items cost one call per PO (~2,100 calls, 15+ min for every PO), and a
    PO's lines only change when its header does — so only POs whose header
    fingerprint (storage.PO_FINGERPRINT) differs from the stored copy, or that
    have no stored lines, are fetched. `all_lines` fetches every PO's lines.

    `grn_quantity / total_quantity` is the fill rate. There is no receipt-EVENT
    date anywhere in this data (app/models/instamart_po.py), so a weekly trend
    buckets by `po_date` (when raised), not by when something arrived.
    """
    res = SectionResult("po", window="all")
    job_id = None
    try:
        async with AsyncSessionLocal() as db:
            job_id = await create_scrape_job(db, tenant_id, "instamart_po", platform=PLATFORM)
        # Its own short session: the browser work happens inside get_token().
        async with AsyncSessionLocal() as db:
            token, brand_company_id = await supply_session.get_token(
                db, tenant_id, creds.email, creds.account_id,
                headless=not headed, force=force_token,
            )
        logger.info(f"token ready · brand {brand_company_id}")

        async with httpx.AsyncClient(timeout=30) as client:
            po_rows = await supply_scraper.fetch_all_purchase_orders(client, token, brand_company_id)
            stored: dict = {}
            if not all_lines:
                async with AsyncSessionLocal() as db:
                    stored = await supply_storage.stored_po_fingerprints(db, tenant_id)
            po_ids = [p["purchase_order_id"] for p in po_rows
                      if stored.get(p["purchase_order_id"]) != supply_storage.po_fingerprint(p)]
            logger.info(f"orders · {len(po_rows)} POs · {len(po_ids)} new or changed"
                        + (" (--po-all-lines)" if all_lines else ""))
            raw_lines, failed = await supply_scraper.fetch_all_po_lines(client, token, po_ids)
            if failed:
                logger.info(f"re-check · {len(failed)} PO(s) lost their lines · in {RECHECK_WAIT_S}s")
                await asyncio.sleep(RECHECK_WAIT_S)
                again, failed = await supply_scraper.fetch_all_po_lines(client, token, failed)
                raw_lines.update(again)
                logger.info(f"re-check · {len(again)} recovered, {len(failed)} still lost")
        res.lost = [f"lines {po_id}" for po_id in failed]

        item_rows = []
        for po_id, raw in raw_lines.items():
            item_rows.extend(supply_parser.parse_po_lines(raw, purchase_order_id=po_id))
        total_qty = sum(p["total_quantity"] for p in po_rows)
        grn_qty = sum(p["grn_quantity"] for p in po_rows)
        fill = f" · fill {100 * grn_qty / total_qty:.1f}%" if total_qty else ""
        logger.info(f"lines · {len(item_rows)} across {len(raw_lines)} POs · "
                    f"value {rupees(sum(p['value'] or 0.0 for p in po_rows))}{fill}")

        # A PO whose lines were lost still gets its header row: save what came back.
        async with AsyncSessionLocal() as db:
            res.written = await supply_storage.save_purchase_orders(
                db, tenant_id, po_rows, item_rows, uuid.UUID(job_id))
            await db.commit()
            total = sum(res.written.values())
            if res.lost:
                await fail_scrape_job(
                    db, job_id, f"partial: {len(res.lost)} PO(s) lost their line items — "
                                f"{short(res.lost)}", records_written=total)
                logger.warning(f"lost after re-check: {short(res.lost)} · re-run to backfill")
            else:
                await complete_scrape_job(db, job_id, total)
        logger.info(f"done · saved {total:,} rows")

        await _sync_export(tenant_id, token, brand_company_id)
    except AuthError:
        await _fail_job(job_id, "auth_expired")
        raise
    except Exception as e:
        await _fail_job(job_id, _error(e))
        res.error = _error(e)
    return res


async def _sync_export(tenant_id: str, token: str, brand_company_id: str) -> None:
    """The bulk CSV export: the only source of a real per-line received qty that
    survives a PO closing (listPurchaseOrderLines' pending_qty resets to 0 on
    close — see InstamartPOItem). Best-effort: the PO data is already saved."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await supply_scraper.submit_po_export(client, token, brand_company_id)
            file_url = await supply_scraper.fetch_po_export_url(client, token)
            if not file_url:
                logger.info("export · job did not complete in time · skipped this run")
                return
            csv_text = await supply_scraper.fetch_po_export_csv(client, file_url)
        rows = supply_parser.parse_po_export_csv(csv_text)
        async with AsyncSessionLocal() as db:
            synced = await supply_storage.save_po_export(db, tenant_id, rows)
            await db.commit()
        logger.info(f"export · received/balanced qty synced for {synced:,} lines")
    except Exception as e:
        logger.warning(f"export · failed, PO data above is still saved: {e}")
