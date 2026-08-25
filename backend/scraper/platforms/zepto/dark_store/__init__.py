"""Zepto dark store DISCOVERY — pincode/area tables and the coordinate locator.

WHY THIS EXISTS AND BLINKIT HAS NO EQUIVALENT
---------------------------------------------
Blinkit's 2,059-store catalog was supplied as an export; nobody had to find those
stores. No such file exists for Zepto, so the catalog was BUILT — a pincode sweep
plus a 666 m grid scan across 58 cities, which is what these tables feed.

NOT PART OF THE SCRAPE PATH
---------------------------
The scraper never imports this. Locations reach it as:

    dark_store/ + scripts/zepto_discover_*.py   ->  master xlsx
                                                ->  config.xlsx  (mp=zepto)
                                                ->  cli sync
                                                ->  marketplace_locations
                                                ->  scraper reads the DB

This package is step ONE only — how the list was produced in the first place.

WHY IT IS KEPT
--------------
Dark stores open and close. Bengaluru alone went 134 -> 169 during this build.
With these tables the catalog can be refreshed in a day; without them a refresh
means rediscovering the grid resolution, outlier handling, phantom-store detection
and prefix attribution from scratch — roughly a week's work.

Blinkit refreshes its catalog by asking whoever supplies the export. For Zepto we
ARE that supplier, and this is the machinery.

Imported by scripts/zepto_discover_city_full.py, zepto_discover_all_cities.py and
export_all_pincodes.py. See docs/zepto_phase0_handover.md.
"""
