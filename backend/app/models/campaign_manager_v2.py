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

from sqlalchemy import JSON, Column, ForeignKey, Index, Integer, UniqueConstraint, text
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
    # Settle-once lifecycle (campaign_manager/lifecycle.py). `ended_at` is a MATERIALIZATION
    # of the rules — written by the reconciler, never an engine gate. `settled_at` is a FACT:
    # the final teardown landed, and covers the ending whose close it is at or after.
    # ⚠️ Migration `c1e5a9d3f7b2` first, model second: a model column the DB lacks breaks
    # every SELECT on this table.
    ended_at: datetime | None = None
    settled_at: datetime | None = None
    settle_attempts: int = Field(default=0)
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
    # One LIVE automation per (tenant, platform, campaign, keyword, match type) — two of them
    # overwrite each other's bid every tick (ZC-C9). Partial: pausing sets `active=False` and
    # deliberately frees the keyword; resuming re-checks in `repo.set_bid_state`.
    # ⚠️ Migration `c4f7b2e81a93` first, model second.
    __table_args__ = (
        Index("idx_cm_bid_tenant", "tenant_id"),
        Index("uq_cm_bid_rule_live", "tenant_id", "platform", "campaign_id",
              text("lower(trim(keyword))"), text("upper(coalesce(match_type, 'EXACT'))"),
              unique=True, postgresql_where=text("active")),
    )

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
    # Lifecycle: "active" | "paused". active → the optimizer runs; paused → frozen (no
    # control cron, no end-of-window reset, no writes at all), resumable.
    #
    # ⚠️ Pausing does NOT lower the bid — it is not a decision about price, and the keyword
    # stays wherever the optimizer left it until Reset or the next window opens.
    #
    # There used to be a third value, "stopped". It was mechanically identical to "paused"
    # (every engine check is `state == "active"`), so it was two words for one behaviour
    # plus a Stop button with no undo. Removed 2026-09-07; no rows carried it.
    state: str = "active"
    # Settle-once lifecycle — see CmBudgetSchedule and campaign_manager/lifecycle.py.
    # ⚠️ Migration `c1e5a9d3f7b2` first, model second.
    ended_at: datetime | None = None
    settled_at: datetime | None = None
    settle_attempts: int = Field(default=0)
    lat: float | None = None
    lon: float | None = None
    location_name: str | None = None
    brand_name: str | None = None
    # The city this rule MEASURES in, when it was saved by city. The engine then resolves that
    # city's frozen store (`cm_city_stores`) on every run, and `lat`/`lon`/`location_name`
    # above are only the snapshot lists show. NULL = pinned to `lat`/`lon` (saved by an
    # explicit store or coordinates). ⚠️ Migration `d7c3e9a1f5b2` first, model second.
    city_id: int | None = Field(default=None, foreign_key="cities.id")
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
    # What `last_position` / `effective_target` were measured in. "ad_slot" since the switch to
    # ad-slot targets (campaign_manager/ad_slots.py); NULL = page positions, written before it.
    # The engine ignores the learned state on a row that isn't "ad_slot" and rewrites it
    # (`bid.slot_state_is_stale`) — the migration does not wipe it, because the old code keeps
    # writing page positions until the new code is deployed.
    # ⚠️ Migration `b8e2d4f6a1c3` first, model second.
    measured_in: str | None = None
    updated_at: datetime = Field(default_factory=now_ist)


class CmCityStore(SQLModel, table=True):
    """The dark stores a CITY's bid automations measure at — a frozen, ranked set.

    A bid rule names a city. Before this table the store inside it was the city's lowest
    `merchant_id` — deterministic, but a store nobody chose — baked into the rule at save
    time, so moving it meant editing every rule.

    `rank` 1 is the ANCHOR; ranks 2..`config.max_stores` validate it. The bid aims for the
    target position at every store in the set where the campaign is in stock — the worst such
    store binds (campaign_manager/coverage.py).

    Two layers, resolved on every bid run (`repo.pick_city_stores`), both set from the CLI only
    (`cm stores set`):
      - `tenant_id` NULL → the GLOBAL set for the city, used by every client without its own;
      - `tenant_id` set  → one client's set, which REPLACES the global set whole — never mixed
        rank by rank — e.g. a brand not stocked at the global stores.

    `merchant_id`, not a FK to `marketplace_locations.id`: `cli sync --prune` deletes and
    re-creates catalog rows, and the merchant id is the store's natural key across that. A
    frozen store that leaves the catalog is skipped at resolve time, never honoured.

    The two partial unique indexes give one store per rank per city, for the global layer and
    per client — a plain UNIQUE would let NULL tenants repeat.

    ⚠️ Migration `d7c3e9a1f5b2` first, model second.
    """
    __tablename__ = "cm_city_stores"
    __table_args__ = (
        Index("uq_cm_city_store_global", "platform", "city_id", "rank", unique=True,
              postgresql_where=text("tenant_id IS NULL")),
        Index("uq_cm_city_store_tenant", "tenant_id", "platform", "city_id", "rank",
              unique=True, postgresql_where=text("tenant_id IS NOT NULL")),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID | None = Field(default=None, foreign_key="tenants.id")
    platform: str = "blinkit"
    city_id: int = Field(foreign_key="cities.id")
    merchant_id: str
    rank: int = Field(default=1)
    created_at: datetime = Field(default_factory=now_ist)
    updated_at: datetime = Field(default_factory=now_ist)


class CmStoreStock(SQLModel, table=True):
    """Our catalogue at one measurement store, with availability — the bid engine's stock cache.

    One row per (tenant, marketplace, store), replaced on every SUCCESSFUL brand-search read
    (campaign_manager/stock.py). A failed read writes nothing, so a store with no row — or one
    older than `CM_STOCK_MAX_AGE_MINUTES` — is "stock unknown", which never stops a raise
    (campaign_manager/coverage.py).

    `products` = our brand's products the read found: `[{pid, name, in_stock, inventory}]`.
    `complete` = the read reached the end of our brand's block. Only then may a campaign
    product missing from `products` be treated as not sold at the store.

    Tenant-scoped: the catalogue is the client's brand at a store, not the store's shelf.
    `merchant_id` is the store we ASKED about (a `cm_city_stores` store); `served_by` is the
    express store Blinkit reported answering, kept for diagnosis.

    ⚠️ Migration `f3c8a1d6b9e2` first, model second.
    """
    __tablename__ = "cm_store_stock"
    __table_args__ = (
        UniqueConstraint("tenant_id", "platform", "merchant_id", name="uq_cm_store_stock"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    merchant_id: str
    served_by: str = ""
    complete: bool = False
    products: list = Field(default=[], sa_column=Column(JSON))
    checked_at: datetime = Field(default_factory=now_ist)


class CmBidStoreRead(SQLModel, table=True):
    """One store's reading for one keyword automation on one bid tick — append-only.

    `cm_run_log` records the DECISION (one row per tick); this records what each store showed
    on the way to it, so "held at ₹121 by Store C" can be checked after the fact. `binding`
    marks the store whose position the decision acted on (the worst counted one).

    `eligibility` (eligible / out_of_stock / not_listed / unknown) and `verdict` (sponsored /
    absent / skipped / error) are campaign_manager/coverage.py's vocabulary. `bid` is the bid
    in force when the store was read.

    Grows with TIME (a row per store per in-window tick), so it is trimmed to
    `CM_STORE_READS_RETENTION_DAYS` as it is written. No FKs to rules or cities, like
    `cm_run_log`: history outlives what it describes.

    ⚠️ Migration `f3c8a1d6b9e2` first, model second.
    """
    __tablename__ = "cm_bid_store_reads"
    __table_args__ = (
        Index("idx_cm_store_reads_tenant", "tenant_id", "observed_at"),
        Index("idx_cm_store_reads_rule", "rule_id", "observed_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    run_id: str | None = None
    rule_id: str | None = None
    campaign_id: int
    keyword: str
    city_id: int | None = None
    merchant_id: str = ""
    store_label: str = ""
    rank: int = 1
    bid: int | None = None
    eligibility: str
    verdict: str
    # Our ad's PAGE position, when it held a slot. The slot itself — what the decision acted
    # on (campaign_manager/ad_slots.py) — is `ad_slot`.
    position: float | None = None
    # ⚠️ Migration `b8e2d4f6a1c3` first, model second — these three.
    ad_slot: int | None = None
    # The page as we saw it (sponsored / absent readings only): every ad's page position, and
    # our organic listings' (product-id match). Organic never decides a bid; it feeds the
    # "already showing organically above your target" warning.
    ad_positions: list | None = Field(default=None, sa_column=Column(JSON))
    organic_positions: list | None = Field(default=None, sa_column=Column(JSON))
    binding: bool = False
    detail: str | None = None
    dry_run: bool = True
    observed_at: datetime = Field(default_factory=now_ist)


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
    # NULLABLE since Zepto (migration c8f4e91a37d2): not every marketplace hides its
    # ad account. Blinkit exposes the advertiser id in NO read API, so it must be
    # captured once and stored — a stale value there writes real money to a dead
    # account. Zepto returns its account in the login response, so there is nothing
    # to store and this stays null.
    advertiser_id: int | None = None
    # For marketplaces whose account id is not an int (Zepto's is a UUID). Used as an
    # ASSERTION rather than a value to send: `adapter.set_advertiser` refuses the
    # write unless the live session's accounts contain it. Derivable AND checkable
    # beats storing-and-trusting.
    #
    # ⚠️ This field and its migration must move together. Adding it to the model
    # first makes every SELECT here ask for a column that does not exist, which
    # breaks every `cm` operation instantly — the same ordering that broke arming
    # once before. Migration first, model second.
    account_ref: str | None = None
    # Cutover switch (V5): OFF by default — the whole automated loop runs dry until this
    # is armed. When True, the reconciler stamps `live=true` on the tenant's engine
    # schedules and the API's set-budget/reset pass live, so scheduled + UI actions
    # write to Blinkit for real. Reversible: disarm → reconcile → back to dry.
    live_armed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=now_ist)
    updated_at: datetime = Field(default_factory=now_ist)


class CmRunLog(SQLModel, table=True):
    """Structured history for the UI — **every tick, not just the changes** (append-only).

    Until 2026-09-04 a tick that changed nothing wrote no row: "held at ₹201 because the
    position is already at target" lived only in Cloud Logging, which is not joinable to our
    data and cannot be shown in the product. A per-automation view needs those ticks most of
    all — "why did my bid not move for six hours" is the question people actually ask.

    Verbose narration still goes to Cloud Logging (D6); this is the queryable subset.

    ⚠️ This table now grows with TIME rather than with ACTIVITY (~4 rows/hour per in-window
    keyword). It needs a retention policy.
    """
    __tablename__ = "cm_run_log"
    __table_args__ = (
        Index("idx_cm_runlog_tenant", "tenant_id", "timestamp"),
        # Every tick writes a row now, so the per-campaign drill-down must not scan the
        # whole tenant's history.
        Index("idx_cm_runlog_campaign", "tenant_id", "campaign_id", "timestamp"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    run_id: str | None = None
    kind: str                               # "budget" | "bid" | "activation"
    campaign_id: int | None = None
    campaign_name: str | None = None
    keyword: str | None = None
    action: str                             # apply | skip | hold | no-op | error
    # Which automation this decision belongs to. NOT a foreign key on purpose: history must
    # outlive the rule it describes, and budget/activation rows point at a different table.
    # TEXT, not int: a bid rule's id is a uuid hex string (`cm_bid_rules.id`) and the bid
    # engine is the only writer. It was created as INTEGER, which made EVERY bid tick that
    # carried a rule_id fail its history write (asyncpg DataError) from 2026-09-04 until
    # a4e7c2f19b83 — after the bids had already been written to Blinkit. A budget rule's
    # int id, if ever logged, is stored as its string form.
    rule_id: str | None = None
    old_value: float | None = None
    new_value: float | None = None
    # The observed search position, and the target it was judged against — the two inputs to
    # every bid decision. They used to exist only as prose inside `reason`, which meant a UI
    # could show THAT a decision happened but never why.
    #
    # Since the switch to ad-slot targets (2026-10, campaign_manager/ad_slots.py): `target` and
    # `ad_slot` are AD SLOTS — what the decision compared — and `position` is where our slot
    # sat on the PAGE. Older rows have no `ad_slot`, and their `position`/`target` are page
    # positions. `measured_in` = "ad_slot" says which — it is the only tell on a "not showing"
    # row, where `ad_slot` and `position` are both empty.
    # ⚠️ Migration `b8e2d4f6a1c3` first, model second (`ad_slot`, `measured_in`).
    position: float | None = None
    target: int | None = None
    ad_slot: int | None = None
    measured_in: str | None = None
    reason: str | None = None
    dry_run: bool = True
    success: bool = True
    timestamp: datetime = Field(default_factory=now_ist)
