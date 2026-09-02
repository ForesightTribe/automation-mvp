"""How well do a marketplace's ad-platform city names line up with our darkstore catalog —
and generate the `city_map` sheet for the ones that don't (V7.3).

READ-ONLY against both Blinkit and the DB. With `--out` it writes a workbook containing
just the `city_map` sheet, for MERGING into `config.xlsx` and applying with `cli sync`.

⚠️ It emits **Blinkit rows only**. The real sheet also holds hand-written rows for other
marketplaces (`zepto:catalog | hubballi | Hubli`, …), so PASTE OVER the sheet and you will
silently drop them. Merge by source, or add new rows below the existing ones.

Only EXCEPTIONS need a row: a marketplace city whose name already equals a
`marketplace_locations.city` resolves without one (228 of Blinkit's 242, measured
2026-08-27). The rest are two kinds:

  - **Grouped catalogs.** Ours has `hr-ncr` / `up-ncr`; Blinkit lists Gurugram, Noida and
    Ghaziabad separately. `hr-ncr` turns out to be entirely Gurgaon district (`122xxx`), so
    it maps whole. `up-ncr` genuinely holds two ad-cities, and that is what forces
    `pincode_prefixes` to FOUR digits: `201xxx` alone cannot separate Noida (`2013xx`) from
    Ghaziabad (`2010–2011xx`), so a three-digit prefix would let a Noida rule measure at a
    Ghaziabad store — wrong city, wrong competitors, no error anywhere.
  - **Disambiguated names.** Ours says `aurangabad (maharashtra)`; Blinkit says
    `Aurangabad` — and separately `Aurangabad (Bihar)`, which is a DIFFERENT city. So the
    mapping is direction-aware and cannot be a symmetric string cleanup.

The generated prefixes come from the stores actually in each catalog city, so they describe
this catalog rather than a memorised list of Indian pincodes. Review before applying —
splitting a grouped city is a judgement call about which ad-city each prefix belongs to.

    python -m scripts.blinkit_city_match [--tenant <uuid>] [--out out/city_map.xlsx]
"""
import argparse
import asyncio
import sys
import difflib
from collections import defaultdict

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from campaign_manager.marketplaces.blinkit import client as bk

DEFAULT_TENANT = "a870fd8d-7373-47ec-ad69-5dd08ce35542"
MP = "blinkit"

# The judgement calls: which ad-city each pincode prefix inside a grouped catalog city
# belongs to. Everything else in this script is derived from live data.
#
# `hr-ncr` is entirely 122xxx — Gurgaon district, Manesar and the new sectors included — so
# it maps WHOLLY to Gurugram and the prefix is just "122". `up-ncr` genuinely holds two ad
# cities, which is why the prefixes there must be four digits: 201xxx alone cannot separate
# Noida (2013xx) from Ghaziabad (2010–2011xx).
#
# ⚠️ The 2032xx stores in up-ncr (Wave City, Saini, Pink City Colony) are Pilkhuwa/Hapur
# side, not Noida or Ghaziabad, and are deliberately left UNASSIGNED — an unmapped store is
# a store the picker never offers, which is recoverable; a wrongly-mapped one silently
# measures the ad's position in another city.
NCR_SPLIT = {
    "hr-ncr": {"Gurugram": ["122"]},
    "up-ncr": {"Noida": ["2013"], "Ghaziabad": ["2010", "2011"]},
}

# Below this, a fuzzy name match is reported but never written to the sheet.
_FUZZY_CUTOFF = 0.85

# Hand-confirmed pairs the automatic rules will not make on their own. Kept here rather
# than typed into the workbook so a regeneration does not silently drop them.
#   tiruchirappalli — Blinkit spells it with one 'l'. Same city (Trichy, Tamil Nadu);
#   confirmed by eye, because the fuzzy matcher is deliberately not allowed to decide this
#   class of thing (it would just as happily pair `Aurangabad` with `Aurangabad (Bihar)`).
# NOT here, and deliberately: `pilkhuwa` (1 store). Blinkit lists no such ad-city. It is a
# town in Hapur district, but Hapur is a DIFFERENT place, so mapping it there would put a
# store in a city it is not in. Left unmapped until someone decides otherwise.
MANUAL_ALIASES = {
    "tiruchirappalli": "Tiruchirapalli",
}

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def _ad_cities(tenant: str) -> dict:
    """The ad platform's city directory, {id: name} — fetched live rather than read from a
    local dump, so this works on a fresh checkout."""
    pw, browser, cl = await bk.setup(tenant)
    try:
        resp = await cl._fetch("GET", "/adservice/v2/campaigns/config")
        return ((resp or {}).get("data") or {}).get("cities") or {}
    finally:
        await browser.close()
        await pw.stop()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default=DEFAULT_TENANT)
    ap.add_argument("--out", help="write the city_map sheet to this .xlsx")
    args = ap.parse_args()

    cities = await _ad_cities(args.tenant)
    id_by_name = {str(v).strip().lower(): int(k) for k, v in cities.items() if str(k).isdigit()}

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT city, count(*) FROM marketplace_locations "
            "WHERE mp_slug = :mp AND is_active GROUP BY 1 ORDER BY 2 DESC"
        ), {"mp": MP})).all()
        prefix_rows = (await db.execute(text(
            "SELECT city, substring(pincode, 1, 4) p, count(*) FROM marketplace_locations "
            "WHERE mp_slug = :mp AND is_active AND pincode ~ '^[0-9]{6}$' "
            "GROUP BY 1, 2 ORDER BY 1, 2"
        ), {"mp": MP})).all()
        pincodes = (await db.execute(text(
            "SELECT count(*) FILTER (WHERE pincode ~ '^[0-9]{6}$'), count(*) "
            "FROM marketplace_locations WHERE mp_slug = :mp AND is_active"
        ), {"mp": MP})).first()

    ours = {(r[0] or "").strip().lower(): (r[0], r[1]) for r in rows}
    by_city_prefix = defaultdict(list)
    for city, prefix, n in prefix_rows:
        by_city_prefix[(city or "").strip().lower()].append((prefix, n))

    missing = sorted(k for k in ours if k not in id_by_name)

    print(f"{MP} ad-cities: {len(id_by_name)}   our active {MP} cities: {len(ours)}")
    print(f"usable pincodes: {pincodes[0]}/{pincodes[1]} stores")
    print(f"\nmatched by exact name: {len(ours) - len(missing)}/{len(ours)} — these need NO row")
    print(f"needing a city_map row ({len(missing)}):\n")

    sheet: list[list] = []
    for catalog_city in missing:
        label, n_stores = ours[catalog_city]
        split = NCR_SPLIT.get(catalog_city)
        if split:
            for ad_name, prefixes in split.items():
                covered = sum(n for p, n in by_city_prefix[catalog_city]
                              if any(p.startswith(x) for x in prefixes))
                print(f"   {label!r:<32} → {ad_name:<12} prefixes {','.join(prefixes):<12} "
                      f"({covered} of {n_stores} stores)")
                # A PREFIX row, deliberately with no alias: a grouped catalog name is not
                # one city, so it must not resolve by name — each store finds its own city
                # by pincode, which is what lets one bucket split into several.
                sheet.append(["", "", ad_name, ",".join(prefixes)])
            leftover = [(p, n) for p, n in by_city_prefix[catalog_city]
                        if not any(p.startswith(x) for xs in split.values() for x in xs)]
            if leftover:
                print(f"      ⚠️ unassigned prefixes in {label!r}: "
                      + ", ".join(f"{p}({n})" for p, n in leftover))
        else:
            # A disambiguated name: strip our parenthetical and see if the bare name is an
            # ad-city. ⚠️ `Aurangabad` vs `Aurangabad (Bihar)` is exactly where this could
            # map two different cities onto one, so an EXACT hit is written and anything
            # else is only reported — a near-miss is usually a spelling variant
            # (`tiruchirappalli` vs Blinkit's `tiruchirapalli`) but sometimes a neighbour.
            bare = catalog_city.split("(")[0].strip()
            guess = id_by_name.get(bare)
            if guess:
                print(f"   {label!r:<32} → {bare!r} ({n_stores} stores)")
                # An ALIAS row: our catalog's name for a place that IS one city.
                sheet.append([f"{MP}:catalog", catalog_city, bare.title(), ""])
                continue
            manual = MANUAL_ALIASES.get(catalog_city)
            if manual:
                print(f"   {label!r:<32} → {manual!r} ({n_stores} stores) [hand-confirmed]")
                sheet.append([f"{MP}:catalog", catalog_city, manual, ""])
                continue
            near = difflib.get_close_matches(bare, list(id_by_name), n=1, cutoff=_FUZZY_CUTOFF)
            if near:
                print(f"   {label!r:<32} → no exact ad-city; closest is {near[0]!r} "
                      f"({n_stores} stores) — ⚠️ add by hand if it is the same place")
            else:
                print(f"   {label!r:<32} → no ad-city by that name ({n_stores} stores) "
                      f"— ⚠️ check by hand")

    if args.out:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "city_map"
        ws.append(["source", "alias", "city", "pincode_prefixes"])
        for row in sheet:
            ws.append(row)
        wb.save(args.out)
        print(f"\nwrote {len(sheet)} rows to {args.out} — review, then paste the sheet into "
              f"config.xlsx and run `cli sync --dry-run`")


asyncio.run(main())
