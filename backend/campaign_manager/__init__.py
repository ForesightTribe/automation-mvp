"""Campaign Manager v2 — Blinkit budget scheduler + bid optimizer (parallel build).

See docs/campaign-manager-refactor.md (the design) and
docs/campaign-manager-v2-implementation.md (the build plan). This package is the
v2 domain logic; it runs alongside the v1 code in `ad_campaigns/` + `ads_service`
until cutover, then v1 is deleted.

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
