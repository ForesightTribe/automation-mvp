"""Marketplace provider registry for the public scrapes.

A provider wraps one marketplace's public-search engine behind a common interface
so everything above the platform layer — `orchestrator.py` (keyword scrape),
`targeted.py` (own-SKU scrape) and `explorer/` — stays marketplace-agnostic:

    open_session(browser, lat, lon)                          -> session | None
    search(session, keyword, cap, *, lat, lon, merchant_id, follow_similarity,
           [include_oos] if search_includes_oos)
                                     -> {products, total_results, merchant_id, ok, error}
    close_session(session)                                   -> None
    parse(raw)                                               -> classified result

`search()` must return the shape above, and each product must use the shared key
names (`product_id`, `name`, `brand`, `price`, `mrp`, `unit`, `inventory`,
`in_stock`, `rating`, `position`, `merchant_id`, `merchant_type`). Translating a
marketplace's own vocabulary into those names happens INSIDE that marketplace's
engine, never here and never in a caller — that is the whole contract.

`merchant_id` is passed IN as well as returned, because the two marketplaces bind
in opposite directions (D8). Blinkit takes a coordinate and reports back which
store served it, so it ignores the argument. Zepto binds by store id header and
ignores the coordinate entirely, so without it the engine would have to spend a
second, independently rate-limited endpoint (`get_page`) resolving a store the
caller already knew — the catalog row it is iterating IS the store.

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
from scraper.platforms.zepto.public_data import endpoints as ze_ep
from scraper.platforms.zepto.public_data import parser as ze_parser
from scraper.platforms.zepto.public_data import scraper as ze_scraper

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

    # Whether this marketplace's `search()` accepts `include_oos` — i.e. whether it
    # keeps sold-out products in a SEPARATE block that must be asked for. Zepto does
    # (OOS_SEARCH_WIDGET); Blinkit returns sold-out items inline, already flagged, so
    # it has no such parameter and must never be passed one. Declared here rather than
    # probed at the call site so no caller has to branch on a marketplace name.
    search_includes_oos: bool = False

    # ── Pacing, per marketplace ──────────────────────────────────────────────
    # These were module constants in orchestrator.py, tuned for Blinkit, which has
    # no volume cap: 5 workers at 0.05 s between stores and no gap between searches.
    # Zepto enforces a per-IP VOLUME cap and dies after ONE search at that rate, so
    # the numbers cannot be shared. Each marketplace now supplies its own from its
    # endpoints.py, measured rather than guessed.
    #
    # Defaults below reproduce Blinkit's previous behaviour exactly, so a provider
    # that sets none of them behaves as before.
    search_gap_s: float = 0.0        # after every search, within a store
    store_gap_s: float = 0.05        # after every store  (the old _PACING)
    # Rest BEFORE the wall rather than crashing into it. None = no scheduled rest,
    # which is right for a marketplace with no volume cap.
    pause_every: int | None = None   # searches per worker before a scheduled rest
    pause_s: int = 0
    # On a block: wait this long, reopen the session, and let the next search act
    # as the probe. Measured recovery on Zepto is ~5 min, so a blind 15-minute
    # sleep wastes 10 minutes of every block.
    probe_every_s: int = 0
    max_block_waits: int = 0         # consecutive block waits before giving up


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
    "zepto": Provider(
        slug="zepto",
        name="Zepto",
        wired=True,
        open_session=ze_scraper.open_context_session,
        search=ze_scraper.search,
        close_session=ze_scraper.close_session,
        parse=ze_parser.parse,
        result_cap=ze_ep.RESULT_CAP,
        brand_cap=ze_ep.BRAND_RESULT_CAP,
        search_includes_oos=True,
        # All measured on a residential IP — see docs/zepto_handover.md. 12 s is the
        # floor: 6 s was tested and is SLOWER end to end, because a hard block costs
        # more than a scheduled pause.
        search_gap_s=ze_ep.SEARCH_GAP_S,
        store_gap_s=ze_ep.STORE_GAP_S,
        pause_every=ze_ep.PAUSE_EVERY,
        pause_s=ze_ep.PAUSE_S,
        probe_every_s=ze_ep.PROBE_EVERY_S,
        max_block_waits=len(ze_ep.RECOVERY_WAITS_S),
    ),
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
