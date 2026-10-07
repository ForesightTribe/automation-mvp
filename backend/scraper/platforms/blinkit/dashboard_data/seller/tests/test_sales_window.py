"""Blinkit seller sales window (`scrape blinkit-seller`), 2026-10-07.

Every run re-scrapes the 4 days up to yesterday (was yesterday only), so a failed or missed
run heals on the next one. Explicit --from / --to still win.

    python -m pytest scraper/platforms/blinkit/dashboard_data/seller/tests/test_sales_window.py
"""
from datetime import date, timedelta

from cli.commands import scrape as cli_scrape


def test_default_is_the_4_days_up_to_yesterday():
    y = date.today() - timedelta(days=1)
    days = cli_scrape._date_range(None, None)
    assert days == [(y - timedelta(days=i)).isoformat() for i in (3, 2, 1, 0)]
    assert cli_scrape.BLINKIT_SALES_DAYS == 4


def test_to_alone_counts_back_from_it():
    assert cli_scrape._date_range(None, "2026-10-05") == [
        "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"]


def test_explicit_window_wins():
    assert cli_scrape._date_range("2026-09-01", "2026-09-02") == ["2026-09-01", "2026-09-02"]
    assert cli_scrape._date_range("2026-10-06", "2026-10-06") == ["2026-10-06"]
