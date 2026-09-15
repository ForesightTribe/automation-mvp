"""READ-ONLY audit: is any Zepto automation currently active?"""
import asyncio
import os
import sys

import asyncpg
from dotenv import load_dotenv

load_dotenv(".env")


async def main(url):
    url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    con = await asyncpg.connect(url, statement_cache_size=0)

    async def show(title, sql, *args):
        print("\n" + "=" * 70)
        print(title)
        print("=" * 70)
        try:
            rows = await con.fetch(sql, *args)
        except Exception as e:
            print("  ERROR:", e)
            return
        if not rows:
            print("  (no rows)")
            return
        for r in rows:
            print("  " + " | ".join(f"{k}={v}" for k, v in dict(r).items()))

    await show(
        "1. cm_platform_accounts (live_armed = gate for scheduled/API runs)",
        "SELECT tenant_id, platform, advertiser_id, account_ref, live_armed "
        "FROM cm_platform_accounts ORDER BY platform",
    )
    await show(
        "2. cm_bid_rules — ZEPTO",
        "SELECT id, tenant_id, campaign_id, campaign_name, keyword, match_type, "
        "active, state, start_date, stop_date, start_time, stop_time, ended_at, settled_at "
        "FROM cm_bid_rules WHERE platform='zepto' ORDER BY created_at DESC",
    )
    await show(
        "2b. cm_bid_rules — count by platform/state/active",
        "SELECT platform, state, active, count(*) FROM cm_bid_rules "
        "GROUP BY 1,2,3 ORDER BY 1,2,3",
    )
    await show(
        "3. cm_budget_schedules — ZEPTO",
        "SELECT id, tenant_id, campaign_id, campaign_name, default_budget, enabled, state, "
        "stop_after_window, ended_at, settled_at FROM cm_budget_schedules "
        "WHERE platform='zepto' ORDER BY created_at DESC",
    )
    await show(
        "3b. cm_budget_schedules — count by platform/state/enabled",
        "SELECT platform, state, enabled, count(*) FROM cm_budget_schedules "
        "GROUP BY 1,2,3 ORDER BY 1,2,3",
    )
    await show(
        "4. job_schedules mentioning zepto (any job_type / name / params)",
        "SELECT id, name, job_type, tenant_id, enabled, repeat, cron, next_run_at, "
        "last_enqueued_at, params::text FROM job_schedules "
        "WHERE name ILIKE '%zepto%' OR job_type ILIKE '%zepto%' OR params::text ILIKE '%zepto%' "
        "ORDER BY id",
    )
    await show(
        "4b. ALL enabled job_schedules (to see what is armed at all)",
        "SELECT id, name, job_type, enabled, cron, next_run_at, params::text "
        "FROM job_schedules WHERE enabled = true ORDER BY next_run_at NULLS LAST",
    )
    await show(
        "5. jobs touching zepto in the last 14 days",
        "SELECT job_type, status, count(*), max(created_at) AS latest FROM jobs "
        "WHERE created_at > now() - interval '14 days' "
        "AND (job_type ILIKE '%zepto%' OR params::text ILIKE '%zepto%') "
        "GROUP BY 1,2 ORDER BY latest DESC",
    )
    await show(
        "5b. last 15 zepto-ish job rows (detail)",
        "SELECT id, job_type, status, lane, created_at, started_at, finished_at, params::text "
        "FROM jobs WHERE (job_type ILIKE '%zepto%' OR params::text ILIKE '%zepto%') "
        "ORDER BY created_at DESC LIMIT 15",
    )
    await show(
        "6. cm_run_log — zepto entries, last 14 days",
        "SELECT * FROM cm_run_log WHERE platform='zepto' "
        "AND created_at > now() - interval '14 days' ORDER BY created_at DESC LIMIT 20",
    )
    await show(
        "7. platform_sessions — zepto",
        "SELECT tenant_id, platform, status, last_login_at, last_validated_at, "
        "consecutive_failures, last_error FROM platform_sessions WHERE platform ILIKE '%zepto%'",
    )

    await con.close()


if __name__ == "__main__":
    u = os.environ.get("DATABASE_URL")
    if not u:
        sys.exit("no DATABASE_URL")
    asyncio.run(main(u))
