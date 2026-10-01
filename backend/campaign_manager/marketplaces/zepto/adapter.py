"""Zepto adapter — the marketplace-specific *mechanism* (see marketplaces/base.py).

`writes.py` owns the policy (dry-run default, bounds, no-op suppression, rate
limiting, audit). This module owns how Zepto is actually driven, and one invariant
that is Zepto's alone:

## Every write is read-modify-write, and must change exactly one field

Budget and bid are both a **whole-campaign PUT** — geo targeting, the product list
and every other keyword's bid ride in the same body. A wrong payload does not fail
loudly; it rewrites live configuration.

So `apply_budget` and `apply_bid` never construct a payload. Holding the campaign's write
lock (`repo.campaign_write_lock` — the budget and bid lanes run in parallel, and each PUT
carries the other's field), `_put_one_field`:

    1. reads the campaign fresh,
    2. translates it into the PUT shape (`translate.to_put`),
    3. mutates ONE field,
    4. diffs against the untouched translation and REFUSES unless exactly that field
       changed,
    5. checks the whole body against the campaign as Zepto reported it
       (`payload.py`, a rule per PUT field) and REFUSES on any other difference,
    6. only then PUTs — and reads the campaign back, logging an ERROR if it does not
       equal what was sent.

Steps 4 and 5 are the load-bearing ones. Step 4 catches a mutation that touched more than
it meant to, or a campaign that changed under us between read and write (someone editing
in the dashboard while a job runs is routine here, not exotic). Step 5 catches what step 4
cannot: a translator that rewrites a field the SAME way on both sides of the diff — the
empty city list, the wrong city shape and the dropped negative keywords of 2026-09-21
(A12–A14) all passed step 4.

⚠️ This is mechanism, not policy, which is why it lives here and not in `writes.py`.
Blinkit's writes are whole-campaign PUTs too (docs §8.2b — a hardcoded city list once
broadened nine live campaigns to pan-India) and carry their own equivalent in
`blinkit/payload.py`; the two differ in shape, so each marketplace owns its own check.

## Status vocabulary

Zepto's own strings map onto the engine's canonical set (`status.py`). Two are `held` —
live, stoppable, not startable, never ours to clear: `DAILY_BUDGET_EXHAUSTED` (raise the
budget) and `INSUFFICIENT_WALLET_BALANCE` (top up the wallet on Zepto; a budget change
does nothing) — and `hold_reason` tells them apart. `ENDED` is terminal. An unmapped value
passes through unchanged so a guardrail can refuse it by name rather than silently
coercing it into something writable.
"""
import json
from urllib.parse import unquote, urlsplit

from app.utils.logger import logger
from campaign_manager import config
from campaign_manager.marketplaces.zepto import client as zc
from campaign_manager.marketplaces.zepto import eligibility
from campaign_manager.marketplaces.zepto import endpoints as ep
from campaign_manager.marketplaces.zepto import payload as zpayload
from campaign_manager.marketplaces.zepto import status as zstatus
from campaign_manager.marketplaces.zepto import translate
from campaign_manager.marketplaces.zepto.transport import setup  # noqa: F401  (contract)
from campaign_manager.writes import SessionExpired, WriteRefused

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

# A PAUSED campaign's budget can be changed (ZC-C11). Blinkit refuses that — a stopped
# campaign only offers RESTART — so the budget engine gates the write on status; Zepto does
# not need the gate. Evidence, not assumption: both live budget writes on Tech Test 2427461
# (2026-09-21, runs `ca8e7cd1` ₹551→552 and `44cbd672` ₹552→551) were made while it was
# PAUSED, landed, and read back with the status unchanged.
#
# It also makes a start correct: `RESUME_RESUBMITS` is False, so activating restores the
# campaign's OWN budget. The engine therefore writes the window's budget FIRST and then
# activates, rather than assuming the start carries it (which on Zepto it silently does not).
BUDGET_WHILE_PAUSED = True

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

# Our sponsored slot is recognised by the CAMPAIGN id Zepto stamps on it (`uclId`), not by
# product — so a campaign whose product list failed to read can still be found in search
# (ZC-C20). An adapter without this (Blinkit, which matches by product) has the bid engine
# skip such a tick instead of reading "not showing" and raising the bid on no evidence.
RECOGNISES_AD_BY_CAMPAIGN = True

# Where position is measured when a rule carries no store of its own. Same Bengaluru
# fallback the bid engine uses, kept here so the adapter is self-contained.
_DEFAULT_LAT, _DEFAULT_LON = 12.9767, 77.5713

# The vocabulary lives in `status.py` (pure — the API reads it too); `_canonical` keeps
# its name here because the engines and tests reach it through the adapter.
_canonical = zstatus.canonical


def hold_reason(detail: dict) -> str | None:
    """Why this campaign is held, when it is — for the refusal a person reads.

    Zepto has two holds that need opposite advice: a spent daily budget (raise it) and an
    empty wallet (top up on Zepto; a budget change does nothing). Both are canonical
    `held`, so without this every wallet-held campaign was told to raise its budget.
    """
    return zstatus.hold_reason((detail or {}).get("status"))


def automation_refusal(detail: dict) -> str | None:
    """Why automations must not touch this campaign, or None (ZC-C3 — `eligibility.py`).
    Optional on the contract: the engines read it with `getattr`, so Blinkit needs none."""
    return eligibility.refusal_from_detail(detail)


# A Zepto bid rule must name a city or a store — see `eligibility.RULE_NEEDS_LOCATION`.
REQUIRES_RULE_LOCATION = eligibility.RULE_NEEDS_LOCATION


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
    """Zepto's published minimum bid per (keyword, match_type) for a campaign (ZC-C1).

    One `keyword/config` request for the campaign's whole bidding-keyword list — the
    analogue of Blinkit's `get_keyword_attributes` — read LIVE because it decides what gets
    written. Keyed in OUR vocabulary, which on Zepto is Zepto's own (EXACT/PHRASE/BROAD):
    the engine looks up `(keyword, rule.match_type)` and must not translate.

    Floors genuinely vary per keyword (bread 9, ricotta 3). A keyword Zepto omits is
    absent here, and `effective_floor` then falls back to the rule's own `min_bid`;
    `writes.apply_bid` still enforces `MIN_BID` flat on top (the observed default of ₹10
    for keywords with no config). Returns {} on any failure — refusing to bid because a
    lookup failed would be worse than bidding at the configured minimum.
    """
    try:
        if detail is None:
            detail = await zc.get_campaign_detail(client, campaign_id)
        pairs = sorted(translate.bids_from_detail(detail or {}))
        return await zc.get_keyword_floors(client, pairs)
    except Exception as e:
        logger.warning(f"Zepto campaign {campaign_id}: could not read keyword floors ({e}) "
                       "— falling back to the rule's own minimum")
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
#
# THROUGH A PROXY (`config.ZEPTO_SHOPPER_PROXY_ON`, off by default). Where Zepto refuses the
# machine's own address — the VM — this session, and nothing else, goes out through a proxy,
# and the scraper searches by typing into Zepto's page instead of replaying (`typed_search.py`
# says why). Nothing below this adapter knows: same session dict, same `fetch_positions`,
# same results.

def shopper_proxy() -> dict | None:
    """Playwright's proxy setting for the shopper session, or None when the switch is off.

    Raises RuntimeError when the switch is ON without a usable address. Going direct instead
    would look like it worked on a laptop and fail on the VM in a way that reads as Zepto
    blocking us — so it holds the run and names the setting.

    ⚠️ The address carries the login. Nothing here may put it in a message or a log:
    `proxy_label` is the only printable form.
    """
    if not config.ZEPTO_SHOPPER_PROXY_ON:
        return None
    raw = config.ZEPTO_SHOPPER_PROXY
    try:
        u = urlsplit(raw)
        scheme, host, port = u.scheme, u.hostname, u.port
    except ValueError:
        scheme = host = port = None
    # http(s) only: Chromium cannot log in to a SOCKS5 proxy.
    if scheme not in ("http", "https") or not host or not port:
        raise RuntimeError(
            "Zepto shopper proxy is switched on (CM_ZEPTO_SHOPPER_PROXY_ON) but "
            "CM_ZEPTO_SHOPPER_PROXY is not a usable http://user:pass@host:port address")
    proxy = {"server": f"{scheme}://{host}:{port}"}
    if u.username:
        proxy.update(username=unquote(u.username), password=unquote(u.password or ""))
    return proxy


def proxy_label(proxy: dict | None) -> str:
    """host:port — the only part of a proxy setting that may be printed."""
    return (proxy or {}).get("server", "").split("://")[-1]


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
    proxy = shopper_proxy()            # raises before a browser is started
    driver = await async_playwright().start()
    why: dict = {}
    try:
        if proxy:
            session = await zs.open_session(driver, lat, lon, proxy=proxy, typed=True,
                                            why=why)
        else:
            session = await zs.open_session(driver, lat, lon)
    except Exception:
        await driver.stop()
        raise
    if not session:
        await driver.stop()
        if not proxy:
            raise RuntimeError(
                f"Zepto: could not open a consumer search session at ({lat}, {lon})")
        reason = why.get("nav_error") or "Zepto did not answer the warm-up search"
        if "ERR_PROXY" in reason or "ERR_TUNNEL" in reason:
            # The proxy itself: down, out of data, or the login refused (seen 2026-09-30,
            # 503 on every connection). Said first and plainly — see bid._PLAIN_CAUSES.
            raise RuntimeError(f"Zepto shopper proxy did not connect "
                               f"({proxy_label(proxy)}: {reason})")
        raise RuntimeError(f"Zepto: could not open a consumer search session through the "
                           f"proxy {proxy_label(proxy)} ({reason})")
    session["_pw"] = driver
    if proxy:
        session["_wait_budget_s"] = config.ZEPTO_SHOPPER_WAIT_BUDGET_S
        logger.info(f"Zepto: shopper search is going through the proxy {proxy_label(proxy)}, "
                    f"searching by typed search")
    return session


async def close_position_session(session: dict) -> None:
    """Release the session AND the playwright driver it owns. Never raises — a
    teardown failure must not fail a run that already did its work."""
    from scraper.platforms.zepto.public_data import scraper as zs

    if not session:
        return
    if session.get("typed") is not None:
        # What the proxy is billed on. One line a run, so a month's cost can be read off the
        # logs instead of the provider's dashboard.
        from scraper.platforms.zepto.public_data import typed_search
        logger.info(f"Zepto: shopper search through the proxy used {typed_search.usage(session)}")
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
                          lon: float, *, merchant_id: str | None = None) -> list[dict]:
    """Search results for one keyword at one store, ad-flagged.

    ⚠️ Zepto binds a search to a store by HEADER, not by coordinate — sending lat/lon
    alone returns a valid 200 carrying a generic catalog, with nothing in the response
    to say so. The store id is passed explicitly where we have one; otherwise the
    scraper resolves the coordinate, which spends a separate and independently
    rate-limited budget (`get_page`) that this project has exhausted once before.

    `merchant_id` comes from the engine's measurement store (every catalogue store has
    one). It used to be read only from `session["_merchant_id"]`, which nothing ever
    set — so every multi-store read quietly paid the `get_page` cost.

    Raises when the search could not be performed — a block, or a transport failure —
    so the caller records an error rather than a silent "nothing found". That
    distinction is the point: "we could not look" must never read as "our ad is not
    there", which under `RAISE_WHEN_ABSENT` would bid money against no evidence.

    A `gate` (299 LOGIN_REQUIRED) or `rate` (429) is retried ONCE after the pause the
    scraper itself publishes. Both are transient and shared — 299 is documented as
    self-clearing in about a minute — so losing a whole 15-minute tick to one is
    wasteful when we know how long to wait. Anything still blocked after that raises.

    A session with a wait budget (`_wait_budget_s`, set on a proxied one) instead keeps
    waiting and retrying for as long as the budget lasts, then stops. Through a proxy a
    refusal spell has lasted ~2 minutes right after the warm-up (2026-10-01) — one retry gave
    up while the very next search was answered — and the address is shared with strangers,
    so the budget is what keeps one bad spell from eating the whole 15-minute tick.
    """
    import asyncio

    from scraper.platforms.zepto.public_data import endpoints as pub_ep
    from scraper.platforms.zepto.public_data import scraper as zs

    async def _once():
        return await zs.search(session, keyword, lat=lat, lon=lon,
                               merchant_id=merchant_id or session.get("_merchant_id") or None)

    res = await _once()
    budget = session.get("_wait_budget_s")
    retries = 0
    while res.get("blocked") and res.get("kind") in ("gate", "rate"):
        kind = res["kind"]
        pause = pub_ep.GATE_PAUSE_S if kind == "gate" else pub_ep.RATE_PAUSE_S
        waited = session.get("_waited_s", 0.0)
        if budget is None and retries:
            break                                   # no budget: one retry, as always
        if budget is not None and waited + pause > budget:
            logger.warning(
                f"Zepto {kind} on {keyword!r} ({res.get('error')}) — not waiting: this run "
                f"has already waited {waited:g}s of the {budget:g}s it may")
            break
        logger.warning(
            f"Zepto {kind} on {keyword!r} ({res.get('error')}) — waiting {pause:g}s and "
            f"retrying; this throttle is shared and self-clearing")
        await asyncio.sleep(pause)
        session["_waited_s"] = waited + pause
        retries += 1
        res = await _once()

    if res.get("blocked"):
        raise RuntimeError(
            f"Zepto blocked the search for {keyword!r}: {res.get('error') or 'blocked'}")
    if not res.get("ok"):
        raise RuntimeError(
            f"Zepto search for {keyword!r} failed: {res.get('error') or 'unknown error'}")
    return res.get("products") or []


async def read_store_catalog(session: dict, query: str, lat: float, lon: float, *,
                             cap: int, names, merchant_id: str | None = None) -> dict:
    """Our products at one store, for the stock check — one capped brand search on the
    run's position session. A READ. On Zepto a product missing from it is not sellable
    there (Zepto hides sold-out products): see catalog.py."""
    from campaign_manager.marketplaces.zepto import catalog
    return await catalog.read(session, query, lat, lon, cap=cap, names=names,
                              merchant_id=merchant_id)


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
    """The prepaid wallet as Zepto reports it (`current_balance`, …). A READ only.

    What a low balance means — and the warning, which is deliberately NOT a guardrail —
    lives in `campaign_manager/wallet.py`, which both engines call once per run (ZC-C12).
    It used to log its own ERROR here, but nothing called it, so it never fired.
    """
    return await zc.get_wallet(client)


# ── writes (guarded; only reached via writes.py) ─────────────────────────────
async def _rebased_payload(client, campaign_id: int) -> tuple[dict, dict]:
    """Read the campaign NOW and translate it. Returns (payload, live_detail).

    Always a fresh read. Reusing a detail fetched earlier in the run would let us
    resubmit a campaign as it was minutes ago — silently reverting anything changed
    in the dashboard meanwhile.

    A failed read means NOTHING was sent, so it is a refusal of this one write, not a
    crash of the run — except a dead session, which every later write would hit too.
    """
    try:
        detail = await zc.get_campaign_detail(client, campaign_id)
        options = await _targeting_options(client, detail)
    except SessionExpired:
        raise
    except Exception as e:
        raise WriteRefused(
            f"could not re-read campaign {campaign_id} from Zepto before writing "
            f"({' '.join(str(e).split())[:160]}) — nothing was sent") from e
    payload = translate.to_put(detail, options, campaign_id)
    # The diff guard cannot see a translation that is wrong in both copies; this catches
    # the one that happened (an empty city list — ZC-A12).
    refusal = translate.write_refusal(payload)
    if refusal:
        raise WriteRefused(f"campaign {campaign_id}: {refusal}")
    return payload, detail


async def _targeting_options(client, detail: dict | None = None) -> dict:
    """The brand's city list for this kind of campaign, cached for the life of the client.

    Needed by every write (a campaign targeting ALL cities sends the explicit list), but
    static within a run — fetching it per write would triple the request count. Cached
    per (campaign_type, sub_type), since the dashboard asks per type.
    """
    detail = detail or {}
    key = (detail.get("campaign_type") or "PLA",
           detail.get("campaign_sub_type") or "AUCTION_UP_SELL")
    cache = getattr(client, "_targeting_options", None)
    if not isinstance(cache, dict) or not all(isinstance(k, tuple) for k in cache):
        cache = {}
        client._targeting_options = cache
    if key not in cache:
        cache[key] = await zc.get_targeting_options(
            client, campaign_type=key[0], campaign_sub_type=key[1])
    return cache[key]


async def _put_one_field(client, campaign_id: int, field_path: str,
                         mutate, *, shape: str, keyword: tuple[str, str] | None = None,
                         base: dict | None = None, detail: dict | None = None) -> dict:
    """THE Zepto write primitive: change exactly one field of a live campaign.

    Zepto has no targeted write. Budget and bid are both a PUT of the WHOLE
    campaign, so the body carries geo targeting, the product list, every negative
    keyword and every other keyword's bid. A wrong payload does not fail — it
    rewrites live configuration. Three guards, each catching what the others cannot:

    1. **The one-field diff** — the payload before and after our mutation differ in
       exactly `field_path`. Catches a mutation that touches more than it should.
       It is a SELF-consistency check, so it cannot see a translator that is wrong in
       both copies (ZC-A12..A14 all passed it).
    2. **The faithfulness check** (`payload.verify`) — Blinkit's design: every field
       we send is read back and compared with the campaign AS ZEPTO REPORTED IT; only
       what `shape` declares (the budget, or ONE keyword's bid) may differ. This is the
       guard that catches a translator bug.
    3. **The read-back** (after the PUT) — the campaign must now equal what we sent.
       Catches Zepto normalising something away. It cannot undo a write, so it logs an
       ERROR (which alerts) and reports the mismatch in the response; it never raises,
       because the write has already landed.

    `base` (+ its `detail`) lets a caller that ALREADY read the campaign hand that read
    in: `apply_bid` needs it to find the keyword's index, and the index is only valid for
    the list it was computed from. Same read, same indices.
    """
    if base is None or detail is None:
        base, detail = await _rebased_payload(client, campaign_id)
    # 0 — only a campaign the automations are allowed to touch (ZC-C3), judged on this read.
    refused = automation_refusal(detail)
    if refused:
        raise WriteRefused(f"campaign {campaign_id} is not automatable: {refused}. "
                           "Nothing was sent.")
    new = json.loads(json.dumps(base))      # deep copy; payloads nest
    mutate(new)

    # 1 — exactly the intended path moved.
    changed = translate.diff(base, new)
    # `diff` yields "<path>: <old> -> <new>"; compare the PATHS, since the values
    # are exactly what we intend to differ.
    paths = [line.split(":", 1)[0] for line in changed]
    if paths != [field_path]:
        raise WriteRefused(
            f"Zepto write REFUSED for campaign {campaign_id}: expected exactly "
            f"{field_path!r} to change, got {changed or 'no change'}. The campaign "
            "may have been edited since it was read, or the translator has drifted. "
            "Nothing was sent."
        )
    # 2 — the whole body says what the campaign says, apart from the intended change.
    zpayload.verify(detail, new, shape=shape, campaign_id=campaign_id, keyword=keyword)

    resp = await zc.update_campaign(client, campaign_id, new)

    # 3 — did the campaign end up as we sent it?
    mismatch = await _read_back_mismatch(client, campaign_id, new)
    if mismatch:
        logger.error(
            f"Zepto campaign {campaign_id}: the {shape} write LANDED, but the campaign now "
            f"differs from what we sent — " + "; ".join(mismatch)
            + ". Check it in the dashboard; nothing was rolled back.")
        return {**(resp if isinstance(resp, dict) else {"response": resp}),
                "post_write_mismatch": mismatch}
    return resp


async def _read_back_mismatch(client, campaign_id: int, sent: dict) -> list[str]:
    """Differences between a FRESH read and the body we just PUT. Never raises — the write
    has landed, and a failed confirmation must not turn it into a failed run."""
    try:
        after = await zc.get_campaign_detail(client, campaign_id)
    except Exception as e:
        logger.warning(f"Zepto campaign {campaign_id}: could not read it back after the "
                       f"write to confirm it ({' '.join(str(e).split())[:120]})")
        return []
    return zpayload.check(after, sent, shape=zpayload.READBACK)


def _write_lock(client, campaign_id: int):
    """One writer at a time per campaign (ZC-C8), across the read AND the PUT.

    Zepto has no targeted write, so a budget change and a bid change that overlap both read
    the campaign as it was and the second PUT reverts the first's field — silently, since
    both succeed. The budget and bid engines run in parallel lanes (`cm_ops`, `cm_bid`), so
    this is a routine overlap, not a corner case: at a window boundary both fire at once.

    Imported here rather than at module import: `repo` reaches the DB, and the adapter is
    also imported by tooling that has none.
    """
    from campaign_manager import repo

    return repo.campaign_write_lock("zepto", getattr(client, "tenant_id", None), campaign_id)


async def apply_budget(client, campaign_id: int, budget: float) -> dict:
    """Set the daily budget via read-modify-write.

    `writes.py` has already applied policy (no-op, bounds, rate limit) by the time
    this runs; the diff guard here is the mechanism-level backstop.
    """
    from campaign_manager import repo

    target = int(round(float(budget)))
    try:
        async with _write_lock(client, campaign_id):
            resp = await _put_one_field(
                client, campaign_id, ".daily_budget",
                lambda p: p.update(daily_budget=target),
                shape=zpayload.BUDGET,
            )
    except repo.WriteLockBusy as e:
        raise WriteRefused(f"campaign {campaign_id}: {e} — nothing was sent, so the two "
                           f"writes cannot overwrite each other") from e
    logger.info(f"Zepto campaign {campaign_id}: daily_budget -> ₹{target}")
    # Zepto answers {"message": "Campaign updated successfully"} with no status
    # field; writes.py reads `status`/`success`, so map it into that shape.
    return _landed(resp)


async def apply_bid(client, campaign_id: int, keyword: str, cpm: int,
                    match_type: str = "EXACT") -> dict:
    """Set ONE keyword's bid, leaving every sibling untouched.

    ⚠️ `cpm` is the contract's Blinkit-flavoured name; Zepto bids in CPC. The engine
    steps by percentage, which is unit-agnostic, so the value passes through — but
    the absolute floors in config are rupee amounts and need per-platform tuning
    before this is trusted live (see PLAN-cm.md).
    """
    from campaign_manager import repo

    target = int(round(float(cpm)))
    try:
        # The lock covers the READ too: the keyword index is only valid for the list it was
        # computed from, and a budget PUT landing in between would rewrite that list.
        async with _write_lock(client, campaign_id):
            # ONE read, for both the index lookup and the mutation — see `_put_one_field`.
            base, detail = await _rebased_payload(client, campaign_id)
            index = _keyword_index(base, campaign_id, keyword, match_type)
            resp = await _put_one_field(
                client, campaign_id, f".keyword_targeting[{index}].bid_value",
                lambda p: p["keyword_targeting"][index].update(bid_value=target),
                shape=zpayload.BID, keyword=(keyword, match_type), base=base, detail=detail,
            )
    except repo.WriteLockBusy as e:
        raise WriteRefused(f"campaign {campaign_id}: {e} — nothing was sent, so the two "
                           f"writes cannot overwrite each other") from e
    logger.info(
        f"Zepto campaign {campaign_id}: bid[{keyword!r}/{match_type}] -> ₹{target}")
    return _landed(resp)


def _landed(resp) -> dict:
    """The shape `writes.py` reads (`success`), with any post-write mismatch lifted to the top
    so a caller can see it without digging into Zepto's own reply."""
    out = {"success": True, "response": resp}
    if isinstance(resp, dict) and resp.get("post_write_mismatch"):
        out["post_write_mismatch"] = resp["post_write_mismatch"]
    return out


def _keyword_index(payload: dict, campaign_id: int, keyword: str,
                   match_type: str) -> int:
    """Where this keyword sits in an ALREADY-READ payload's `keyword_targeting[]`.

    Matched on (text, match_type) — the text alone is ambiguous, because Zepto bids
    one keyword under several match types at different rates, and writing to the
    wrong one would move a bid nobody asked to move.

    Pure, and takes the payload rather than fetching one: the index is only valid for
    the exact list it was computed from, so the caller must mutate that same payload.

    Negative keywords share the list (ZC-A14) and are skipped: a bid rule whose keyword
    happens to equal a negative one must not give that negative a bid.
    """
    for i, kw in enumerate(payload.get("keyword_targeting", [])):
        if kw.get("is_negative"):
            continue
        if kw.get("text") == keyword and kw.get("match_type") == match_type:
            return i
    raise WriteRefused(
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


# ── Catalogue write-back (ZC-B7; Blinkit's twin is in blinkit/adapter.py) ─────
#
# A landed write changes Zepto but not `zepto_ad_campaigns` / `_keywords` — the catalogue
# the product reads — until the next scrape. `writes.py` asks the adapter WHERE a write
# lands and `repo.record_applied` patches it (UPDATE only; never advances `scraped_at`).

CATALOG_CAMPAIGNS = "zepto.campaigns"
CATALOG_KEYWORDS = "zepto.keywords"

# Only the two states we ever WRITE. Zepto's activate/pause are dedicated flips, so the
# status is exactly this — unlike Blinkit, a resume never re-submits the budget.
_STATUS_TO_ZEPTO = {"running": ep.STATUS_ACTIVE, "paused": ep.STATUS_PAUSED}


def catalog_patch(what: str, *, campaign_id: int, value, keyword: str | None = None,
                  match_type: str | None = None, budget: float | None = None) -> list[dict]:
    """Where a landed write lands in OUR catalogue — `[{table, key, set}]`. Pure.

    No vocabulary translation for bids: a Zepto rule's match type IS Zepto's own
    (EXACT/PHRASE/BROAD), unlike Blinkit's BROAD→SMART. `budget` is ignored on a status
    write for the same reason `RESUME_RESUBMITS` is False: activating changes no budget.
    An unknown `what` returns [] — the marketplace has already been mutated by now, so a
    stale column beats a failed run.
    """
    if what == "budget":
        return [{"table": CATALOG_CAMPAIGNS, "key": {"campaign_id": campaign_id},
                 "set": {"daily_budget": int(round(float(value)))}}]
    if what == "status":
        zepto_status = _STATUS_TO_ZEPTO.get(value)
        if zepto_status is None:
            return []
        return [{"table": CATALOG_CAMPAIGNS, "key": {"campaign_id": campaign_id},
                 "set": {"status": zepto_status}}]
    if what == "bid":
        return [{"table": CATALOG_KEYWORDS,
                 "key": {"campaign_id": campaign_id, "keyword": keyword,
                         "match_type": (match_type or "EXACT").upper()},
                 "set": {"bid_value": int(value)}}]
    return []


def campaign_name(detail: dict) -> str | None:
    """The campaign's name out of a raw detail. Zepto calls it `campaign_name`."""
    return (detail or {}).get("campaign_name")


def resume_overwrites(detail: dict, budget: float | None) -> dict | None:
    """Nothing is overwritten by a Zepto resume — see RESUME_RESUBMITS."""
    return None
