"""Marketplace provider registry for the Explorer.

A provider wraps one marketplace's public-search engine behind a common interface
so the orchestrator stays marketplace-agnostic:

    open_session(browser, lat, lon)                          -> session | None
    search(session, keyword, cap, *, lat, lon, follow_similarity)
                                     -> {products, total_results, merchant_id, ok, error}
    close_session(session)                                   -> None

Blinkit already exposes exactly this (`open_context_session` / `search` /
`close_session`). Instamart and Zepto have public modules but only on the older
one-shot interface, so they are registered as NOT wired until refactored onto
this one — selecting them fails fast with a clear message.

`providers.py` lives inside the explorer package for now; if the per-tenant
orchestrators (`orchestrator.py` / `targeted.py`) later adopt the same
abstraction it can graduate to `scraper/public/providers.py`.
"""
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from scraper.platforms.blinkit.public_data import scraper as bl_scraper

OpenSession = Callable[..., Awaitable[dict | None]]
Search = Callable[..., Awaitable[dict]]
CloseSession = Callable[[dict], Awaitable[None]]


@dataclass(frozen=True)
class Provider:
    """A marketplace's public-search engine behind the common interface. A pure
    data record (the callables) — no behaviour of its own."""

    slug: str
    name: str
    wired: bool
    open_session: OpenSession | None = None
    search: Search | None = None
    close_session: CloseSession | None = None


_PROVIDERS: dict[str, Provider] = {
    "blinkit": Provider(
        slug="blinkit",
        name="Blinkit",
        wired=True,
        open_session=bl_scraper.open_context_session,
        search=bl_scraper.search,
        close_session=bl_scraper.close_session,
    ),
    # Modules exist but on the old one-shot interface — not yet on the session-reuse
    # interface the worker pool needs.
    "instamart": Provider(slug="instamart", name="Instamart", wired=False),
    "zepto": Provider(slug="zepto", name="Zepto", wired=False),
}


def get_provider(slug: str) -> Provider:
    """The wired provider for `slug`, or a clear error if unknown / not yet wired."""
    p = _PROVIDERS.get((slug or "").lower())
    if p is None:
        raise ValueError(
            f"Unknown marketplace '{slug}'. Known: {', '.join(_PROVIDERS)}."
        )
    if not p.wired:
        raise ValueError(
            f"Marketplace '{slug}' is not yet supported by Explorer "
            f"(supported: {', '.join(supported_marketplaces())})."
        )
    return p


def supported_marketplaces() -> list[str]:
    """Slugs of the wired marketplaces — the future frontend selector reads this."""
    return [slug for slug, p in _PROVIDERS.items() if p.wired]


def all_marketplaces() -> list[dict[str, Any]]:
    """Every registered marketplace with its wired flag (for a UI selector that
    shows unavailable ones greyed out)."""
    return [{"slug": p.slug, "name": p.name, "wired": p.wired} for p in _PROVIDERS.values()]
