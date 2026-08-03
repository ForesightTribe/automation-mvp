"""Marketplace provider registry for the public scrapes.

A provider wraps one marketplace's public-search engine behind a common interface
so everything above the platform layer — `orchestrator.py` (keyword scrape),
`targeted.py` (own-SKU scrape) and `explorer/` — stays marketplace-agnostic:

    open_session(browser, lat, lon)                          -> session | None
    search(session, keyword, cap, *, lat, lon, follow_similarity)
                                     -> {products, total_results, merchant_id, ok, error}
    close_session(session)                                   -> None
    parse(raw)                                               -> classified result

`search()` must return the shape above, and each product must use the shared key
names (`product_id`, `name`, `brand`, `price`, `mrp`, `unit`, `inventory`,
`in_stock`, `rating`, `position`, `merchant_id`, `merchant_type`). Translating a
marketplace's own vocabulary into those names happens INSIDE that marketplace's
engine, never here and never in a caller — that is the whole contract.

`parse` is optional: the Explorer works off raw products and does its own
classification, while the per-tenant orchestrator needs the platform's
`parser.parse()` to build a snapshot header. A provider without one can still be
used by the Explorer.

Registering a marketplace as `wired=False` is deliberate: selecting it fails fast
with a clear message instead of silently scraping something else.

This started life inside `explorer/` and graduated here when the per-tenant
orchestrators adopted it; `explorer/providers.py` now re-exports from this module.
"""
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from scraper.platforms.blinkit.public_data import endpoints as bl_ep
from scraper.platforms.blinkit.public_data import parser as bl_parser
from scraper.platforms.blinkit.public_data import scraper as bl_scraper

OpenSession = Callable[..., Awaitable[dict | None]]
Search = Callable[..., Awaitable[dict]]
CloseSession = Callable[[dict], Awaitable[None]]
Parse = Callable[[dict], dict]


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
    parse: Parse | None = None
    # Cap FLOORS, from the marketplace's own endpoints.py. These apply only when the
    # tenant configures no `keyword_cap`/`brand_cap` and the CLI passes no override —
    # they are the last fallback, not the usual value.
    result_cap: int = 48
    brand_cap: int = 60


_PROVIDERS: dict[str, Provider] = {
    "blinkit": Provider(
        slug="blinkit",
        name="Blinkit",
        wired=True,
        open_session=bl_scraper.open_context_session,
        search=bl_scraper.search,
        close_session=bl_scraper.close_session,
        parse=bl_parser.parse,
        result_cap=bl_ep.RESULT_CAP,
        brand_cap=bl_ep.BRAND_RESULT_CAP,
    ),
    # Modules exist but on the old one-shot interface — not yet on the session-reuse
    # interface the worker pool needs. See docs/zepto.md.
    "instamart": Provider(slug="instamart", name="Instamart", wired=False),
    "zepto": Provider(slug="zepto", name="Zepto", wired=False),
}

DEFAULT_MARKETPLACE = "blinkit"


def get_provider(slug: str) -> Provider:
    """The wired provider for `slug`, or a clear error if unknown / not yet wired."""
    p = _PROVIDERS.get((slug or "").lower())
    if p is None:
        raise ValueError(
            f"Unknown marketplace '{slug}'. Known: {', '.join(_PROVIDERS)}."
        )
    if not p.wired:
        raise ValueError(
            f"Marketplace '{slug}' is not yet supported "
            f"(supported: {', '.join(supported_marketplaces())})."
        )
    return p


def supported_marketplaces() -> list[str]:
    """Slugs of the wired marketplaces — the CLI validates against this, and the
    frontend selector reads it."""
    return [slug for slug, p in _PROVIDERS.items() if p.wired]


def all_marketplaces() -> list[dict[str, Any]]:
    """Every registered marketplace with its wired flag (for a UI selector that
    shows unavailable ones greyed out)."""
    return [{"slug": p.slug, "name": p.name, "wired": p.wired} for p in _PROVIDERS.values()]
