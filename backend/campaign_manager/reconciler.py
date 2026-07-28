"""Reconciler — compile a tenant's rules into `job_schedules` rows (MP-agnostic).

Runner-owned: the API enqueues a `cm.reconcile` job on any rule change; this reads
the current rules and makes `job_schedules` match them, idempotently (deterministic
names → create missing / update changed / delete no-longer-wanted). Schedules are
written at edit time and stay dormant until they fire:
  - recurring windows  → a cron `job_schedules` row (future-start via next_run_at)
  - one-time / expiry   → a one-shot row (repeat=false — needs the V3.0 jobs-system
                          enhancement)

**V0 scaffold:** entry point + logging only. The full compile lands in **V3** (and
depends on the `repeat`/one-shot flag from V3.0).
"""
import uuid

from campaign_manager import config, logs


async def reconcile(tenant_id: uuid.UUID, *, dry_run: bool | None = None,
                    platform: str = "blinkit") -> dict:
    dry_run = config.DRY_RUN_DEFAULT if dry_run is None else dry_run
    run_id = logs.new_run_id()
    logs.run_start(run_id, "reconcile", tenant_id, dry_run=dry_run, platform=platform)

    # ── V3 goes here ──────────────────────────────────────────────────────────
    #   rules → desired job_schedules (deterministic names) → create/update/delete
    created = updated = deleted = 0

    logs.run_summary(run_id, "reconcile", dry_run=dry_run,
                     processed=created + updated + deleted, applied=created + updated,
                     skipped=0, errors=0)
    return {"created": created, "updated": updated, "deleted": deleted}
