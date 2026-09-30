"""The marketplace seam (D17).

All marketplace-specific code (API client, reverse-engineered payloads, position
lookup, the read/apply *mechanism*) lives under `marketplaces/<slug>/`. The
orchestration above (budget/bid/reconciler/writes-policy) stays MP-agnostic.

`base.py` documents the contract every adapter satisfies — written once TWO
marketplaces existed, so it describes a real seam rather than one implementation's
shape.

Adding a marketplace is one entry in `_ADAPTERS` below plus a package. Imports are
deferred inside `get_adapter` on purpose: `campaign_manager` is imported by the API
process (Render), which must never pull in Playwright — an eager import here would
drag a browser dependency into a web worker that is forbidden from launching one.
"""

# slug -> "module path", resolved lazily. Keep the slugs identical to
# `platform_sessions.platform` and to the `marketplace` job param.
_ADAPTERS: dict[str, str] = {
    "blinkit": "campaign_manager.marketplaces.blinkit.adapter",
    "zepto": "campaign_manager.marketplaces.zepto.adapter",
}


# Each marketplace's status vocabulary, as a PURE module the API may import (the adapters
# may not be — Blinkit's pulls in Playwright).
_STATUS: dict[str, str] = {
    "blinkit": "campaign_manager.marketplaces.blinkit.status",
    "zepto": "campaign_manager.marketplaces.zepto.status",
}


def canonical_status(slug: str | None, raw: str | None) -> str | None:
    """A marketplace's raw campaign status → `running` / `paused` / `held` / `ended` /
    `draft`, exactly as the engines read it. Safe to call from the API process.

    An unknown marketplace, or an unmapped status, comes back unchanged — the same
    "refuse it by name, never coerce it" rule the adapters follow.
    """
    path = _STATUS.get((slug or "").lower())
    if path is None:
        return raw
    from importlib import import_module
    return import_module(path).canonical(raw)


# Which campaigns a marketplace lets the automations touch, as a PURE module (ZC-C3). A
# marketplace with no entry puts no limit on it (Blinkit).
_ELIGIBILITY: dict[str, str] = {
    "zepto": "campaign_manager.marketplaces.zepto.eligibility",
}


def automation_refusal(slug: str | None, campaign_type: str | None,
                       bid_targeting: str | None) -> str | None:
    """Why a campaign of this type may not be automated on this marketplace, or None.
    From catalogue fields, so it is safe to call from the API process."""
    path = _ELIGIBILITY.get((slug or "").lower())
    if path is None:
        return None
    from importlib import import_module
    return import_module(path).refusal(campaign_type, bid_targeting)


def rule_needs_location(slug: str | None) -> bool:
    """Must a bid rule on this marketplace name a city or a store (ZC-C14)? API-safe."""
    path = _ELIGIBILITY.get((slug or "").lower())
    if path is None:
        return False
    from importlib import import_module
    return bool(getattr(import_module(path), "RULE_NEEDS_LOCATION", False))


# Keyword match types each marketplace bids on, in OUR vocabulary (ZC-D8). Blinkit's BROAD
# travels as SMART inside its adapter; PHRASE exists on Zepto only.
_MATCH_TYPES: dict[str, tuple[str, ...]] = {
    "blinkit": ("EXACT", "BROAD"),
    "zepto": ("EXACT", "PHRASE", "BROAD"),
}


def match_types(slug: str | None) -> tuple[str, ...]:
    """The match types a bid rule may use on this marketplace; () when unknown."""
    return _MATCH_TYPES.get((slug or "").lower(), ())


def min_daily_budget(slug: str | None) -> float | None:
    """The marketplace's PUBLISHED minimum daily budget, or None when it publishes none.

    Zepto publishes ₹500 (`campaigns/metadata`). Blinkit publishes no such field — its
    dashboard derives one in the browser — so it has none here and stays the judge itself.
    API-safe: Zepto's `endpoints` module is constants only."""
    if (slug or "").lower() == "zepto":
        from campaign_manager.marketplaces.zepto import endpoints as zep
        return float(zep.MIN_DAILY_BUDGET)
    return None


def keyword_bidding_refusal(slug: str | None) -> str | None:
    """Why keyword-bid automations are off on this marketplace, or None when they are on.

    Zepto: OFF for now (2026-09-29, Deepansh — "option C"). The bid engine reads our rank
    from Zepto's shopper site, and Zepto's firewall refuses the VM's data-centre address;
    a residential proxy works but was judged not worth its per-GB cost yet. Budget
    automations, start/stop and one-time ops do not touch the shopper site and stay on.
    Everything bidding needs (adapter, rotation, stock check) is still here — turning it
    back on is `CM_ZEPTO_KEYWORD_BIDDING=1` (e.g. for a supervised test from a home IP).
    API-safe: config is constants only."""
    from campaign_manager import config
    if (slug or "").lower() == "zepto" and not config.ZEPTO_KEYWORD_BIDDING:
        return ("Keyword automations aren't available on Zepto yet. Budget automations, "
                "start/stop and one-time changes are.")
    return None


def supported() -> list[str]:
    """Marketplaces the campaign manager can drive. Used by CLI help and errors."""
    return sorted(_ADAPTERS)


def get_adapter(slug: str):
    """Return the adapter module for a marketplace.

    Raises ValueError naming the valid options — a typo'd `--marketplace` should
    say what it should have been, not fail somewhere deeper with an AttributeError.
    """
    path = _ADAPTERS.get(slug)
    if path is None:
        raise ValueError(
            f"no campaign-manager adapter for marketplace {slug!r}. "
            f"Valid: {', '.join(supported())}"
        )
    from importlib import import_module

    try:
        return import_module(path)
    except ModuleNotFoundError as e:
        # Registered but not built yet — say so plainly rather than surfacing a
        # bare import error that looks like a broken installation.
        raise ValueError(
            f"marketplace {slug!r} is registered but its adapter is not implemented "
            f"yet ({path}): {e}"
        ) from e
