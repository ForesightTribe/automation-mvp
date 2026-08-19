"""Shared phrasing for the strings an export prints — window labels, context
lines, freshness. Kept apart from `build.py` so sections can use it without an
import cycle, and in one place so every sheet phrases the same thing the same way.
"""
from datetime import date, datetime

_KIND = {
    "main": "Main SKUs (combos excluded)",
    "combo": "Combos and multipacks only",
    "all": "Main SKUs and combos",
}
_KIND_SHORT = {"main": "Main SKUs", "combo": "Combos", "all": "All products"}


def window_label(start: date, end: date) -> str:
    """'1 – 7 Aug 2026', collapsing to a single date when the range is one day."""
    if start == end:
        return f"{_day(start)} {start.strftime('%b %Y')}"
    if (start.year, start.month) == (end.year, end.month):
        return f"{_day(start)} – {_day(end)} {end.strftime('%b %Y')}"
    if start.year == end.year:
        return f"{_day(start)} {start.strftime('%b')} – {_day(end)} {end.strftime('%b %Y')}"
    return f"{_day(start)} {start.strftime('%b %Y')} – {_day(end)} {end.strftime('%b %Y')}"


def kind_label(kind: str, *, short: bool = False) -> str:
    return (_KIND_SHORT if short else _KIND).get(kind, kind)


def context_line(spec, *extra: str) -> str:
    """The grey line under every sheet title: window · marketplace · filter · N."""
    parts = [
        window_label(spec.start, spec.end),
        (spec.marketplace or "all marketplaces").title(),
        kind_label(spec.kind, short=True),
    ]
    if spec.city:
        parts.insert(2, spec.city.title())
    parts += [p for p in extra if p]
    return " · ".join(parts)


def freshness(scraped_at: datetime | None, *, today: date | None = None) -> tuple[str, str]:
    """('Scraped 7 Aug 2026', '3 days ago — collected weekly, not live').

    Public data is weekly, so a workbook that doesn't say how old it is invites
    someone to read a stale number as live. Both halves are always shown.
    """
    if scraped_at is None:
        return ("No scrape in this window", "the sheets below will be empty")
    when = scraped_at.date()
    days = ((today or date.today()) - when).days
    if days <= 0:
        age = "today"
    elif days == 1:
        age = "yesterday"
    else:
        age = f"{days} days ago"
    return (f"Scraped {_day(when)} {when.strftime('%b %Y')}",
            f"{age} — collected weekly, not live")


def _day(d: date) -> str:
    """Day without a leading zero. `%-d`/`%#d` are platform-specific and this
    runs on both Windows (dev) and Linux (the VM), so format it by hand."""
    return str(d.day)
