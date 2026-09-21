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
