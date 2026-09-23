"""Business logic for the Campaign Manager v2 API — routes stay thin (§0 / D2).

Orchestrates the `campaign_manager` domain layer (`repo`) + the jobs queue. Every rule
mutation enqueues `cm.reconcile` (so the VM rewrites `job_schedules`); on-demand actions
enqueue a job and return its id to poll. **No Playwright** — only DB rows + enqueue.

Convention: functions return schema DTOs (or None for not-found / access-denied, which the
route maps to 404); a `DuplicateActiveJob` from the queue propagates for the route to 409.
"""
import uuid
from datetime import timedelta

from app.models.job import Job
from app.schemas.campaign_manager import (
    BidContextOut, KeywordBidRange, TargetedCity,
    BidRuleIn, BidRuleOut, BidRuleUpdate, BudgetRuleIn, BudgetRuleOut, BudgetRuleUpdate,
    BudgetScheduleIn, BudgetScheduleOut, BudgetScheduleUpdate, CmActionOut, CmJobOut,
    RunLogOut,
)
from app.utils.time import now_ist
# `window` is the same pure module the engines decide with, so the status the UI shows is
# the logic the engines act on — and it pulls in no Playwright (the app-layer rule holds).
from campaign_manager import repo, window
from jobs.queue import enqueue

PLATFORM = "blinkit"


class EditError(ValueError):
    """A rejected edit (e.g. editing a spent one-time rule) — the route maps it to 400."""


class WrongMarketplace(EditError):
    """The campaign belongs to a different marketplace than this API drives. A 400: the
    request itself is wrong, and retrying it will never succeed."""


class StateError(ValueError):
    """The action is fine, the automation is just not in a state where it makes sense —
    resuming one that is already running, pausing one that has ended, resetting one that
    the optimizer will bid straight back up. Mapped to 409, not 400: nothing about the
    REQUEST is wrong, and the same call may well succeed a minute later."""


# ── helpers ─────────────────────────────────────────────────────────────────

async def _reconcile(session, tenant_id: uuid.UUID) -> None:
    """Enqueue a live reconcile so the VM rewrites this tenant's job_schedules. A queued
    reconcile already covers later edits (it reads current rules at run time)."""
    from jobs.queue import DuplicateActiveJob
    try:
        await enqueue(session, job_type="cm.reconcile", tenant_id=tenant_id, params={"live": "true"})
    except DuplicateActiveJob:
        pass


async def _require_marketplace(tenant_id: uuid.UUID, campaign_id: int) -> None:
    """Refuse a campaign that only another marketplace's catalogue knows.

    Every path that takes a campaign id from the caller and turns it into an automation or
    a job goes through this. Without it, a Zepto campaign picked from the merged
    `/ads/campaigns` list was saved as a `PLATFORM` automation and its id sent to that
    marketplace's ad account.

    A campaign no catalogue has seen is allowed — one created since the last scrape is a
    normal state, and refusing it would make it unautomatable until tomorrow.
    """
    found = await repo.campaign_marketplaces(tenant_id, campaign_id)
    if found and PLATFORM not in found:
        other = ", ".join(sorted(p.title() for p in found))
        raise WrongMarketplace(
            f"Campaign {campaign_id} is a {other} campaign. Automations here run on "
            f"{PLATFORM.title()} only, so nothing was created.")


async def _reapply(session, tenant_id: uuid.UUID, job_type: str) -> None:
    """After an edit, land the change on Blinkit NOW (not at the next scheduled fire) by
    enqueuing an engine run. Only when armed — a dry run writes nothing, so there'd be
    nothing to apply immediately."""
    if not await repo.get_armed(tenant_id, PLATFORM):
        return
    from jobs.queue import DuplicateActiveJob
    try:
        await enqueue(session, job_type=job_type, tenant_id=tenant_id, params={"live": "true"})
    except DuplicateActiveJob:
        pass


# ── Status (computed, so the UI shows Running / Scheduled / Ended, not raw state) ──
#
# Two axes projected onto one label. The user's choice (`paused` / `stopped`) wins whenever
# it is not `active`; otherwise the label is the calendar state from `window`.

def _budget_rule_status(r, now) -> str:
    return window.calendar_state(window.from_budget(r), now)


def _budget_status(schedule, rules, now) -> str:
    if schedule.state != "active":
        return schedule.state                    # stopped
    return window.schedule_calendar_state([window.from_budget(r) for r in rules], now)


def _bid_status(r, now) -> str:
    # A paused rule reports `paused` even if its window has since ended — the state the
    # user chose outranks the calendar. The lifecycle gates in pause/resume/reset read
    # `state` and `_bid_ended()` directly and never this, precisely because of that.
    if r.state != "active":
        return r.state                            # paused (the raw value, whatever it is)
    return window.calendar_state(window.from_bid(r), now)


def _schedule_out(schedule, rules, now=None) -> BudgetScheduleOut:
    now = now or now_ist()
    rule_outs = []
    for r in rules:
        ro = BudgetRuleOut.model_validate(r)
        ro.status = _budget_rule_status(r, now)
        rule_outs.append(ro)
    return BudgetScheduleOut(
        id=schedule.id, campaign_id=schedule.campaign_id, campaign_name=schedule.campaign_name,
        name=schedule.name, default_budget=schedule.default_budget, state=schedule.state,
        stop_after_window=schedule.stop_after_window,
        status=_budget_status(schedule, rules, now), platform=schedule.platform, rules=rule_outs,
        ended_at=getattr(schedule, "ended_at", None),
        settled_at=getattr(schedule, "settled_at", None),
    )


def _bid_out(r, now=None, city_name=None) -> BidRuleOut:
    o = BidRuleOut.model_validate(r)
    o.status = _bid_status(r, now or now_ist())
    o.city_name = city_name
    return o


async def _bid_out_async(r, now=None) -> BidRuleOut:
    """`_bid_out` for the single-rule paths, which have no batch to resolve cities with.
    Lists must NOT use this — see `list_bid_rules`, which resolves the whole page at once."""
    names = await repo.city_names_for(PLATFORM, [r])
    return _bid_out(r, now, names.get(r.id))


# ── Budget schedules + rules ────────────────────────────────────────────────

async def list_budget_schedules(tenant_id: uuid.UUID) -> list[BudgetScheduleOut]:
    # The UI lists every automation — stopped and ended included.
    pairs = await repo.get_budget_schedules(tenant_id, PLATFORM, state=repo.ANY_STATE,
                                            calendar=repo.ANY_CALENDAR)
    return [_schedule_out(s, rules) for s, rules in pairs]


async def create_budget_schedule(session, tenant_id: uuid.UUID, body: BudgetScheduleIn) -> BudgetScheduleOut:
    await _require_marketplace(tenant_id, body.campaign_id)
    try:
        s = await repo.create_budget_schedule(
            tenant_id, PLATFORM, body.campaign_id,
            body.campaign_name or f"campaign {body.campaign_id}", body.default_budget, body.name,
            stop_after_window=body.stop_after_window,
        )
    except repo.NotAutomatable as e:
        raise EditError(str(e)) from e
    rules = [await repo.add_budget_rule(s.id, **body.rule.model_dump())] if body.rule else []
    await _reconcile(session, tenant_id)
    return _schedule_out(s, rules)


async def delete_budget_schedule(session, tenant_id: uuid.UUID, schedule_id: int) -> bool:
    s = await repo.get_budget_schedule(schedule_id)
    if not s or s.tenant_id != tenant_id:
        return False
    await repo.delete_budget_schedule(schedule_id)
    await _reconcile(session, tenant_id)
    return True


async def add_budget_rule(session, tenant_id: uuid.UUID, schedule_id: int,
                          body: BudgetRuleIn) -> BudgetRuleOut | None:
    s = await repo.get_budget_schedule(schedule_id)
    if not s or s.tenant_id != tenant_id:
        return None
    r = await repo.add_budget_rule(schedule_id, **body.model_dump())
    await _reconcile(session, tenant_id)
    return BudgetRuleOut.model_validate(r)


async def _fresh_schedule(tenant_id: uuid.UUID, schedule_id: int) -> BudgetScheduleOut | None:
    now = now_ist()
    for s, rules in await repo.get_budget_schedules(tenant_id, PLATFORM, state=repo.ANY_STATE,
                                                    calendar=repo.ANY_CALENDAR):
        if s.id == schedule_id:
            return _schedule_out(s, rules, now)
    return None


async def update_budget_schedule(session, tenant_id: uuid.UUID, schedule_id: int,
                                 body: BudgetScheduleUpdate) -> BudgetScheduleOut | None:
    s = await repo.get_budget_schedule(schedule_id)
    if not s or s.tenant_id != tenant_id:
        return None
    fields = body.model_dump(exclude_unset=True)
    if fields:
        await repo.update_budget_schedule(schedule_id, fields)
    await _reconcile(session, tenant_id)
    await _reapply(session, tenant_id, "cm.budget_scheduler")     # new default/amount applies now
    return await _fresh_schedule(tenant_id, schedule_id)


async def update_budget_rule(session, tenant_id: uuid.UUID, rule_id: int,
                             body: BudgetRuleUpdate) -> BudgetScheduleOut | None:
    r = await repo.get_budget_rule(rule_id)
    if not r:
        return None
    s = await repo.get_budget_schedule(r.schedule_id)
    if not s or s.tenant_id != tenant_id:
        return None
    fields = body.model_dump(exclude_unset=True)
    # The DATE, deliberately — not whether the window has closed. Rescheduling a spent
    # one-time rule to later the SAME day is the most natural correction to make, and a
    # window-closed check would refuse it.
    if window.date_passed(window.Window(type=fields.get("type", r.type),
                                        date=fields.get("date", r.date),
                                        end_date=fields.get("end_date", r.end_date)),
                          now_ist()):
        raise EditError("This automation has already ended — move its dates forward to run it again.")
    if fields:
        await repo.update_budget_rule(rule_id, fields)
    await _reconcile(session, tenant_id)
    await _reapply(session, tenant_id, "cm.budget_scheduler")
    return await _fresh_schedule(tenant_id, s.id)


async def delete_budget_rule(session, tenant_id: uuid.UUID, rule_id: int) -> bool:
    r = await repo.get_budget_rule(rule_id)
    if r:
        s = await repo.get_budget_schedule(r.schedule_id)
        if not s or s.tenant_id != tenant_id:
            return False
    await repo.delete_budget_rule(rule_id)
    await _reconcile(session, tenant_id)
    return True


async def reset_budget_schedule(session, tenant_id: uuid.UUID, schedule_id: int) -> uuid.UUID | None:
    """D19 Budget Reset: stop + set the campaign back to its default budget. Returns the
    reset job's id, or None if the schedule isn't the caller's."""
    s = await repo.get_budget_schedule(schedule_id)
    if not s or s.tenant_id != tenant_id:
        return None
    await repo.set_budget_state(schedule_id, "stopped")
    armed = await repo.get_armed(tenant_id, PLATFORM)      # cutover: write live when armed

    # AD10 — on a stop-after-window schedule, Reset must also bring the campaign BACK.
    # We may have stopped it at the last window end, and "undo the automation" that
    # silently leaves the campaign dark is the opposite of what anyone expects. The
    # restart carries the default budget, so it replaces the set-budget job rather than
    # running alongside it.
    if s.stop_after_window:
        params = {"campaign": str(s.campaign_id), "status": "running",
                  "budget": str(s.default_budget)}
        if armed:
            params["live"] = "true"
        job = await enqueue(session, job_type="cm.set_activation",
                            tenant_id=tenant_id, params=params)
    else:
        params = {"campaign": str(s.campaign_id), "budget": str(s.default_budget)}
        if armed:
            params["live"] = "true"
        job = await enqueue(session, job_type="cm.set_budget", tenant_id=tenant_id, params=params)
    await _reconcile(session, tenant_id)
    return job.id


# ── Bid rules + D19 lifecycle ───────────────────────────────────────────────

async def list_bid_rules(tenant_id: uuid.UUID) -> list[BidRuleOut]:
    now = now_ist()
    # The UI lists every automation — paused and ended included.
    pairs = await repo.get_bid_rules(tenant_id, PLATFORM, state=repo.ANY_STATE,
                                     calendar=repo.ANY_CALENDAR)
    rules = [r for r, _rt in pairs]
    # One resolve for the whole page — a per-row lookup would be a session per rule.
    names = await repo.city_names_for(PLATFORM, rules)
    return [_bid_out(r, now, names.get(r.id)) for r in rules]


def _sorted(cities: list[TargetedCity]) -> list[TargetedCity]:
    """Alphabetical, with the cities we cannot measure in last.

    Blinkit returns `region_ids` in the order someone ticked boxes in its dashboard, and
    that order reached the picker untouched. Sorting here rather than in the form keeps one
    answer for every caller, and sinking the unmeasurable ones stops disabled options
    interleaving with pickable ones.
    """
    return sorted(cities, key=lambda c: (c.lat is None, c.name.lower()))


async def _measurement_cities(tenant_id: uuid.UUID, campaign) -> list[TargetedCity]:
    """Where a bid rule for this campaign may measure position — ONE list, always populated.

    Two branches, one shape, because the form should render a picker rather than choose
    between sources:

    - **CITY targeting** → the campaign's own cities, so a rule cannot be pointed somewhere
      the campaign never runs. A targeted city our catalog has no store in is kept, not
      dropped, carrying `lat=None`: the form disables it and says why, which is the honest
      answer. Dropping it would quietly shrink the campaign's targeting on screen.
    - **Anything else** → every measurable city. PAN_INDIA runs everywhere, so every city we
      have a store in is legitimate. An unscraped campaign (`campaign is None`, or no
      targeting captured) gets the same list for a different reason — we have no evidence it
      is narrow — and `region_type` stays None so the form can word that differently.

    Names come back canonical (`cities.name`) wherever they resolve, which is what stops the
    picker mixing Blinkit's spelling with our catalog's.
    """
    targeted = (campaign.cities or []) if campaign and campaign.region_type == "CITY" else None

    if targeted is None:
        catalog = await repo.measurable_cities(PLATFORM, tenant_id=tenant_id)
        return _sorted([
            TargetedCity(id=key if isinstance(key, int) else None, name=name, state=state,
                         location_name=store.label, lat=store.lat, lon=store.lon)
            for key, (name, state, store) in catalog.items()
        ])

    named = [(c.get("id"), c["name"]) for c in targeted
             if isinstance(c, dict) and c.get("name")]
    resolved = await repo.resolve_city_ids(PLATFORM, [n for _rid, n in named])
    catalog = await repo.measurable_cities(
        PLATFORM, tenant_id=tenant_id, city_ids=set(resolved.values()))

    cities: list[TargetedCity] = []
    for region_id, name in named:
        city_id = resolved.get(name.strip().lower())
        entry = catalog.get(city_id)
        if entry is None:
            # No canonical city, so ask the single-city resolver — it also matches our
            # catalog's own `city` TEXT, which reaches a store in a city that has no
            # `cities` row yet. Normally this loop runs zero times (the canonical registry
            # covers the catalog); it exists so seeding lag cannot make a city we can
            # genuinely measure in look unmeasurable.
            store = await repo.resolve_store(PLATFORM, city=name, tenant_id=tenant_id)
            cities.append(TargetedCity(
                id=city_id or region_id, name=name.title(),
                location_name=store.label if store else None,
                lat=store.lat if store else None,
                lon=store.lon if store else None))
            continue
        canonical, state, store = entry
        cities.append(TargetedCity(id=city_id, name=canonical, state=state,
                                   location_name=store.label, lat=store.lat, lon=store.lon))
    return _sorted(cities)


async def get_bid_context(tenant_id: uuid.UUID, campaign_id: int) -> BidContextOut:
    """Everything the bid-rule form needs about one campaign (V7.4) — DB only, no Blinkit.

    An unscraped campaign returns `scraped_at=None` and no bid prefill rather than a 404 —
    the right answer for a campaign created since the last scrape, where blocking would make
    it unautomatable for a day. It still gets a full city list: not knowing a campaign's
    targeting is a reason to offer every measurable city, not to offer none.
    """
    campaign, keywords = await repo.get_bid_context(tenant_id, campaign_id, PLATFORM)
    cities = await _measurement_cities(tenant_id, campaign)
    if campaign is None:
        return BidContextOut(campaign_id=campaign_id, cities=cities)

    return BidContextOut(
        campaign_id=campaign_id,
        campaign_type=campaign.type,
        scraped_at=campaign.scraped_at,
        region_type=campaign.region_type,
        cities=cities,
        keywords=[KeywordBidRange.model_validate(k, from_attributes=True) for k in keywords],
        daily_budget=campaign.daily_budget,
        pacing_type=campaign.pacing_type,
        billed_amount=campaign.billed_amount,
    )


async def _check_bid_floor(tenant_id: uuid.UUID, campaign_id: int, keyword: str,
                           match_type: str, min_bid: int | None) -> None:
    """Refuse a rule whose `min_bid` sits below the floor Blinkit publishes (V7.5).

    This is the SAVE-time check and it reads the last scrape, so it is a convenience, not
    the authority — the engine re-checks live at write time, where the number cannot be
    stale. It exists to keep an unworkable rule out of the DB and to explain why at the
    moment someone types it, rather than in a job log the next morning.

    Silent when we have no scraped floor: "unknown" must never read as "rejected".
    """
    if min_bid is None:
        return
    floor = await repo.get_keyword_floor(tenant_id, campaign_id, keyword, match_type, PLATFORM)
    if floor is not None and min_bid < floor:
        raise EditError(
            f"Blinkit's minimum bid for “{keyword}” is ₹{floor} — a min bid of ₹{min_bid} "
            f"would be raised to ₹{floor} on the first write. Set ₹{floor} or more."
        )


async def create_bid_rule(session, tenant_id: uuid.UUID, body: BidRuleIn) -> BidRuleOut:
    d = body.model_dump()
    await _require_marketplace(tenant_id, body.campaign_id)
    await _check_bid_floor(tenant_id, body.campaign_id, body.keyword,
                           body.match_type, body.min_bid)
    # Resolve the measurement store from a city / store id when lat/lon weren't given.
    city, location_id = d.pop("city", None), d.pop("location_id", None)
    if (d.get("lat") is None or d.get("lon") is None) and (city or location_id):
        store = await repo.resolve_store(PLATFORM, city=city, location_id=location_id,
                                         tenant_id=tenant_id)
        if store:
            d["lat"], d["lon"] = store.lat, store.lon
            d["location_name"] = d.get("location_name") or store.label
            # Saved BY CITY → follows that city's frozen store from now on (resolved on every
            # run). Saved by an explicit store → pinned to it.
            d["city_id"] = None if location_id else store.city_id
    try:
        r = await repo.create_bid_rule(
            tenant_id, PLATFORM, d.pop("campaign_id"),
            d.pop("campaign_name") or f"campaign {body.campaign_id}",
            d.pop("keyword"), d.pop("target_position"), d.pop("min_bid"), d.pop("max_bid"), **d,
        )
    except repo.NotAutomatable as e:
        raise EditError(str(e)) from e
    await _reconcile(session, tenant_id)
    return await _bid_out_async(r)


async def update_bid_rule(session, tenant_id: uuid.UUID, rule_id: str,
                          body: BidRuleUpdate) -> BidRuleOut | None:
    r = await repo.get_bid_rule(rule_id)
    if not r or r.tenant_id != tenant_id:
        return None
    fields = body.model_dump(exclude_unset=True)
    # Reject editing a spent one-time rule unless the edit moves its date into the future.
    # The DATE on purpose — see the note in update_budget_rule.
    if window.date_passed(window.Window(type=fields.get("type", r.type),
                                        date=fields.get("date", r.date),
                                        end_date=fields.get("stop_date", r.stop_date)),
                          now_ist()):
        raise EditError("This automation has already ended — move its dates forward to run it again.")
    # The floor applies to whatever the rule will BE after the edit, not to what was
    # sent — changing the keyword alone can drop an unchanged min_bid below its new floor.
    await _check_bid_floor(tenant_id, r.campaign_id,
                           fields.get("keyword", r.keyword),
                           fields.get("match_type", r.match_type),
                           fields.get("min_bid", r.min_bid))
    # `city`/`location_id` re-resolve the measurement store (same as create).
    city, location_id = fields.pop("city", None), fields.pop("location_id", None)
    if city or location_id:
        store = await repo.resolve_store(PLATFORM, city=city, location_id=location_id,
                                         tenant_id=tenant_id)
        if store:
            fields["lat"], fields["lon"] = store.lat, store.lon
            fields["location_name"] = store.label
            fields["city_id"] = None if location_id else store.city_id
    if fields:
        try:
            await repo.update_bid_rule(rule_id, fields)
        except repo.NotAutomatable as e:
            raise EditError(str(e)) from e
    await _reconcile(session, tenant_id)
    r = await repo.get_bid_rule(rule_id)
    if window.in_window(window.from_bid(r), now_ist()):   # editing a live window → apply now
        await _reapply(session, tenant_id, "cm.bid_optimizer")
    return await _bid_out_async(r)


async def delete_bid_rule(session, tenant_id: uuid.UUID, rule_id: str, *,
                          reset: bool = False) -> bool:
    """Delete an automation, optionally putting its bid back to the floor first.

    Order matters. The reset is enqueued BEFORE the rule goes, so a refused enqueue leaves
    the rule (and its bid) exactly as they were rather than orphaning a high bid with no
    automation left to bring it down. The job itself carries plain values, so it does not
    care that the rule is gone by the time it runs.
    """
    r = await repo.get_bid_rule(rule_id)
    if not r or r.tenant_id != tenant_id:
        return False
    if reset:
        await _enqueue_bid_reset(session, tenant_id, r)
    await repo.delete_bid_rule(rule_id)
    await _reconcile(session, tenant_id)
    return True


# ── Pause / Resume / Reset ──────────────────────────────────────────────────
#
# A bid rule is `active` or `paused` — there is no third state. Pause was always
# mechanically identical to the old `stopped` (every engine check is `state == "active"`),
# so keeping both meant two words for one behaviour and a Stop button that could not be
# undone. Removed 2026-09-07.

def _bid_ended(r) -> bool:
    """Has this automation's last window already passed? Nothing will fire for it again, so
    pause and resume are meaningless — but Reset is NOT: a rule paused across its window
    end never got its end-of-window de-escalation, and its bid is still sitting high."""
    return window.is_expired(window.from_bid(r), now_ist())


async def pause_bid_rule(session, tenant_id: uuid.UUID, rule_id: str) -> BidRuleOut | None:
    """Freeze the automation: no optimizer ticks, no end-of-window reset, no writes at all.

    The bid is deliberately left where it is — pausing is not a decision about price. Use
    Reset (allowed on a paused rule) to bring it back to the floor.

    Runtime is NOT cleared here. `updated_at` decides whether the window counts as opened,
    and Resume needs it intact; everything stale is cleared then, when we know what we are
    resuming into.
    """
    r = await repo.get_bid_rule(rule_id)
    if not r or r.tenant_id != tenant_id:
        return None
    if r.state == "paused":
        raise StateError("This automation is already paused.")
    if _bid_ended(r):
        raise StateError("This automation has already ended, so there is nothing to pause.")
    r = await repo.set_bid_state(rule_id, "paused")
    await _reconcile(session, tenant_id)
    return await _bid_out_async(r)


async def resume_bid_rule(session, tenant_id: uuid.UUID, rule_id: str) -> BidRuleOut | None:
    """Un-freeze, and make the engine decide from CURRENT facts rather than pre-pause ones.

    Two things happen:

    1. **Every learned value is cleared** (`repo.clear_bid_runtime`) — last bid, last
       position, the drift pause, the escalation step, a relaxed target. A rule paused for
       six hours knows nothing useful about the auction, and each of those is an input to a
       decision. `updated_at` is kept, which is what makes the window behaviour correct
       with no special-casing: resumed inside the same window → carry on from the live bid;
       resumed after a new window has started → the next tick re-opens at the floor.

    2. **A window that ended during the pause is repaired.** Pausing removes the
       end-of-window reset, so if the window has since closed the bid is still at whatever
       the optimizer climbed to. Resume enqueues that reset itself.
    """
    r = await repo.get_bid_rule(rule_id)
    if not r or r.tenant_id != tenant_id:
        return None
    if r.state == "active":
        raise StateError("This automation is already running.")
    if _bid_ended(r):
        raise StateError("This automation has already ended — change its dates to run it again.")
    await repo.clear_bid_runtime(rule_id)
    r = await repo.set_bid_state(rule_id, "active")
    await _reconcile(session, tenant_id)
    if not window.in_window(window.from_bid(r), now_ist()):
        await _enqueue_bid_reset(session, tenant_id, r)
    return await _bid_out_async(r)


async def reset_bid_rule(session, tenant_id: uuid.UUID, rule_id: str) -> uuid.UUID | None:
    """Put this automation's keyword back to its floor now. Returns the job id to poll.

    Refused only while the rule is RUNNING (active and inside its window) — there the next
    tick would undo it within 15 minutes, so refusing says so instead of spending a write
    that gets reverted. Allowed while paused, before a window opens, and after a rule has
    ended: that last case is the one that matters, because a rule paused across its window
    end never got its de-escalation and Resume is not available to repair it.
    """
    r = await repo.get_bid_rule(rule_id)
    if not r or r.tenant_id != tenant_id:
        return None
    if r.state == "active" and window.in_window(window.from_bid(r), now_ist()):
        raise StateError(
            "This automation is running right now — pause it first, or the next check "
            "will bid it straight back up.")
    return await _enqueue_bid_reset(session, tenant_id, r)


async def _enqueue_bid_reset(session, tenant_id: uuid.UUID, rule) -> uuid.UUID:
    """Queue the one write that Reset (and Delete-with-reset) performs.

    `priority=10` against a default of 100: the queue claims by `(priority, scheduled_for)`,
    so a reset a person is waiting on jumps any scheduled work already pending in the lane.
    The lane itself (`cm_ops`) is what keeps it from queueing behind a bid-optimizer tick —
    see the job registry.
    """
    from jobs.queue import DuplicateActiveJob
    # The rule's OWN marketplace, not this service's `PLATFORM` default. The rest of the
    # CM API is Blinkit-only, but `get_bid_rule` looks up by id and does not filter — so a
    # Zepto rule reaching here would otherwise be enqueued as a Blinkit job (the argv
    # builder defaults `marketplace` to blinkit) and armed against Blinkit's `live_armed`.
    # That means a Zepto campaign id, sent to the wrong ad account, with real writes on.
    marketplace = getattr(rule, "platform", None) or PLATFORM
    params = {"marketplace": marketplace,
              "campaign": str(rule.campaign_id), "keyword": rule.keyword,
              "cpm": str(rule.min_bid), "match_type": rule.match_type or "EXACT"}
    if await repo.get_armed(tenant_id, marketplace):
        params["live"] = "true"
    try:
        job = await enqueue(session, job_type="cm.set_bid", tenant_id=tenant_id,
                            params=params, priority=10)
    except DuplicateActiveJob:
        # One bid reset per client at a time (`uq_jobs_active`). It is a single write and
        # takes about a minute, so saying "wait" beats silently dropping the second one.
        raise StateError(
            "Another bid reset is already running for this client — try again in a minute.")
    return job.id


# ── On-demand actions (enqueue → poll) ──────────────────────────────────────

async def set_budget_now(session, tenant_id: uuid.UUID, campaign_id: int, budget: float) -> uuid.UUID:
    await _require_marketplace(tenant_id, campaign_id)
    params = {"campaign": str(campaign_id), "budget": str(budget)}
    if await repo.get_armed(tenant_id, PLATFORM):     # cutover: write live when armed
        params["live"] = "true"
    job = await enqueue(session, job_type="cm.set_budget", tenant_id=tenant_id, params=params)
    return job.id


async def set_activation_now(session, tenant_id: uuid.UUID, campaign_id: int, status: str,
                             budget: float | None = None) -> uuid.UUID:
    """Enqueue a start/stop of one campaign. Like set_budget_now, the API only queues —
    the VM opens the browser, reads the campaign's real state and runs the guardrails.

    `budget` is passed through only for a resume; leaving it out lets the engine reuse the
    campaign's current budget from a fresh read, which is better than anything the API
    could guess from stale scraped data.
    """
    await _require_marketplace(tenant_id, campaign_id)
    params = {"campaign": str(campaign_id), "status": status}
    if status == "running" and budget is not None:
        params["budget"] = str(budget)
    if await repo.get_armed(tenant_id, PLATFORM):     # cutover: write live when armed
        params["live"] = "true"
    job = await enqueue(session, job_type="cm.set_activation", tenant_id=tenant_id, params=params)
    return job.id


async def refresh_campaigns(session, tenant_id: uuid.UUID) -> uuid.UUID:
    """Enqueue a catalogue refresh from the live account. No `live` param — it is a read,
    so it runs the same whether or not the tenant is armed."""
    job = await enqueue(session, job_type="cm.sync_campaigns", tenant_id=tenant_id)
    return job.id


async def run_engine(session, tenant_id: uuid.UUID, job_type: str) -> uuid.UUID:
    """Enqueue a run-now of cm.budget_scheduler / cm.bid_optimizer (dry). Raises
    DuplicateActiveJob if one is already active."""
    job = await enqueue(session, job_type=job_type, tenant_id=tenant_id)
    return job.id


# ── Recent actions (the dashboard's activity list) ──────────────────────────

# How many to show, and how far back to look. Small on purpose: this answers "what did I
# just ask for", not "what has happened lately" — the run log answers that, and is where
# anything older belongs.
_ACTIONS_LIMIT = 10
_ACTIONS_WINDOW_HOURS = 6


async def recent_actions(session, tenant_id: uuid.UUID, limit: int = _ACTIONS_LIMIT):
    """This client's recent PERSON-TRIGGERED campaign jobs, newest first.

    Two conditions, and both are needed:

      * the job TYPE is one a person performs (`spec.user_action`) — which excludes the
        hourly engines and `cm.reconcile`, the latter being fired by the API on every rule
        edit and so the noisiest thing that would otherwise qualify;
      * THIS RUN had no schedule behind it (`schedule_id IS NULL`). The scheduler stamps
        every job it fires with its schedule id and the API never sets one, so this is an
        exact record of "a person asked for this" rather than an inference.

    Neither alone is enough. The type says what KIND of thing it is; `schedule_id` says who
    started THIS one. A cron fire of a type people also click is not an action anyone is
    waiting on, and a reconcile nobody thinks of as an action should not appear just because
    it came from the API.

    Includes finished jobs, not only running ones — a job that wrote no history rows (a
    catalogue refresh always does, and an engine tick that changed nothing does too) would
    otherwise vanish on completion with nothing left to show it ever ran.
    """
    from sqlalchemy import select
    from jobs.types import JOB_TYPES

    actionable = [t for t, spec in JOB_TYPES.items() if spec.user_action]
    if not actionable:
        return []
    since = now_ist() - timedelta(hours=_ACTIONS_WINDOW_HOURS)
    rows = (await session.execute(
        select(Job).where(
            Job.tenant_id == tenant_id,
            Job.job_type.in_(actionable),
            Job.schedule_id.is_(None),
            Job.created_at >= since,
        ).order_by(Job.created_at.desc()).limit(limit)
    )).scalars().all()

    out = []
    for job in rows:
        spec = JOB_TYPES.get(job.job_type)
        item = CmActionOut.model_validate(job)
        item.label = (spec.label if spec else None) or job.job_type
        item.run_id = (job.params or {}).get("run_id")
        # The campaign this acted on, for a line that names its subject rather than
        # saying "a budget change" and leaving the reader to guess which.
        campaign = (job.params or {}).get("campaign")
        item.campaign_id = int(campaign) if str(campaign or "").isdigit() else None
        item.keyword = (job.params or {}).get("keyword") or None
        out.append(item)
    return out


# ── Status + history ────────────────────────────────────────────────────────

async def get_job(session, tenant_id: uuid.UUID, job_id: uuid.UUID) -> CmJobOut | None:
    job = await session.get(Job, job_id)
    if not job or job.tenant_id != tenant_id or not job.job_type.startswith("cm."):
        return None
    out = CmJobOut.model_validate(job)
    # Lifted out of `params` so callers never have to know where it is stored. It is a
    # param because that is how it reaches the CLI (`--run-id`), but to a reader of a job
    # it is identity, not input — and it is the key to what the run actually DID, since
    # `status` only reports that the process exited.
    out.run_id = (job.params or {}).get("run_id")
    return out


async def history(tenant_id: uuid.UUID, *, kind: str | None, limit: int, offset: int,
                  campaign_id: int | None = None, rule_id: str | None = None,
                  run_id: str | None = None, include_unchanged: bool = False,
                  keyword: str | None = None, success: bool | None = None):
    """History for the UI. Changes only by default; `include_unchanged` returns every tick,
    which is what a per-automation view wants (see repo.list_run_log).

    `run_id` is the one-run view — what a single job did, and the only exact answer to
    "did my change happen" (see the note on `repo.list_run_log`)."""
    rows, total = await repo.list_run_log(
        tenant_id, PLATFORM, kind=kind, limit=limit, offset=offset,
        campaign_id=campaign_id, rule_id=rule_id, run_id=run_id,
        include_unchanged=include_unchanged, keyword=keyword, success=success)
    return [RunLogOut.model_validate(r) for r in rows], total


# ── Advertiser account (B3) ─────────────────────────────────────────────────

async def get_advertiser(tenant_id: uuid.UUID) -> int | None:
    return await repo.get_advertiser(tenant_id, PLATFORM)


async def set_advertiser(tenant_id: uuid.UUID, advertiser_id: int) -> None:
    await repo.set_advertiser(tenant_id, advertiser_id, PLATFORM)
