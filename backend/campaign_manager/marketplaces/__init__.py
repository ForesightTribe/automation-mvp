"""The marketplace seam (D17).

All marketplace-specific code (API client, reverse-engineered payloads, position
scraping, the read/apply *mechanism*) lives under `marketplaces/<slug>/`. The
orchestration above (budget/bid/reconciler/writes-policy) stays MP-agnostic.

`get_adapter(slug)` returns the adapter module for a marketplace. Only `blinkit`
exists today; `base.py` (the abstract interface) is deliberately deferred until a
second MP lands — see D17.
"""


def get_adapter(slug: str):
    if slug == "blinkit":
        from campaign_manager.marketplaces import blinkit
        return blinkit.adapter
    raise ValueError(f"no campaign-manager adapter for marketplace {slug!r}")
