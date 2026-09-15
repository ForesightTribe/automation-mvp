"""The gated write choke-point (docs §12.1) — the ONLY place that mutates Blinkit.

Nothing else in the campaign manager may call an adapter's `apply_*`. Every write
goes through `apply_budget()` / `apply_bid()`, which:
  - are DRY-RUN by default (live must be explicitly requested),
  - run guardrails (bounds / clamp / no-op skip / rate limit),
  - log intent → guardrail → result,
  - and only then delegate the real mutation to the marketplace adapter.

The guardrail checks are PURE functions (unit-tested in tests/test_guardrails.py),
so the safety logic is verifiable without Blinkit.
"""
from campaign_manager import config, logs


class SessionExpired(RuntimeError):
    """The marketplace answered as if we are logged out.

    Lives here, beside `WriteRefused`, because the ENGINES have to act on it and they are
    marketplace-agnostic — an adapter-specific exception class would make `bid.py` import
    from `marketplaces/blinkit/`.

    Deliberately distinct from "the marketplace refused this change". Blinkit's `_fetch`
    used to turn a login redirect into `{}`, which every caller reads as a rejection — so a
    session dying mid-run logged `not applied — Blinkit rejected the change to ₹250` for
    every remaining keyword. A false statement about the marketplace, and it hid the fault.

    A client that CAN re-authenticate does so first and only raises this if that fails, so
    reaching an engine means the run genuinely cannot continue.

    Subclasses RuntimeError because `adapter.setup()` failures are already caught as
    RuntimeError and reported as an expired session — this keeps startup behaviour identical.
    """


class WriteRefused(Exception):
    """A payload builder refused to send a write it could not build safely.

    Raised from deep inside an adapter — where the marketplace's own payload shape is
    known — and caught here, at the choke point, because refusing is a POLICY outcome:
    it is one failed write with a readable reason, not a crashed run.

    That distinction matters. The engines wrap their per-campaign loops in `try/finally`,
    not `try/except`, so any other exception escaping a write aborts the whole run and
    every campaign after it is silently skipped. Only refusals are caught here — a dead
    session or a network failure must still abort, because continuing would mean firing
    the same broken call at fifty more campaigns.

    The case that created it: a Blinkit campaign reporting `region_type=CITY` whose
    `region_ids` cannot be read. Sending the pan-India default would broaden a live
    campaign (docs §8.2b), so the builder refuses instead.
    """


class WriteUnverified(RuntimeError):
    """The write WAS SENT and the marketplace's answer does not say whether it worked.

    Not the same as a refusal. A refusal is the marketplace telling us no; this is the
    marketplace telling us nothing — an empty body, a gateway timeout page, a 200 with no
    success marker. The write may have landed.

    Why it exists (2026-09-07, Blinkit, campaign 637511, keyword "soda"). Two ticks failed
    the same way and meant opposite things:

      12:16  body `{"message": ""}`  → the bid did NOT change (next tick read the old value)
      18:15  body not JSON at all    → the bid DID change (₹421 was live on Blinkit)

    Both raised a bare `RuntimeError`, both aborted the whole run, and neither was
    distinguishable in the logs. The 18:15 one was the expensive kind: the marketplace was
    mutated, we reported failure, and — because the exception escaped past the engine's
    `finally` — the run never wrote its runtime state, so the 90-minute drift pause that
    recovery had just earned was silently lost.

    So this is raised instead, and `apply_bid` answers the question by READING THE BID BACK
    rather than guessing. Guessing "failed" is not the safe default when a write may have
    landed: it makes the engine's memory disagree with the marketplace.
    """


# ── Pure guardrail logic (unit-tested, no I/O) ──────────────────────────────

def _why(resp: dict | None) -> str:
    """The marketplace's own reason a write was refused.

    It was always in the response and never logged: a failed budget write recorded
    `applied=False` and "₹201 → ₹250", with the reason dropped on the floor. That is
    half of why a delisted-catalog retry could sit in `apply_budget` for months looking
    like it did something — nobody ever saw either message.

    Blinkit puts it in `message`, as a string or a list of them; Zepto uses `error` or
    `detail`. Falls back to naming the shape of the response, because "no reason given"
    is itself worth knowing — it means the refusal came back empty, not that we lost it.
    """
    if not isinstance(resp, dict):
        return f"no reason given ({type(resp).__name__})"
    for key in ("message", "error", "detail", "errors"):
        val = resp.get(key)
        if isinstance(val, (list, tuple)):
            val = "; ".join(str(v) for v in val if v)
        if val:
            return str(val)[:200]
    return f"no reason given (keys: {', '.join(sorted(resp)) or 'none'})"


def money(v) -> str:
    """Render a budget the way it will actually be SENT.

    `--budget` is a float, so a target of 700 logs as "700.0" unless formatted —
    noise in the one line a human reads to approve a money change. Adapters round
    to int before sending, so show the int.
    """
    if v is None:
        return "unknown"
    try:
        return f"₹{int(round(float(v)))}"
    except (TypeError, ValueError):
        return f"₹{v}"


def budget_out_of_bounds(target, *, min_budget: float | None = None,
                         max_budget: float | None = None) -> str | None:
    """Return a reason string if `target` is outside sane bounds, else None."""
    lo = config.MIN_BUDGET if min_budget is None else min_budget
    hi = config.MAX_BUDGET if max_budget is None else max_budget
    if target is None:
        return "budget is None"
    if target < lo:
        return f"budget {target} below min {lo}"
    if target > hi:
        return f"budget {target} above max {hi}"
    return None


def clamp_bid(cpm, min_bid, max_bid) -> int:
    """Clamp a CPM into [min_bid, max_bid] (defense in depth)."""
    return max(int(min_bid), min(int(cpm), int(max_bid)))


def bid_out_of_bounds(cpm, *, min_bid: float | None = None,
                      max_bid: float | None = None) -> str | None:
    """Reason string if `cpm` is outside the MARKETPLACE's own bid bounds, else None.

    The rule's own `[min_bid, max_bid]` is already applied by `clamp_bid`. This is the
    separate question of whether the platform will accept the result at all — the same
    declare/enforce split `apply_budget` uses for `MIN_BUDGET`: the adapter states the
    marketplace's law, this policy enforces it, and a violation is refused with a
    readable reason instead of arriving later as an opaque 400.

    REFUSES rather than clamping up. Silently raising a bid above what the operator
    configured is not a guardrail's decision to make — and a rule whose ceiling sits
    below the platform floor is a configuration error that should be visible.
    """
    if cpm is None:
        return "bid is None"
    if min_bid is not None and cpm < min_bid:
        return f"bid {cpm} below the marketplace minimum {min_bid:g}"
    if max_bid is not None and cpm > max_bid:
        return f"bid {cpm} above the marketplace maximum {max_bid:g}"
    return None


def is_noop(new, current) -> bool:
    """True when the computed value equals the current one → skip the write."""
    if new is None or current is None:
        return False
    return int(round(float(new))) == int(round(float(current)))


def exceeds_rate_limit(recent_writes: int, *, limit: int | None = None) -> bool:
    """True when this campaign already has `limit`+ writes in the window."""
    cap = config.MAX_WRITES_PER_WINDOW if limit is None else limit
    return recent_writes >= cap


# ── Status transitions (docs/campaign-manager.md §8.1) ───────────────────
#
# Unlike budget (a scalar with bounds), a campaign's run state is an ENUM, so the
# guardrail is a transition table. Two states are terminal-ish and must never be
# written through: `ended` (COMPLETED — Blinkit is done with it) and `held`
# (ON_HOLD — Blinkit imposed it, so clearing it is not ours to do).

WRITABLE_STATES = ("running", "paused")


def status_transition_denied(current: str | None, target: str, *,
                             allow_draft: bool = False) -> str | None:
    """Return a reason string if `current → target` must not be written, else None.

    `allow_draft` is True only for an on-demand action (AD8): a human clicking Start on
    a draft means it; a scheduled rule reaching one does not — drafts are often
    incomplete. A no-op (current == target) is NOT rejected here; the caller checks that
    separately so it can log it as a skip rather than a guardrail trip.
    """
    if target not in WRITABLE_STATES:
        return f"refusing to write status {target!r} (only {'/'.join(WRITABLE_STATES)})"
    if current is None:
        return "current status unknown"
    if current in WRITABLE_STATES:
        return None
    if current == "draft":
        if target == "running" and allow_draft:
            return None
        return f"campaign is a draft — {'not startable by a rule' if target == 'running' else 'nothing to pause'}"
    if current == "held":
        # ON_HOLD = Blinkit paused delivery because the campaign's budget ran out. It is
        # still a LIVE campaign, not a stopped one — so it can be stopped, and raising its
        # budget is what revives it. What it CANNOT be is "restarted": there is nothing to
        # restart, which is why Blinkit offers `['UPDATE']` and never `['RESTART']` for it.
        if target == "paused":
            return None
        return ("campaign is ON_HOLD (its budget is exhausted) — raise the budget to revive "
                "it; there is nothing to restart")
    if current == "ended":
        return "campaign is COMPLETED — terminal, cannot be restarted"
    # An unmapped marketplace string. Refuse rather than guess: a new Blinkit status
    # we've never seen is exactly when a blind write is most likely to be wrong.
    return f"unrecognised campaign status {current!r}"


# ── Catalogue write-back (docs/campaign-manager.md §4) ──────────────────────

def _record(applied, adapter, what: str, **kw) -> None:
    """Note that a write landed, so the caller can mirror it into our catalogue.

    COLLECTS, it does not write. Every `apply_*` takes an optional `applied` list and
    appends to it; the engine flushes the whole list once, beside `write_run_log`. Two
    reasons it works that way rather than writing here:

      * **Cost.** A bid run applies a write per keyword per tick. A DB session per write
        would be a connection acquisition per keyword — on a pool that has been exhausted
        in production before. Batched, a whole run costs one session, which is what the
        engines already spend on `write_bid_runtime` and `write_run_log`.
      * **Blast radius.** The choke point's job is to decide and to narrate; a DB failure
        in here would sit in the middle of the one function that must never turn a landed
        marketplace write into an exception.

    A marketplace with no `catalog_patch` is a silent no-op — see the note on Blinkit's
    `catalog_patch` for why that is the mechanism rather than a platform check.
    """
    if applied is None:
        return
    patch = getattr(adapter, "catalog_patch", None)
    if patch is None:
        return
    try:
        applied.extend(patch(what, **kw) or [])
    except Exception:                      # bookkeeping never breaks the write it describes
        pass


def _refused(outcome, reason: str | None) -> None:
    """Record WHY a write did not land, for the caller's history row.

    The reason always existed — every branch below computes one and hands it to
    `logs.write_guardrail` / `logs.write_result`. But these functions return a bare
    `bool`, so the reason reached Cloud Logging and stopped there, and every caller then
    wrote a history row saying something it already knew: `set_budget` recorded the
    literal string "set-budget", the engines recorded the RULE that prompted the write.
    A person reading History therefore saw that a change did not happen, and never why.

    2026-09-15 is what made it concrete: Blinkit began rejecting every UPDATE with
    "Start Date of Campaign is not allowed to be changed" (a date-formatting bug, fixed
    in `build.fmt_date`), and the refused rows in `cm_run_log` read `set-budget` —
    the one sentence that would have identified it, dropped.

    An out-param rather than a changed return type, deliberately: `apply_*` is called from
    nine places that read the bool directly, and a tuple would have to be unpacked at every
    one of them. Same shape as the `applied` accumulator beside it, and callers that do not
    care simply pass nothing.
    """
    if outcome is not None and reason:
        outcome["reason"] = reason


# ── Live-write arming (B3 account guardrail) ────────────────────────────────

async def arm_live(adapter, client, run_id: str,
                   advertiser: int | str | None) -> int | str:
    """Gate a LIVE run on the account guardrail. Never called in dry-run.

    The tenant's stored ad account must exist, and the adapter decides what to do
    with it — the two marketplaces mean different things by "account":

    * **Blinkit** SENDS it. The advertiser id is in no read API, so a stored value
      is the only source, and a stale one spends real money on the wrong account.
    * **Zepto** CHECKS it. The brand id comes from the login response, so the
      adapter asserts the live session matches and refuses if it does not.

    Either way, refusing to run beats writing to an account we cannot identify.
    """
    if advertiser is None:
        raise RuntimeError(
            "no ad account stored for this tenant — run "
            "`cm set-advertiser -t <id> -m <marketplace> --id <value>` first "
            "(Blinkit: the integer advertiser id from a dashboard PUT; "
            "Zepto: the brand UUID from `cm advertiser`). Refusing live write.")
    adapter.set_advertiser(client, advertiser)
    logs.live_armed(run_id, advertiser=advertiser)
    return advertiser


# ── The choke-point (only entry to a Blinkit budget/bid mutation) ───────────

async def apply_budget(adapter, client, *, run_id: str, campaign_id, target, current,
                       dry_run: bool, recent_writes: int = 0,
                       applied: list | None = None,
                       outcome: dict | None = None) -> bool:
    """Guardrailed budget write. Returns True if applied (or would-apply in dry-run),
    False if skipped/rejected. `adapter`/`client` are unused in dry-run.

    `applied` is the run's catalogue write-back accumulator — see `_record`.
    `outcome` collects WHY a write did not land — see `_refused`."""
    logs.write_intent(run_id, dry_run=dry_run, campaign_id=campaign_id,
                      what="budget", old=current, new=target)

    if is_noop(target, current):
        # DEBUG, not WARNING: "the budget is already what it should be" is the hourly
        # poll's normal answer, and the engine has already said so in its own words.
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id, passed=False,
                             reason=f"the budget is already {money(current)}", level="debug")
        _refused(outcome, f"the budget is already {money(current)}")
        return False
    # A marketplace may impose its own floor/ceiling, which is stricter than our
    # config bounds and not ours to argue with — Zepto publishes a ₹500 daily-budget
    # minimum in its own metadata. The ADAPTER declares it (mechanism); this policy
    # enforces it, so an out-of-range target is skipped with a readable reason
    # instead of failing later as an opaque 400 from the marketplace.
    reason = budget_out_of_bounds(
        target,
        min_budget=getattr(adapter, "MIN_BUDGET", None),
        max_budget=getattr(adapter, "MAX_BUDGET", None),
    )
    if reason:
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                             passed=False, reason=reason)
        _refused(outcome, reason)
        return False
    if exceeds_rate_limit(recent_writes):
        limited = f"rate limit ({recent_writes} recent writes)"
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                             passed=False, reason=limited)
        _refused(outcome, limited)
        return False

    logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id, passed=True)

    if dry_run:
        # Report the SAME values the live branch does. Without them a dry run printed
        # "would apply  — not sent" with no numbers, which is backwards: the dry run
        # is precisely when a human needs to see what would change, and `write.intent`
        # (which carries old→new) is DEBUG.
        logs.write_result(run_id, dry_run=True, campaign_id=campaign_id, applied=True,
                          subject="the budget", old=money(current), new=money(target))
        return True

    # LIVE — the single real budget mutation.
    try:
        resp = await adapter.apply_budget(client, campaign_id, target)
    except WriteRefused as e:
        logs.write_guardrail(run_id, dry_run=False, campaign_id=campaign_id,
                             passed=False, reason=str(e))
        logs.write_result(run_id, dry_run=False, campaign_id=campaign_id, applied=False,
                          subject="the budget", old=money(current), new=money(target),
                          reason=str(e))
        _refused(outcome, str(e))
        return False
    ok = bool(resp.get("status") or resp.get("success"))
    logs.write_result(run_id, dry_run=False, campaign_id=campaign_id, applied=ok,
                      subject="the budget", old=money(current), new=money(target),
                      reason=None if ok else _why(resp))
    if not ok:
        _refused(outcome, _why(resp))
    if ok:
        _record(applied, adapter, "budget", campaign_id=campaign_id, value=target)
    return ok


async def apply_bid(adapter, client, *, run_id: str, campaign_id, keyword, new_cpm,
                    current_cpm, min_bid, max_bid, match_type="EXACT",
                    dry_run: bool, recent_writes: int = 0,
                    applied: list | None = None,
                    outcome: dict | None = None) -> bool:
    """Guardrailed keyword-bid write. Clamps to [min_bid, max_bid] first.

    `outcome` collects WHY a write did not land — see `_refused`."""
    clamped = clamp_bid(new_cpm, min_bid, max_bid)
    logs.write_intent(run_id, dry_run=dry_run, campaign_id=campaign_id, keyword=keyword,
                      what="bid", old=current_cpm, new=clamped)

    if is_noop(clamped, current_cpm):
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id, passed=False,
                             reason=f"the bid is already ₹{clamped}", keyword=keyword,
                             level="debug")
        _refused(outcome, f"the bid is already ₹{clamped}")
        return False
    # The marketplace's OWN bid bounds, if it publishes any — the same declare/enforce
    # split `apply_budget` uses for MIN_BUDGET. Sits after the clamp because the clamp
    # applies the RULE's range: a rule whose floor is below the platform's still needs
    # catching, and the platform gets the final say.
    reason = bid_out_of_bounds(clamped,
                               min_bid=getattr(adapter, "MIN_BID", None),
                               max_bid=getattr(adapter, "MAX_BID", None))
    if reason:
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                             passed=False, reason=reason, keyword=keyword)
        _refused(outcome, reason)
        return False
    if exceeds_rate_limit(recent_writes):
        limited = f"rate limit ({recent_writes} recent writes)"
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                             passed=False, reason=limited, keyword=keyword)
        _refused(outcome, limited)
        return False

    logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id, passed=True, keyword=keyword)

    # No write.result line here: the bid engine narrates the outcome itself, inside the
    # rule block, in a sentence. Emitting both would report every bid change twice.
    if dry_run:
        return True

    # LIVE — the single real Blinkit bid mutation.
    why = None
    try:
        resp = await adapter.apply_bid(client, campaign_id, keyword, clamped, match_type)
        ok = bool(resp.get("status") or resp.get("success"))
        if not ok:
            why = _why(resp)
    except WriteRefused as e:
        logs.write_guardrail(run_id, dry_run=False, campaign_id=campaign_id,
                             passed=False, reason=str(e), keyword=keyword)
        _refused(outcome, str(e))
        return False
    except WriteUnverified as e:
        # The write went out and we did not get a usable answer. Ask the marketplace what
        # the bid IS now, rather than assuming the worst — see WriteUnverified.
        ok = await verify_bid(adapter, client, run_id=run_id, campaign_id=campaign_id,
                              keyword=keyword, intended=clamped, why=str(e))
        # `resp` never existed on this path. The reason is the unverified reply itself,
        # which `verify_bid` has already narrated in full; this is its one-line form.
        why = None if ok else f"{e}; and the bid did not change"

    # One record point, so the verified-after-the-fact path is mirrored too: `verify_bid`
    # returning True means the marketplace itself reports `clamped` as the live bid, which
    # is a landed write however badly it was acknowledged.
    if ok:
        _record(applied, adapter, "bid", campaign_id=campaign_id, value=clamped,
                keyword=keyword, match_type=match_type)
    else:
        _refused(outcome, why)
    return ok


async def verify_bid(adapter, client, *, run_id: str, campaign_id, keyword: str,
                     intended: int, why: str) -> bool:
    """Did an unacknowledged bid write actually land? Read the bid back and see.

    Returns True only when the marketplace now reports the value we sent. Anything else —
    a different value, an unreadable keyword, a failed read — is False, because "we could
    not confirm it" must never be logged as an applied write.

    Compares against `adapter.read_bids`, which is the SAME source the engine reads
    `current_cpm` from, so a confirmation here means the next tick will agree with us.
    """
    read = getattr(adapter, "read_bids", None)
    if read is None:                              # a marketplace with no read-back path
        logs.write_guardrail(run_id, dry_run=False, campaign_id=campaign_id, passed=False,
                             reason=f"{why}; this marketplace cannot be read back",
                             keyword=keyword)
        return False
    try:
        live = await read(client, campaign_id)
    except Exception as e:                        # the read is best-effort by definition
        logs.write_guardrail(run_id, dry_run=False, campaign_id=campaign_id, passed=False,
                             reason=f"{why}; reading the bid back failed too ({e})",
                             keyword=keyword)
        return False

    current = live.get(keyword)
    if current is not None and int(current) == int(intended):
        logs.note(run_id, f'"{keyword}" — {why}, but the bid IS now ₹{intended} on the '
                          f"marketplace, so the change did land", level="warning")
        return True
    shown = f"₹{int(current)}" if current is not None else "unreadable"
    logs.write_guardrail(run_id, dry_run=False, campaign_id=campaign_id, passed=False,
                         reason=f"{why}; the bid is still {shown}, so it did not land",
                         keyword=keyword)
    return False


# A campaign's run state, in the words a person uses for it. `held` and `ended` are
# Blinkit's own conditions, so they are named rather than translated away.
STATE_WORDS = {"running": "running", "paused": "stopped", "held": "on hold (out of budget)",
                "ended": "finished", "draft": "a draft"}


def _status_words(target: str, budget: float | None) -> str:
    """What a status write leaves behind, for the log line.

    `budget` is None on a marketplace whose resume carries none, so it is only
    mentioned when there is one — and never formatted with `:g`, which raises on
    None and would turn a successful write into a crash while reporting itself.
    """
    word = STATE_WORDS.get(target, target)
    if target == "running" and budget is not None:
        return f"{word} at {money(budget)}"
    return word


async def apply_status(adapter, client, *, run_id, campaign_id, target, current,
                       dry_run: bool, recent_writes: int = 0, allow_draft: bool = False,
                       budget: float | None = None, overwrites: dict | None = None,
                       applied: list | None = None,
                       outcome: dict | None = None) -> bool:
    """Guardrailed campaign start/stop. Returns True if applied (or would-apply in dry-run).

    The two directions are NOT symmetric, and HOW asymmetric depends on the
    marketplace — which is why the adapter declares it via `RESUME_RESUBMITS`
    rather than this function assuming:

      - `paused` is cheap and safe everywhere (Blinkit: a bodiless DELETE;
        Zepto: a dedicated pause endpoint).
      - `running` on **Blinkit** is a RESTART: a FULL campaign re-submission that
        rewrites budget, keywords, bids and dates. It therefore REQUIRES a budget
        and inherits the budget bounds guardrail; `overwrites` (AD10) is the diff
        of everything it will replace, logged so a silently-reverted bid is visible
        rather than discovered weeks later.
      - `running` on **Zepto** is an idempotent flip that restores the campaign's
        own budget and bids. Nothing is re-submitted, so demanding a budget would
        refuse every legitimate resume as "budget is None".
    """
    logs.write_intent(run_id, dry_run=dry_run, campaign_id=campaign_id,
                      what="status", old=current, new=target)

    if current == target:
        already = f"the campaign is already {STATE_WORDS.get(target, target)}"
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id, passed=False,
                             reason=already, level="debug")
        _refused(outcome, already)
        return False
    reason = status_transition_denied(current, target, allow_draft=allow_draft)
    if reason:
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                             passed=False, reason=reason)
        _refused(outcome, reason)
        return False

    # A RESTART writes a budget, so it passes the same bounds check a budget write
    # does rather than sneaking a value past it (AD14 of the original draft; §5.3).
    # Defaults to True so Blinkit — and any adapter that has not thought about it —
    # keeps the stricter behaviour.
    if target == "running" and getattr(adapter, "RESUME_RESUBMITS", True):
        bad = budget_out_of_bounds(budget)
        if bad:
            logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                                 passed=False, reason=f"restart budget rejected — {bad}")
            _refused(outcome, f"restart budget rejected — {bad}")
            return False

    if exceeds_rate_limit(recent_writes):
        limited = f"rate limit ({recent_writes} recent writes)"
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                             passed=False, reason=limited)
        _refused(outcome, limited)
        return False

    logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id, passed=True)
    if target == "running" and overwrites:
        logs.status_overwrites(run_id, dry_run=dry_run, campaign_id=campaign_id,
                               fields=overwrites)

    was = STATE_WORDS.get(current, current)
    if dry_run:
        # Same values the live branch reports. A dry run that says only "would
        # apply" tells a reviewer nothing about WHAT it would apply.
        logs.write_result(run_id, dry_run=True, campaign_id=campaign_id, applied=True,
                          subject="the campaign", old=was,
                          new=_status_words(target, budget))
        return True

    # LIVE — the single real status mutation.
    try:
        resp = await adapter.apply_status(client, campaign_id, target, budget=budget)
    except WriteRefused as e:
        logs.write_guardrail(run_id, dry_run=False, campaign_id=campaign_id,
                             passed=False, reason=str(e))
        logs.write_result(run_id, dry_run=False, campaign_id=campaign_id, applied=False,
                          subject="the campaign", old=was,
                          new=_status_words(target, budget), reason=str(e))
        _refused(outcome, str(e))
        return False
    ok = bool(resp.get("status") or resp.get("success"))
    logs.write_result(run_id, dry_run=False, campaign_id=campaign_id, applied=ok,
                      subject="the campaign", old=was,
                      new=_status_words(target, budget),
                      reason=None if ok else _why(resp))
    if ok:
        # `budget` goes along for the ride: on a marketplace whose resume RE-SUBMITS the
        # campaign, a restart sets the budget as surely as it sets the status, and the
        # adapter decides whether that is true of it.
        _record(applied, adapter, "status", campaign_id=campaign_id, value=target,
                budget=budget)
    else:
        _refused(outcome, _why(resp))
    return ok
