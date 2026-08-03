"""Back-compat re-export — the registry now lives at `scraper/public/providers.py`.

It graduated out of the explorer package when the per-tenant orchestrators
(`orchestrator.py` / `targeted.py`) adopted the same abstraction, which is exactly
the condition this module's original docstring set for the move. Import from
`scraper.public.providers` in new code.
"""
from scraper.public.providers import (  # noqa: F401
    Provider,
    all_marketplaces,
    get_provider,
    supported_marketplaces,
)

__all__ = ["Provider", "all_marketplaces", "get_provider", "supported_marketplaces"]
