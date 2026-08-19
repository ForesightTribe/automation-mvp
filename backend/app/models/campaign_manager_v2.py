"""Campaign Manager v2 tables (`cm_*`).

Parallel to the v1 tables (D14) so v2 can be built and tested while v1 keeps running;
the v1 tables are untouched until cutover, then dropped (V6). Two deliberate shapes:

- **Config vs runtime split (Q2):** `cm_bid_rules` holds only what the user sets;
  `cm_bid_runtime` holds system-written state (`last_*`) 1:1 with the rule, updated
  in place (bounded — one row per rule, not per run). Cascade-deleted with the rule.
- **`platform` column** on config tables for MP-readiness (default `'blinkit'`).
- **`cm_run_log`** is a slim, append-only history for the UI (retention later);
  verbose narration goes to Cloud Logging, not here (D6).
"""
import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, ForeignKey, Index, Integer, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.utils.time import now_ist


class CmBudgetSchedule(SQLModel, table=True):
    __tablename__ = "cm_budget_schedules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "platform", "campaign_id",
                         name="uq_cm_bs_tenant_platform_campaign"),
        Index("idx_cm_bs_tenant", "tenant_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    campaign_id: int
    campaign_name: str
    name: str | None = None
    default_budget: float
    enabled: bool = True
    # D19 lifecycle: "active" | "stopped" (budget has no pause). The reconciler emits
    # schedules only while active; Reset → "stopped" + a set-budget→default job.
    state: str = "active"
    # Campaign activation (docs/campaign-manager.md §6): stop the campaign when
    # a rule's window ENDS — not whenever it happens to be idle. This toggle governs ONLY
    # the stop; starting is unconditional (AD7), so a schedule with the toggle OFF still
    # restarts a campaign found stopped at a window start. Default False therefore means
    # "never stopped by us", NOT "never written to".
    stop_after_window: bool = Field(default=False)
    created_at: datetime = Field(default_factory=now_ist)


class CmBudgetRule(SQLModel, table=True):
    __tablename__ = "cm_budget_rules"

    id: int | None = Field(default=None, primary_key=True)
    # Cascade-delete rules when their schedule goes.
    schedule_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("cm_budget_schedules.id", ondelete="CASCADE"),
            nullable=False, index=True,
        )
    )
    type: str = "recurring"                 # "recurring" | "once"
    days: list = Field(default=[], sa_column=Column(JSON))
    time_slots: list = Field(default=[], sa_column=Column(JSON))
    start_time: str | None = None
    end_time: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    date: str | None = None
    budget: float


class CmBidRule(SQLModel, table=True):
    """User config for a keyword bid target (system runtime lives in cm_bid_runtime)."""
    __tablename__ = "cm_bid_rules"
    __table_args__ = (Index("idx_cm_bid_tenant", "tenant_id"),)

    id: str = Field(primary_key=True)       # uuid hex
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    campaign_id: int
    campaign_name: str
    keyword: str
    match_type: str = "EXACT"
    target_position: int
    min_bid: int
    # OPTIONAL — None means "reach the target position whatever it costs". Never read
    # directly by the engine: `bid.resolve_ceiling` turns it into a concrete ceiling,
    # falling back to (and capping at) `config.BID_MAX_ABSOLUTE` so an unbounded rule
    # still has a runaway guard.
    max_bid: int | None = None
    type: str = "recurring"                 # "recurring" (daily window) | "once" (single-date span)
    date: str | None = None                 # the single day, for a "once" rule
    days: list = Field(default=[], sa_column=Column(JSON))   # weekday filter (empty = every day)
    start_time: str | None = None
    stop_time: str | None = None
    start_date: str | None = None
    stop_date: str | None = None
    active: bool = True
    # D19 lifecycle: "active" | "paused" | "stopped". active → optimizer runs; paused →
    # frozen (no control cron, resumable); stopped → off. Bid never auto-resets (freeze).
    state: str = "active"
    lat: float | None = None
    lon: float | None = None
    location_name: str | None = None
    brand_name: str | None = None
    created_at: datetime = Field(default_factory=now_ist)


class CmBidRuntime(SQLModel, table=True):
    """System-written runtime state, 1:1 with `cm_bid_rules` (Q2). Updated in place
    each run (bounded — one row per rule). Cascade-deleted with the rule."""
    __tablename__ = "cm_bid_runtime"

    rule_id: str = Field(
        sa_column=Column(
            ForeignKey("cm_bid_rules.id", ondelete="CASCADE"), primary_key=True,
        )
    )
    last_cpm: int | None = None
    last_position: float | None = None
    last_bid_updated_at: str | None = None
    # Drift-down state (cost minimisation at target). Both cleared when a window opens.
    # `last_holding_cpm` is refreshed on EVERY tick that holds target, so the snap-back
    # target tracks the market rather than a price that worked an hour ago.
    last_holding_cpm: int | None = None
    drift_paused_until: datetime | None = None
    # Unreachable-target state. When `max_bid` cannot reach `target_position`, the position
    # actually achieved at the ceiling becomes the working target so the drift can find the
    # cheapest bid that holds THAT — instead of pinning at max forever, paying the maximum
    # for a position the maximum did not buy. `effective_at_max_bid` records the ceiling it
    # was derived at: the moment the rule's `max_bid` differs, the conclusion is void (most
    # sharply when the ceiling is RAISED, where a stale relaxed target would keep the
    # optimizer drifting DOWN after being given more room). Cleared when a window opens, so
    # every day retries the real target from scratch.
    effective_target: int | None = None
    effective_at_max_bid: int | None = None
    # The size of the last raise. Escalates while the position refuses to move (we are
    # mid-tread and whatever we added wasn't enough) and resets the moment it does. NULL
    # means "start from the base step" — the state at a window open, after a riser is
    # crossed, and for a rule that has never climbed.
    raise_step: int | None = None
    updated_at: datetime = Field(default_factory=now_ist)


class CmPlatformAccount(SQLModel, table=True):
    """The marketplace ad-account (advertiser) id for a tenant, per platform. Blinkit does
    not expose this in its read APIs, so it's captured once at onboarding (from a dashboard
    PUT) and stored here; live writes send it explicitly. Per (tenant, platform) so it's
    multi-marketplace ready — see docs (B3)."""
    __tablename__ = "cm_platform_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "platform", name="uq_cm_platacct_tenant_platform"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    advertiser_id: int
    # Cutover switch (V5): OFF by default — the whole automated loop runs dry until this
    # is armed. When True, the reconciler stamps `live=true` on the tenant's engine
    # schedules and the API's set-budget/reset pass live, so scheduled + UI actions
    # write to Blinkit for real. Reversible: disarm → reconcile → back to dry.
    live_armed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=now_ist)
    updated_at: datetime = Field(default_factory=now_ist)


class CmRunLog(SQLModel, table=True):
    """Slim structured history for the UI (append-only; retention policy later).
    Verbose run narration goes to Cloud Logging, not here (D6)."""
    __tablename__ = "cm_run_log"
    __table_args__ = (Index("idx_cm_runlog_tenant", "tenant_id", "timestamp"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    run_id: str | None = None
    kind: str                               # "budget" | "bid" | "activation"
    campaign_id: int | None = None
    campaign_name: str | None = None
    keyword: str | None = None
    action: str                             # apply | skip | hold | no-op | error
    old_value: float | None = None
    new_value: float | None = None
    reason: str | None = None
    dry_run: bool = True
    success: bool = True
    timestamp: datetime = Field(default_factory=now_ist)
