"""Zepto adapter — the marketplace-specific *mechanism* (see marketplaces/base.py).

`writes.py` owns the policy (dry-run default, bounds, no-op suppression, rate
limiting, audit). This module owns how Zepto is actually driven, and one invariant
that is Zepto's alone:

## Every write is read-modify-write, and must change exactly one field

Budget and bid are both a **whole-campaign PUT** — geo targeting, the product list
and every other keyword's bid ride in the same body. A wrong payload does not fail
loudly; it rewrites live configuration.

So `apply_budget` and `apply_bid` never construct a payload. They:

    1. read the campaign fresh,
    2. translate it into the PUT shape (translate.to_put),
    3. mutate ONE field,
    4. diff against the untouched translation and REFUSE unless exactly that field
       changed,
    5. only then PUT.

Step 4 is the load-bearing one. It catches both a translator bug and a campaign
that changed under us between read and write — someone editing in the dashboard
while a job runs is routine here, not exotic.

⚠️ This is mechanism, not policy, which is why it lives here and not in
`writes.py`: it defends against a hazard only Zepto has. Blinkit's targeted writes
cannot damage a campaign this way, and forcing every marketplace through a
whole-object diff would be wrong.

## Status vocabulary

Zepto's own strings map onto the engine's canonical set. `DAILY_BUDGET_EXHAUSTED`
is Zepto's `ON_HOLD`: live but out of budget — stoppable, not startable, and never
ours to clear. An unmapped value passes through unchanged so a guardrail can refuse
it by name rather than silently coercing it into something writable.
"""
import json

from app.utils.logger import logger
from campaign_manager.marketplaces.zepto import client as zc
from campaign_manager.marketplaces.zepto import endpoints as ep
from campaign_manager.marketplaces.zepto import translate
from campaign_manager.marketplaces.zepto.transport import setup  # noqa: F401  (contract)

# Platform-imposed bounds, published by Zepto at campaigns/metadata
# (budget_types[0].minimum_value). `writes.py` reads these off the adapter, so a
# sub-minimum target is refused with a readable reason instead of arriving as an
# opaque 400. Ours to mirror, not to argue with.
MIN_BUDGET = ep.MIN_DAILY_BUDGET
# Zepto enforces a keyword bid floor server-side but does not publish it — learned
# from a live 400 (see endpoints.py). Declared so `writes.apply_bid` refuses locally
# with a readable reason instead of sending a doomed WHOLE-CAMPAIGN PUT.
MIN_BID = ep.MIN_BID

# Resuming is a dedicated endpoint that flips the campaign back on with its own
# budget and bids intact — nothing is re-submitted, so no budget is required and
# nothing is silently overwritten. Blinkit declares True, where resume IS a full
# campaign re-submission. `writes.py` reads this to decide whether a resume must
# carry a budget; without it a Zepto resume is refused as "budget is None".
RESUME_RESUBMITS = False

# Absence means "bid up", not "do nothing".
#
# If our ad is not in the results, that is the worst outcome a sponsored campaign can
# have — and on Zepto it is a FACT, not a guess: `tagsV2` marks sponsored rows
# positively and `uclId` names the campaign that won each one, so "not ours" is
# something we established rather than failed to detect.
#
# Blinkit does not opt in, for two reasons — neither of which is the DOM fallback an
# earlier version of this comment cited (that was deleted long ago; Blinkit reads
# `ads_campaign_id` from the API now, a positive marker like ours):
#
#   1. Blinkit is LIVE-ARMED and spending today. Zepto is not: every run is by hand.
#      Changing how a running optimizer reacts to absence is a deployment decision.
#   2. Its "absent" is LESS CERTAIN than ours. Blinkit's search rows do not say which
#      campaign paid for them, so we recognise our own ad by product id, falling back
#      to name tokens and then brand. A name-match miss produces a FALSE absent — and
#      under this flag a false absent becomes an escalating bid increase for a product
#      already sitting on the page. Zepto's `uclId` names the campaign outright, so
#      "none of these is ours" is read, not inferred.
#
# Worth revisiting: measure how often Blinkit reaches "absent" via a pid match versus
# the name fallback. If pids match reliably, reason 2 evaporates.
#
# Evidence this is the right call for Zepto (2026-09-02): a `pink toffee` search
# returned 11 sponsored slots including two SUITCASE brands, so relevance filtering is
# loose enough that almost anything can win a slot; and the campaign's own product was
# confirmed stocked and serviceable at the same store. Absent at ₹10 therefore means
# outbid, which is precisely what a bid can fix.
RAISE_WHEN_ABSENT = True

# Where position is measured when a rule carries no store of its own. Same Bengaluru
# fallback the bid engine uses, kept here so the adapter is self-contained.
_DEFAULT_LAT, _DEFAULT_LON = 12.9767, 77.5713

_STATUS_FROM_ZEPTO = {
    ep.STATUS_ACTIVE: "running",
    ep.STATUS_PAUSED: "paused",
    # Live but out of budget — Zepto-imposed, exactly like Blinkit's ON_HOLD.
    ep.STATUS_BUDGET_EXHAUSTED: "held",
}


def _canonical(status: str | None) -> str | None:
    """Zepto's status -> ours. Unmapped values return as-is, on purpose."""
    if not status:
        return None
    key = status.strip().upper()
    if key not in _STATUS_FROM_ZEPTO:
        logger.warning(
            f"Zepto returned an unmapped campaign status {status!r} — treating it as "
            "unknown. If it is legitimate, add it to _STATUS_FROM_ZEPTO."
        )
    return _STATUS_FROM_ZEPTO.get(key, status)


# ── reads (safe) ─────────────────────────────────────────────────────────────
async def list_campaigns(client, days: int = 90) -> list[dict]:
    """Every campaign on the account, ONE call. Raw rows, not canonicalised."""
    return await zc.get_campaigns(client, days=days)


async def read_campaign(client, campaign_id: int) -> tuple[str | None, int | None, dict]:
    """(canonical status, daily budget, full detail) in ONE call.

    Writes read per-campaign like this rather than off `list_campaigns`, because a
    write needs the full detail anyway and it must be fresh at write time — not
    taken from a list fetched minutes earlier.
    """
    detail = await zc.get_campaign_detail(client, campaign_id)
    budget = detail.get("daily_budget")
    return (_canonical(detail.get("status")),
            int(budget) if budget is not None else None,
            detail)


async def read_status(client, campaign_id: int) -> str | None:
    status, _, _ = await read_campaign(client, campaign_id)
    return status


async def read_budget(client, campaign_id: int) -> int | None:
    _, budget, _ = await read_campaign(client, campaign_id)
    return budget


async def read_bids(client, campaign_id: int) -> dict[str, int]:
    """Keyword bids, keyed by TEXT — the shape `base.py` specifies.

    ⚠️ LOSSY on Zepto by design of the contract: a keyword bid under both EXACT and
    BROAD collapses to one entry here. `read_bids_by_match` keeps the pair and is
    what the write path uses; this exists for callers that only need a rough view.
    """
    by_pair = await read_bids_by_match(client, campaign_id)
    flat: dict[str, int] = {}
    for (text, match), value in by_pair.items():
        if text in flat and flat[text] != value:
            logger.warning(
                f"Zepto campaign {campaign_id}: keyword {text!r} is bid under several "
                f"match types at different values; read_bids() reports one. Use "
                "read_bids_by_match() where the distinction matters."
            )
        flat[text] = value
    return flat


async def read_bids_by_match(client, campaign_id: int) -> dict[tuple[str, str], int]:
    """Keyword bids keyed by (text, match_type) — the real grain on Zepto."""
    detail = await zc.get_campaign_detail(client, campaign_id)
    return translate.bids_from_detail(detail)


def bids_from_detail(detail: dict) -> dict[str, int]:
    """Bids off an already-fetched detail, saving a call. Same lossiness as
    `read_bids`."""
    return {text: value
            for (text, _match), value in translate.bids_from_detail(detail).items()}


async def read_bid_floors(client, campaign_id: int, detail: dict | None = None
                          ) -> dict[tuple[str, str], int]:
    """Zepto's published minimum bid per (keyword, match_type). NOT YET WIRED.

    Returns `{}`, which `effective_floor` reads as "no floor known" and falls back to
    the rule's own `min_bid` — today's behaviour, unchanged. The method exists because
    the engine calls it unconditionally; without it every Zepto tick raised
    AttributeError inside the campaign-read `try` and reported "could not read the
    campaign", skipping the rule entirely.

    The endpoint IS known and verified live (2026-09-02) — the direct analogue of
    Blinkit's `get_keyword_attributes`:

        POST /ads-bff/api/v1/keyword/config   (`ep.KEYWORD_CONFIG`)
        -> {"keywords": [{"keyword": "bread", "match_type": "EXACT"}]}
        <- {"keywords": [{"keyword": "bread", "match_type": "EXACT", "min_bid": 9}]}

    Wiring it is deliberately deferred (Deepansh, 2026-09-02) rather than done inside
    a merge. Three things to honour when it is:

    * **Floors vary per keyword** — bread 9, ricotta 3 in one sample. `MIN_BID = 10`
      is currently enforced flat, so it is conservative and over-restrictive; it
      should become the fallback for keywords the lookup does not cover.
    * **EXACT only.** PHRASE and BROAD returned nothing for any keyword tested.
    * **Absence is not permission.** `pink toffee` is missing from the response for
      every match type, yet a live write was refused against a floor of 10.

    Key the returned dict in OUR vocabulary (see `blinkit.adapter._our_match`) — the
    engine looks up `(keyword, rule.match_type)` and must not translate.
    """
    return {}


async def read_products(client, campaign_id: int) -> list[dict]:
    """The products a campaign advertises, as `{pid, name}` — the shape every adapter
    returns, so the bid engine never has to know a marketplace's field names.

    Zepto calls it `product_variant_id`, and that id is what consumer search reports
    as `variant_id`, so the join is exact — no name matching needed. `name` is often
    absent here; it is carried when present only for readable logs.
    """
    detail = await zc.get_campaign_detail(client, campaign_id)
    return [{"pid": str(a["product_variant_id"]), "name": a.get("name") or ""}
            for a in (detail.get("ad_assets_pla") or [])
            if a.get("product_variant_id")]


# ── position sourcing (bid optimisation only) ───────────────────────────────
#
# ⚠️ `pw` is None on Zepto. The engines unpack `(playwright, browser, client)` from
# `setup()` and hand the first element straight to `open_position_session` — but
# Zepto's setup returns `(None, None, client)` because its API needs no persistent
# browser. So the position session launches its OWN Playwright and owns it.
#
# The consumer scrape is the PUBLIC scraper, shared with the keyword scrape rather
# than reimplemented, so a Zepto payload change gets fixed once. It manages its own
# AWS WAF pass in-session (`_ensure_pass`, ~4-6 min, re-minted by re-navigating the
# same page) — do NOT wrap a second pass lifecycle around it.

async def open_position_session(pw, lat: float | None = None,
                                lon: float | None = None) -> dict:
    """Open one consumer-side session for a whole run.

    `pw` is accepted for signature compatibility and IGNORED — see the note above.
    The returned dict carries its own playwright handle so `close_position_session`
    can shut both down.

    Raises RuntimeError when no session could be established: the bid loop must be
    able to tell "our ad isn't there" from "we could not look".
    """
    from playwright.async_api import async_playwright
    from scraper.platforms.zepto.public_data import scraper as zs

    lat = _DEFAULT_LAT if lat is None else float(lat)
    lon = _DEFAULT_LON if lon is None else float(lon)
    driver = await async_playwright().start()
    try:
        session = await zs.open_session(driver, lat, lon)
    except Exception:
        await driver.stop()
        raise
    if not session:
        await driver.stop()
        raise RuntimeError(
            f"Zepto: could not open a consumer search session at ({lat}, {lon})")
    session["_pw"] = driver
    return session


async def close_position_session(session: dict) -> None:
    """Release the session AND the playwright driver it owns. Never raises — a
    teardown failure must not fail a run that already did its work."""
    from scraper.platforms.zepto.public_data import scraper as zs

    if not session:
        return
    try:
        await zs.close_session(session)
    except Exception as e:
        logger.debug(f"Zepto: position session teardown failed ({e})")
    driver = session.get("_pw")
    if driver is not None:
        try:
            await driver.stop()
        except Exception as e:
            logger.debug(f"Zepto: playwright teardown failed ({e})")


async def fetch_positions(session: dict, keyword: str, lat: float,
                          lon: float) -> list[dict]:
    """Search results for one keyword at one store, ad-flagged.

    ⚠️ Zepto binds a search to a store by HEADER, not by coordinate — sending lat/lon
    alone returns a valid 200 carrying a generic catalog, with nothing in the response
    to say so. The store id is passed explicitly where we have one; otherwise the
    scraper resolves the coordinate, which spends a separate and independently
    rate-limited budget (`get_page`) that this project has exhausted once before.

    Raises when the search could not be performed — a block, or a transport failure —
    so the caller records an error rather than a silent "nothing found". That
    distinction is the point: "we could not look" must never read as "our ad is not
    there", which under `RAISE_WHEN_ABSENT` would bid money against no evidence.

    A `gate` (299 LOGIN_REQUIRED) or `rate` (429) is retried ONCE after the pause the
    scraper itself publishes. Both are transient and shared — 299 is documented as
    self-clearing in about a minute — so losing a whole 15-minute tick to one is
    wasteful when we know how long to wait. Anything still blocked after that raises.
    """
    import asyncio

    from scraper.platforms.zepto.public_data import endpoints as pub_ep
    from scraper.platforms.zepto.public_data import scraper as zs

    async def _once():
        return await zs.search(session, keyword, lat=lat, lon=lon,
                               merchant_id=session.get("_merchant_id") or None)

    res = await _once()
    kind = res.get("kind")
    if res.get("blocked") and kind in ("gate", "rate"):
        pause = pub_ep.GATE_PAUSE_S if kind == "gate" else pub_ep.RATE_PAUSE_S
        logger.warning(
            f"Zepto {kind} on {keyword!r} ({res.get('error')}) — waiting {pause:g}s and "
            f"retrying once; this throttle is shared and self-clearing")
        await asyncio.sleep(pause)
        res = await _once()

    if res.get("blocked"):
        raise RuntimeError(
            f"Zepto blocked the search for {keyword!r}: {res.get('error') or 'blocked'}")
    if not res.get("ok"):
        raise RuntimeError(
            f"Zepto search for {keyword!r} failed: {res.get('error') or 'unknown error'}")
    return res.get("products") or []


def locate_position(results: list[dict], keyword: str, lat: float, lon: float, *,
                    products: list[dict] | None = None, campaign_id=None,
                    match_type: str = "EXACT", brand_name: str | None = None,
                    **_ignored) -> tuple[float | None, str]:
    """Find THIS campaign+keyword's sponsored slot in already-fetched results (pure).

    Attribution is by campaign id from the row's `uclId`, not by product-name
    similarity — see positions.py. `products` supplies the campaign's variant ids as
    a secondary signal for the case where the tracking id does not decode.
    """
    from campaign_manager.marketplaces.zepto import positions

    return positions.locate(
        results, keyword, lat, lon,
        campaign_id=campaign_id, match_type=match_type,
        variant_ids=[p.get("pid") for p in (products or [])],
        brand_name=brand_name,
    )


async def read_wallet(client) -> dict:
    """Prepaid balance, and a warning when it is low.

    Deliberately NOT a guardrail: an empty wallet does not make a budget change
    wrong, and refusing to act would be worse than acting loudly. Campaigns simply
    stop delivering, which is Zepto's decision to make, not ours.
    """
    wallet = await zc.get_wallet(client)
    balance = wallet.get("current_balance")
    if isinstance(balance, (int, float)) and balance <= 0:
        logger.error(
            f"Zepto wallet is empty (balance {balance}) — campaigns will not deliver "
            "regardless of their budgets, and we cannot top it up (recharge is not in "
            "our permissions). This needs a human."
        )
    return wallet


# ── writes (guarded; only reached via writes.py) ─────────────────────────────
async def _rebased_payload(client, campaign_id: int) -> tuple[dict, dict]:
    """Read the campaign NOW and translate it. Returns (payload, live_detail).

    Always a fresh read. Reusing a detail fetched earlier in the run would let us
    resubmit a campaign as it was minutes ago — silently reverting anything changed
    in the dashboard meanwhile.
    """
    detail = await zc.get_campaign_detail(client, campaign_id)
    options = await _targeting_options(client)
    return translate.to_put(detail, options, campaign_id), detail


async def _targeting_options(client) -> dict:
    """Brand-level city list, cached for the life of the client.

    Needed by every write (a campaign targeting ALL cities sends the explicit list),
    but it is brand-level and static within a run — fetching it per write would
    triple the request count for no benefit.
    """
    cached = getattr(client, "_targeting_options", None)
    if cached is None:
        cached = await zc.get_targeting_options(client)
        client._targeting_options = cached
    return cached


async def _put_one_field(client, campaign_id: int, field_path: str,
                         mutate, *, base: dict | None = None) -> dict:
    """THE Zepto write primitive: change exactly one field of a live campaign.

    Zepto has no targeted write. Budget and bid are both a PUT of the WHOLE
    campaign, so the body carries geo targeting, the product list and every other
    keyword's bid. A wrong payload does not fail — it rewrites live configuration.

    Hence the guard: build the payload from a fresh read, apply the mutation, and
    diff the two. If anything other than `field_path` moved, refuse.

    That single check catches both failure modes at once — a translator bug, and a
    campaign edited in the dashboard between our read and our write. The second is
    routine here, not exotic: one session per user means a human is often in there.

    `base` lets a caller that ALREADY read the campaign hand that payload in rather
    than causing a second read. `apply_bid` needs one to locate the keyword's index,
    and reusing it is not merely cheaper: computing the index from one read and
    mutating a different one means the index can point at the wrong keyword if the
    campaign's keyword list changed in between. Same read, same indices.
    """
    if base is None:
        base, _detail = await _rebased_payload(client, campaign_id)
    new = json.loads(json.dumps(base))      # deep copy; payloads nest
    mutate(new)

    changed = translate.diff(base, new)
    # `diff` yields "<path>: <old> -> <new>"; compare the PATHS, since the values
    # are exactly what we intend to differ.
    paths = [line.split(":", 1)[0] for line in changed]
    if paths != [field_path]:
        raise RuntimeError(
            f"Zepto write REFUSED for campaign {campaign_id}: expected exactly "
            f"{field_path!r} to change, got {changed or 'no change'}. The campaign "
            "may have been edited since it was read, or the translator has drifted. "
            "Nothing was sent."
        )
    return await zc.update_campaign(client, campaign_id, new)


async def apply_budget(client, campaign_id: int, budget: float) -> dict:
    """Set the daily budget via read-modify-write.

    `writes.py` has already applied policy (no-op, bounds, rate limit) by the time
    this runs; the diff guard here is the mechanism-level backstop.
    """
    target = int(round(float(budget)))
    resp = await _put_one_field(
        client, campaign_id, ".daily_budget",
        lambda p: p.update(daily_budget=target),
    )
    logger.info(f"Zepto campaign {campaign_id}: daily_budget -> ₹{target}")
    # Zepto answers {"message": "Campaign updated successfully"} with no status
    # field; writes.py reads `status`/`success`, so map it into that shape.
    return {"success": True, "response": resp}


async def apply_bid(client, campaign_id: int, keyword: str, cpm: int,
                    match_type: str = "EXACT") -> dict:
    """Set ONE keyword's bid, leaving every sibling untouched.

    ⚠️ `cpm` is the contract's Blinkit-flavoured name; Zepto bids in CPC. The engine
    steps by percentage, which is unit-agnostic, so the value passes through — but
    the absolute floors in config are rupee amounts and need per-platform tuning
    before this is trusted live (see PLAN-cm.md).
    """
    target = int(round(float(cpm)))
    # ONE read, used for both the index lookup and the mutation — see `_put_one_field`.
    base, _detail = await _rebased_payload(client, campaign_id)
    index = _keyword_index(base, campaign_id, keyword, match_type)
    resp = await _put_one_field(
        client, campaign_id, f".keyword_targeting[{index}].bid_value",
        lambda p: p["keyword_targeting"][index].update(bid_value=target),
        base=base,
    )
    logger.info(
        f"Zepto campaign {campaign_id}: bid[{keyword!r}/{match_type}] -> ₹{target}")
    return {"success": True, "response": resp}


def _keyword_index(payload: dict, campaign_id: int, keyword: str,
                   match_type: str) -> int:
    """Where this keyword sits in an ALREADY-READ payload's `keyword_targeting[]`.

    Matched on (text, match_type) — the text alone is ambiguous, because Zepto bids
    one keyword under several match types at different rates, and writing to the
    wrong one would move a bid nobody asked to move.

    Pure, and takes the payload rather than fetching one: the index is only valid for
    the exact list it was computed from, so the caller must mutate that same payload.
    """
    for i, kw in enumerate(payload.get("keyword_targeting", [])):
        if kw.get("text") == keyword and kw.get("match_type") == match_type:
            return i
    raise RuntimeError(
        f"Zepto campaign {campaign_id} has no keyword {keyword!r} with match type "
        f"{match_type!r}. Refusing to write — adding a keyword is not a bid change."
    )


async def apply_status(client, campaign_id: int, target: str, *,
                       budget: float | None = None) -> dict:
    """Start or stop. A dedicated endpoint, so none of the whole-campaign risk.

    `budget` is accepted for contract compatibility and IGNORED: Blinkit needs one
    because its restart re-submits the campaign, but Zepto's activate is an
    idempotent flip that restores the prior budget and bids by itself.
    """
    canonical = (target or "").strip().lower()
    if canonical in ("paused", "stopped", "pause", "stop"):
        pause = True
    elif canonical in ("running", "active", "resume", "start"):
        pause = False
    else:
        raise RuntimeError(f"Zepto: unknown target status {target!r}")

    if budget is not None:
        logger.info(
            f"Zepto campaign {campaign_id}: ignoring budget=₹{budget} on "
            "activation — Zepto restores the campaign's own budget."
        )
    resp = await zc.set_status(client, campaign_id, pause=pause)
    logger.info(f"Zepto campaign {campaign_id}: {'paused' if pause else 'activated'}")
    return {"success": True, "response": resp}


def set_advertiser(client, advertiser_id) -> None:
    """Pin the ad account for this client's writes (B3).

    Zepto needs no stored id — `brand_id` arrives in the login response — so this
    ASSERTS rather than sets. Blinkit must store one because it appears in no read
    API, and a stale value there writes real money to a dead account; here we can
    check instead of trust.
    """
    if advertiser_id in (None, "", 0):
        return
    if str(advertiser_id) not in {str(b) for b in client.brand_ids}:
        raise RuntimeError(
            f"Zepto account mismatch: the stored account_ref {advertiser_id!r} is not "
            f"among this session's brand ids {client.brand_ids}. Refusing to write — "
            "the session may belong to a different account than the one configured."
        )
    logger.info(f"Zepto account asserted: {advertiser_id}")


async def resolve_advertiser(client):
    """What a write would be scoped to. Derived, not stored."""
    return client.brand_id


def campaign_name(detail: dict) -> str | None:
    """The campaign's name out of a raw detail. Zepto calls it `campaign_name`."""
    return (detail or {}).get("campaign_name")


def resume_overwrites(detail: dict, budget: float | None) -> dict | None:
    """Nothing is overwritten by a Zepto resume — see RESUME_RESUBMITS."""
    return None
