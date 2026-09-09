"""Snapshot every campaign's current configuration to a local file. READ-ONLY.

Insurance, not a feature. `blinkit_ad_campaigns` is upserted IN PLACE by the nightly
marketing scrape, so it holds exactly one picture — today's. That is why the city lists
lost to the `city_ids` bug (docs/campaign-manager.md §8.2b) are unrecoverable: the table
that could have proved what they were had already overwritten itself, night after night.

This captures what a whole-campaign PUT can destroy — city targeting, budget, pacing, and
every keyword's bid — before we rewrite the Blinkit payload builders. If a write goes wrong
during that work, this file is the difference between restoring from it and asking the
client to remember.

Writes to `backend/out/` (gitignored). Nothing is sent anywhere and nothing is modified.

    python -m scripts.snapshot_campaign_state              # all tenants
    python -m scripts.snapshot_campaign_state -t <uuid>    # one tenant
"""
import argparse
import asyncio
import json
from datetime import datetime, date
from pathlib import Path

from sqlalchemy import text

from app.core.database import AsyncSessionLocal

OUT_DIR = Path(__file__).resolve().parent.parent / "out"

CAMPAIGNS = """
SELECT tenant_id, campaign_id, name, type, status, start_ts, end_ts,
       infinite_campaign, daily_budget, region_type, cities, min_cpm,
       pacing_type, billed_amount, campaign_cpm, scraped_at
FROM blinkit_ad_campaigns
-- Both sides cast: asyncpg cannot infer a bare parameter's type from `$1 IS NULL`.
WHERE (CAST(:tenant AS uuid) IS NULL OR tenant_id = CAST(:tenant AS uuid))
ORDER BY campaign_id
"""

KEYWORDS = """
SELECT tenant_id, campaign_id, campaign_type, keyword, match_type, current_cpm,
       min_bid, max_bid, suggested_min, suggested_max, keyword_searches, scraped_at
FROM blinkit_ad_campaign_keywords
-- Both sides cast: asyncpg cannot infer a bare parameter's type from `$1 IS NULL`.
WHERE (CAST(:tenant AS uuid) IS NULL OR tenant_id = CAST(:tenant AS uuid))
ORDER BY campaign_id, keyword, match_type
"""


def _plain(value):
    """JSON-safe. Dates go to ISO; everything else keeps its own type."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "hex") and not isinstance(value, (str, bytes)):
        return str(value)                      # UUID
    return value


async def _rows(session, sql: str, tenant: str | None) -> list[dict]:
    result = await session.execute(text(sql), {"tenant": tenant})
    return [{k: _plain(v) for k, v in r._mapping.items()} for r in result.all()]


def _city_count(row: dict) -> int | None:
    """How many cities a campaign targets. None = pan-India / untargeted.

    `cities` is JSON: a list of {id, name} when targeted, JSON null otherwise (the column
    stores Python None as JSON null, not SQL NULL — so `is None` catches both).
    """
    cities = row.get("cities")
    return len(cities) if isinstance(cities, list) else None


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-t", "--tenant", default=None, help="Tenant UUID (default: all)")
    args = ap.parse_args()

    async with AsyncSessionLocal() as session:
        campaigns = await _rows(session, CAMPAIGNS, args.tenant)
        keywords = await _rows(session, KEYWORDS, args.tenant)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"campaign-state-{stamp}.json"
    path.write_text(json.dumps({
        "taken_at": datetime.now().isoformat(timespec="seconds"),
        "source": "blinkit_ad_campaigns + blinkit_ad_campaign_keywords (nightly scrape)",
        "why": "pre-rewrite insurance — see docs/campaign-manager.md 8.2b",
        "tenant": args.tenant,
        "campaigns": campaigns,
        "keywords": keywords,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    targeted = [c for c in campaigns if _city_count(c) is not None]
    print(f"\nSaved {path}")
    print(f"  {len(campaigns)} campaigns · {len(keywords)} keyword rows")
    print(f"  {len(targeted)} campaigns carry city targeting — the ones with something to lose:")
    for c in sorted(targeted, key=lambda c: -(_city_count(c) or 0)):
        names = ", ".join(x.get("name", "?") for x in (c.get("cities") or [])[:4])
        more = "" if (_city_count(c) or 0) <= 4 else f" +{_city_count(c) - 4} more"
        print(f"    {c['campaign_id']:>8}  {_city_count(c):>3} cities  {c['status']:<10} "
              f"{(c['name'] or '')[:34]:<34} [{names}{more}]")


if __name__ == "__main__":
    asyncio.run(main())
