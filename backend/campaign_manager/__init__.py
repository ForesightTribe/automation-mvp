"""Campaign Manager — budget scheduler + bid optimizer, across marketplaces.

See docs/campaign-manager.md. This package is the whole of campaign automation: the v1
engine it was built to replace (`ad_campaigns/`, plus its half of `ads_service` and the
`/ads/budget-schedules` + `/ads/bid-optimizer` API and UI) was retired and DELETED on
2026-09-03. Its DB tables outlive it for now — see the doc's cleanup notes.

Layout:
  config.py       guardrail bounds + the dry-run default
  logs.py         structured, dry-run-aware logging (docs §12.2)
  repo.py         tenant-scoped DB reads/writes (cm_* tables — NO JSON)
  writes.py       ⭐ the gated write choke-point — the ONLY place that mutates Blinkit
  budget.py       budget-scheduler orchestration (MP-agnostic)
  bid.py          bid-optimizer orchestration (MP-agnostic)
  reconciler.py   rules → job_schedules (MP-agnostic)
  marketplaces/   the MP seam — all Blinkit-specific code lives under marketplaces/blinkit/
"""
