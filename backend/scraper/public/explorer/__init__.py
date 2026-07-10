"""Explorer engine — ad-hoc, ephemeral custom scrape → Excel (agency-facing).

Reuses the public scrape engine but driven by an `ExplorerSpec` instead of a
tenant watchlist, accumulating results in memory (no fact-table writes) under one
`explorer_runs` record. See docs/explorer.md.
"""
from scraper.public.explorer.export import write_workbook
from scraper.public.explorer.insights import build_insights
from scraper.public.explorer.orchestrator import ExplorerResult, run_explorer
from scraper.public.explorer.providers import (
    Provider,
    all_marketplaces,
    get_provider,
    supported_marketplaces,
)

__all__ = [
    "run_explorer",
    "ExplorerResult",
    "build_insights",
    "write_workbook",
    "Provider",
    "get_provider",
    "supported_marketplaces",
    "all_marketplaces",
]
