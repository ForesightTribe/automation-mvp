"""Blinkit adapter — the marketplace-specific *mechanism* (docs §5.1 / D17).

Thin wrappers over the Blinkit engine (`.client` + `.live_position`), which is now
**vendored into this package** (copied out of the legacy `ad_campaigns/` on 2026-07-30)
so campaign-manager v2 owns its whole Blinkit stack and no longer imports v1. `writes.py`
owns the dry-run + guardrail *policy* and calls these only when a real mutation is due.

B3: live writes send the tenant's STORED advertiser id (set on the client by
`writes.arm_live` → `set_advertiser`), rather than the client's own live derivation.
(That derivation used to fall back to a hardcoded account id; it now raises instead.)
"""
from campaign_manager.marketplaces.blinkit import payload as payload_check
from campaign_manager.marketplaces.blinkit import restart

# Resuming a Blinkit campaign is a RESTART: a full re-submission that rewrites
# budget, keywords, bids and dates. So a resume needs a budget, and `writes.py`
# subjects it to the same bounds guardrail as a budget write. Zepto declares False —
# its activate is an idempotent flip that restores the campaign's own values.
RESUME_RESUBMITS = True

# Being absent from the search results makes the bid GO UP, rather than being skipped.
#
# ⚠️ This was OFF for Blinkit until 2026-09-04, and the reason it was off is no longer
# true. The guard existed because Blinkit's DOM fallback reported every result as organic,
# so "absent" could mean a broken SOURCE rather than a missing ad — and raising against
# that is bidding on garbage. **That fallback no longer exists.** `live_position.py`
# removed it precisely because it could not read `ads_campaign_id`, which is now the sole
# source of the sponsored flag (with Blinkit's `"0"`/`"null"` string sentinels handled).
# The signal is as positive as Zepto's, so absence here is a fact about the auction too.
#
# What it fixes: a keyword outbid off the page could never climb back. Every tick saw
# "absent", skipped, and left the bid alone — and the next window open then wrote
# `min_bid`, lower still. Once off the page, off forever, which is the opposite of what a
# bid is for.
#
# ⚠️ Known and accepted (2026-09-04): if the PRODUCT MATCH breaks — a pid changes, a name
# drifts — every tick reads "absent" and the bid climbs to `max_bid` and stays there,
# paying the ceiling for a slot it never had. Relaxation cannot rescue it, because
# relaxing against a synthetic position would make the engine trim while trying to climb
# (see tests/test_absent_raises.py). The exposure is bounded by the operator's own
# ceiling, which is why this was accepted rather than gated on an absent-streak counter.
RAISE_WHEN_ABSENT = True
from campaign_manager.marketplaces.blinkit.client import setup, setup_with_state  # noqa: F401  (session bootstrap)
from campaign_manager.marketplaces.blinkit.live_position import get_live_positions


async def read_budget(client, campaign_id: int) -> int | None:
    """Current daily budget for a campaign (a READ — safe)."""
    detail, _ = await client.get_campaign_detail(campaign_id)
    budget = (detail or {}).get("campaign_budget")
    return int(budget) if budget is not None else None


async def apply_budget(client, campaign_id: int, budget: float) -> dict:
    """Set the campaign's daily budget. LIVE — only reached via writes.apply_budget.
    Sends the tenant's stored advertiser id (set on the client by arm_live)."""
    adv = getattr(client, "cm_advertiser_id", None)
    detail, _ = await client.get_campaign_detail(campaign_id)
    pacing = (detail or {}).get("pacing_type", "DAILY")
    changes = {"bidding_strategy": {"total_budget": float(budget), "pacing_type": pacing}}
    # ONE write. There used to be a retry here that resent the campaign with `pids: ""`,
    # meant to rescue a delisted catalog. Tested live 2026-09-04 (574687,
    # PRODUCT_LISTING): it does not clear the products — Blinkit ignores an empty list —
    # but it cannot succeed either, because the validator fires on the payload HAVING no
    # pids ("Please select atleast one PID"), which an empty list always does.
    #
    # It was removed rather than kept because it actively cost us the diagnosis: the
    # retry's rejection REPLACED the first response, so a failed budget write reported an
    # error about a payload we invented instead of the one you asked for. A fallback that
    # cannot fire, whose message stands in for the real one, is how the scorecard hid for
    # four weeks. `writes.apply_budget` now logs the marketplace's own message instead.
    return await client.update_campaign(campaign_id, changes, advertiser_id=adv)


async def read_bid(client, campaign_id: int, keyword: str) -> int | None:
    """Current CPM bid for a keyword in a campaign (a READ — safe)."""
    detail, _ = await client.get_campaign_detail(campaign_id)
    existing = (
        (detail.get("campaign_targeting") or {})
        .get("keyword_targeting", {})
        .get("keywords", [])
    ) or detail.get("keywords", [])
    for kw in existing:
        if kw.get("keyword") == keyword and kw.get("bids"):
            return int(kw["bids"][0].get("cpm", 0))
    return None


async def resolve_advertiser(client) -> int:
    """What Blinkit reports for this session — `client.get_advertiser_id()`, which RAISES
    rather than guessing when the id is unreadable. Shown by `cm advertiser` for comparison
    only; live writes use the per-tenant STORED value, not this. Read-only."""
    return int(await client.get_advertiser_id())


def set_advertiser(client, advertiser_id: int) -> None:
    """Make subsequent writes on this client send `advertiser_id` (the tenant's stored
    account), overriding Blinkit's unreliable derivation. Called by writes.arm_live."""
    client.cm_advertiser_id = int(advertiser_id)


def bids_from_detail(detail: dict) -> dict[str, int]:
    """{keyword: cpm} out of an ALREADY-FETCHED campaign detail — no I/O.

    Split out so a caller that already holds the detail (the bid optimizer, which needs the
    campaign's status from the same response) doesn't fetch it twice. Keeps Blinkit's
    two-places-for-keywords quirk in the adapter, where marketplace shapes belong."""
    existing = (
        (detail.get("campaign_targeting") or {}).get("keyword_targeting", {}).get("keywords", [])
    ) or (detail or {}).get("keywords", [])
    return {k["keyword"]: int(k["bids"][0].get("cpm", 0))
            for k in existing if k.get("keyword") and k.get("bids")}


async def read_bids(client, campaign_id: int) -> dict[str, int]:
    """Current CPM per keyword for a campaign (a READ — safe). {keyword: cpm}."""
    detail, _ = await client.get_campaign_detail(campaign_id)
    return bids_from_detail(detail or {})


def _api_match(match_type: str | None) -> str:
    """Our vocabulary → Blinkit's bid-range key. `apply_bid` sends BROAD as SMART, so the
    floor has to be looked up under the SAME name or a BROAD rule would be checked against
    the exact-match floor."""
    m = (match_type or "EXACT").upper().replace("_MATCH", "")
    return "SMART" if m == "BROAD" else m


def _our_match(api_match: str | None) -> str:
    """Blinkit's bid-range key → OUR vocabulary. The inverse of `_api_match`.

    `read_bid_floors` keys its result with this, so the returned dict speaks the same
    language as `cm_bid_rules.match_type` and the engine can look a floor up with a
    plain `floors.get((kw, rule.match_type))`.

    It used to key by Blinkit's names, which forced `bid.py` to call
    `adapter._api_match(...)` — the MP-agnostic engine reaching into a private function
    of one adapter. Zepto has no such function, so every Zepto bid run raised
    AttributeError. Translation belongs on the side that owns the vocabulary.
    """
    m = (api_match or "EXACT").upper().replace("_MATCH", "")
    return "BROAD" if m == "SMART" else m


async def read_bid_floors(client, campaign_id: int, detail: dict | None = None
                          ) -> dict[tuple[str, str], int]:
    """Blinkit's minimum bid per (keyword, match_type) for a campaign (a READ — safe).

    This is the authority the bid engine clamps to. It is read LIVE rather than from the
    nightly scrape because it is the number that decides what gets written to a real
    account: the scraped copy is for the UI, this is for the write.

    ONE request per campaign — the endpoint takes the whole keyword list — so a run costs
    +1 call per campaign regardless of how many keywords it manages. Pass an
    already-fetched `detail` to avoid re-reading it.

    Returns {} on any failure, which the caller must read as "no floor known" and fall back
    to the rule's own `min_bid`. Refusing to bid because a lookup failed would be worse
    than bidding at the configured minimum.
    """
    if detail is None:
        detail, _ = await client.get_campaign_detail(campaign_id)
    detail = detail or {}
    keywords = [k["keyword"] for k in (
        (detail.get("campaign_targeting") or {}).get("keyword_targeting", {}).get("keywords", [])
        or detail.get("keywords", []) or []
    ) if k.get("keyword")]
    if not keywords:
        return {}

    attrs = await client.get_keyword_attributes(
        campaign_id, detail.get("campaign_type") or "", keywords)
    floors: dict[tuple[str, str], int] = {}
    for a in attrs or []:
        kw = (a.get("keyword") or "").strip()
        for api_match, rng in (a.get("bid_range") or {}).items():
            if not isinstance(rng, dict) or rng.get("min") is None:
                continue
            floors[(kw, _our_match(api_match))] = int(rng["min"])
    return floors


async def read_products(client, campaign_id: int) -> list[dict]:
    """Campaign products (name + pid) — used to match the ad in live search (a READ)."""
    return await client.get_campaign_products(campaign_id)


async def read_position(client, keyword: str, lat: float, lon: float) -> list[dict]:
    """Live consumer-search positions for a keyword at a dark store (a READ — safe).
    Returns [{position, name, is_ad, pid}]. `client` is unused (separate browser)."""
    return await get_live_positions(keyword, lat=lat, lon=lon)


async def resolve_position(client, campaign_id: int, keyword: str, *, lat: float, lon: float,
                           product_names: list[str], product_pids: list[str],
                           brand_name: str | None) -> tuple[float | None, str]:
    """Live sponsored position for the campaign's product on `keyword` (a READ — safe).
    Scrapes consumer search, then matches this campaign's product by pid/name/brand.
    Returns (position | None, source). None = product not found / organic-only → skip.
    MP-specific matching lives in `positions.py`; the bid loop stays MP-agnostic.

    Self-contained (own browser) — for a one-off lookup. A run with several keywords uses
    `open_position_session` + `fetch_positions` + `locate_position` so one browser serves
    them all and identical (keyword, location) pairs are scraped once."""
    from campaign_manager.marketplaces.blinkit import positions
    return await positions.resolve(keyword, lat, lon, product_names=product_names,
                                   product_pids=product_pids, brand_name=brand_name)


# ── Batched position sourcing (one session per run) ─────────────────────────

async def open_position_session(pw, lat: float | None = None, lon: float | None = None) -> dict:
    """Open the consumer-side browser for a whole run and capture Blinkit's session-bound
    search headers. One warm-up (two navigations) serves every keyword AND every store in
    the run. The caller closes it with `close_position_session`."""
    from campaign_manager.marketplaces.blinkit import live_position
    kw = {k: v for k, v in (("lat", lat), ("lon", lon)) if v is not None}
    return await live_position.open_session(pw, **kw)


async def close_position_session(session: dict) -> None:
    from campaign_manager.marketplaces.blinkit import live_position
    await live_position.close_session(session)


async def fetch_positions(session: dict, keyword: str, lat: float, lon: float) -> list[dict]:
    """Raw search results for (keyword, store) on an open session — one API request, no
    page navigation. The store is selected by the lat/lon HEADERS, so a run spanning
    several stores costs no more than one at a single store.

    Raises when the search could not be performed, so the caller can tell "our ad isn't
    there" (empty list) from "we couldn't look" (error)."""
    from campaign_manager.marketplaces.blinkit import live_position
    return await live_position.search(session, keyword, lat, lon)


def locate_position(results: list[dict], keyword: str, lat: float, lon: float, *,
                    products: list[dict] | None = None, brand_name: str | None = None,
                    **_ignored) -> tuple[float | None, str]:
    """Match a campaign's product inside already-fetched results (pure, no I/O).

    Takes the raw `products` from `read_products` and pulls out what Blinkit's matcher
    needs. That extraction used to live in `bid.py`, which meant the MP-agnostic engine
    was reading Blinkit's field names — and on any other marketplace produced two empty
    lists, so nothing ever matched and the run reported "product not in results"
    forever, silently. Extraction belongs with the matcher that defines the shape.

    `campaign_id` / `match_type` are accepted and ignored: Blinkit's search results
    carry no per-slot campaign attribution, so matching is by product identity.
    """
    from campaign_manager.marketplaces.blinkit import positions
    products = products or []
    return positions.locate(
        results, keyword, lat, lon,
        product_names=[p.get("name", "") for p in products if p.get("name")],
        product_pids=[str(p["pid"]) for p in products if p.get("pid")],
        brand_name=brand_name,
    )


async def apply_bid(client, campaign_id: int, keyword: str, cpm: int,
                    match_type: str = "EXACT") -> dict:
    """Set a keyword's CPM bid. LIVE — only reached via writes.apply_bid.
    Sends the tenant's stored advertiser id (set on the client by arm_live)."""
    adv = getattr(client, "cm_advertiser_id", None)
    api_match = "SMART" if match_type == "BROAD" else match_type
    return await client.update_keyword_bids(
        campaign_id, [{"keyword": keyword, "match_type": api_match, "cpm": int(cpm)}],
        advertiser_id=adv,
    )


# ── Campaign activation — start / stop (docs/campaign-manager.md) ────────
#
# Blinkit's vocabulary stops here: everything above this layer speaks the canonical
# `running` / `paused` / `held` / `ended` / `draft`, so a second marketplace only has to
# supply its own mapping (AD9 of the design; D17 — no abstract base until MP #2).

_STATUS_FROM_BLINKIT = {
    "ACTIVE": "running",
    "STOPPED": "paused",        # user-stopped — resumable
    "ON_HOLD": "held",          # Blinkit-imposed — never ours to clear
    "COMPLETED": "ended",       # terminal
    "DRAFT": "draft",           # never launched
    # TRANSIENT, and it bit us in production on 2026-08-08: for a minute or two after a
    # RESTART, Blinkit reports the campaign as SCHEDULED before settling to ACTIVE. It is
    # live (or imminently so), not stopped — so it maps to `running`: we may set its budget
    # and we may stop it. Treating it as unknown made the engine skip a window-end stop and
    # leave the campaign spending. Too short-lived to appear in the scraped status table,
    # which is why the first five values looked like the whole vocabulary.
    "SCHEDULED": "running",
}


def _canonical(blinkit_status: str | None) -> str | None:
    """Blinkit's status → ours. An unmapped value returns as-is so the guardrail can
    refuse it by name rather than silently coercing it to something writable."""
    if not blinkit_status:
        return None
    return _STATUS_FROM_BLINKIT.get(blinkit_status.strip().upper(), blinkit_status)


async def list_campaigns(client, days: int = 90) -> list[dict]:
    """Every campaign on the account with its status, in ONE list call (a READ — safe).

    This is the cheap bulk read behind `cm sync-campaigns`: two requests total (enabled
    types, then the list) rather than a detail call per campaign, and no consumer-side
    scraping at all.

    It was long believed unusable — the call returned an empty list on Dobra — but the
    cause was `get_campaigns()` blindly asking for every campaign type: Blinkit rejects
    the whole request when any one of them is disabled for the advertiser (`"['BANNER_DIY',
    'SHELF_DIY', 'BRAND_SPOTLIGHT_DIY'] are not enabled for given advertiser"` → `data:
    null` → silently empty). The client now asks Blinkit which types are enabled first,
    the same fix the marketing scraper already carried.

    Raw Blinkit rows (`id`, `campaign_name`, `campaign_status`, …), not canonicalised —
    the caller stores them in the same shape the scraper does.
    """
    return await client.get_campaigns(days=days)


async def read_campaign(client, campaign_id: int) -> tuple[str | None, int | None, dict]:
    """(canonical status, current budget, full detail) in ONE call (a READ — safe).

    Campaign detail carries `status`, so status and budget come from the same request.
    Writes still read per-campaign like this rather than off `list_campaigns`: a write
    needs the campaign's full detail (pacing, targeting, products) anyway, and it must be
    read fresh at write time rather than from a list fetched earlier.

    `detail["allowed_transitions"]` is Blinkit's own answer to "what may I do to this
    campaign next" (a STOPPED campaign reports `['RESTART']`). Returned as part of the
    detail so callers can use it; we do not yet gate on it, because only the stopped-side
    vocabulary has been observed — see the doc's §2.3 note.
    """
    detail, _ = await client.get_campaign_detail(campaign_id)
    detail = detail or {}
    budget = detail.get("campaign_budget")
    return (_canonical(detail.get("status")),
            int(budget) if budget is not None else None,
            detail)


async def read_status(client, campaign_id: int) -> str | None:
    """One campaign's canonical status (a READ — safe). None when the detail carries no
    status — itself a refusal signal, never a reason to write blind."""
    status, _, _ = await read_campaign(client, campaign_id)
    return status


async def apply_status(client, campaign_id: int, target: str, *,
                       budget: float | None = None) -> dict:
    """Start or stop a campaign. LIVE — only reached via writes.apply_status.

    The two directions are NOT symmetric:

      - **paused** → `DELETE /adservice/v1/campaigns/{id}`. ⚠️ **This DELETE does not
        delete the campaign — it stops it.** Blinkit's own dashboard uses this exact call
        for its Stop button, and a stopped campaign is restartable afterwards (verified on
        574687, 2026-08-06). Do not "fix" this into something else.
      - **running** → a full campaign re-submission via `restart.build` (see that module).
        It rewrites budget, keywords, bids, pids and dates, so `budget` is required and the
        detail read below must be FRESH (AD9).
    """
    if target == "paused":
        return await client._fetch("DELETE", f"/adservice/v1/campaigns/{campaign_id}")

    if target != "running":
        raise ValueError(f"apply_status only writes running/paused, got {target!r}")
    if budget is None:
        raise ValueError("restarting a campaign requires a budget — Blinkit's RESTART "
                         "payload sets it, so there is no 'leave it alone' option")

    detail, _ = await client.get_campaign_detail(campaign_id)
    if not detail:
        raise RuntimeError(f"could not fetch details for campaign {campaign_id}")
    payload = restart.build(detail, campaign_id=campaign_id, budget=budget,
                            requested_by=client._email)
    # A restart rewrites the campaign whole, so it is the write with the largest blast
    # radius of the three. It is allowed to set the budget and the dates; everything else
    # must still match what we just read (payload.py).
    payload_check.verify(detail, payload, shape=payload_check.RESTART,
                         campaign_id=campaign_id)
    return await client._fetch("PUT", "/adservice/v3/campaigns", payload)


async def read_restart_context(client, campaign_id: int) -> dict:
    """What a restart would overwrite, for the AD9 audit line (a READ — safe)."""
    _, _, detail = await read_campaign(client, campaign_id)
    return detail


# ── Catalogue write-back (docs/campaign-manager.md §4) ───────────────────────
#
# A landed write changes Blinkit but NOT the tables the dashboard reads — those are
# filled by the nightly marketing scrape, so a budget set at 10:00 read back as
# yesterday's number until 03:00 the next morning. `writes.py` closes that by asking the
# adapter WHERE a write lands in the catalogue; this is that answer for Blinkit.
#
# It lives here, beside `_STATUS_FROM_BLINKIT` and `_api_match`, because both mappings it
# needs are Blinkit's own vocabulary and this module is where that vocabulary stops. The
# alternative — `writes.py` reaching for `adapter._api_match` — is a mistake already made
# once: it raised AttributeError on every Zepto bid run, because Zepto has no such
# function. An MP-agnostic caller must never know a marketplace's words.
#
# ⚠️ A marketplace with no `catalog_patch` gets NO write-back at all, silently and by
# design. That is how Zepto stays untouched today: not an `if platform == "blinkit"` in
# the choke point, but an absent attribute. When Zepto's turn comes it defines its own
# `catalog_patch`, adds its table names to `repo._catalog_model`, and nothing in
# `writes.py` or the engines changes.

# The inverse of `_STATUS_FROM_BLINKIT`, and deliberately NOT derived from it: that map is
# many-to-one (`ACTIVE` and the transient `SCHEDULED` both mean `running`), so inverting it
# programmatically would be ambiguous. Only the two states we ever WRITE appear here, which
# makes this exact — `writes.apply_status` refuses every other target.
_STATUS_TO_BLINKIT = {"running": "ACTIVE", "paused": "STOPPED"}

# Logical table names, resolved to models by `repo._catalog_model`. Strings rather than
# model classes because no adapter imports `app.models` — the marketplace layer talks to
# the marketplace, and the DB layer owns the schema.
CATALOG_CAMPAIGNS = "blinkit.campaigns"
CATALOG_KEYWORDS = "blinkit.keywords"


def catalog_patch(what: str, *, campaign_id: int, value, keyword: str | None = None,
                  match_type: str | None = None, budget: float | None = None) -> list[dict]:
    """Where a landed write lands in OUR catalogue — `[{table, key, set}, …]`.

    Pure: no I/O, no session, no marketplace call. It only translates a write we already
    made into the row and column that mirror it, so it is cheap enough to call inside the
    choke point and safe enough to unit-test without a DB.

    `what` is `"budget"` / `"status"` / `"bid"` — the three things `writes.py` can apply.
    Returns a LIST because one write can mirror into two columns: a Blinkit RESTART sets
    the budget as well as the status (its payload has no "leave the budget alone" option),
    so recording only the status would leave `daily_budget` stale after the one write that
    definitely changed it.

    An unknown `what` returns `[]` rather than raising. A new kind of write that nobody
    taught this function about should cost a stale column, not a failed run — the
    marketplace has already been mutated by the time this is called.
    """
    if what == "budget":
        return [{"table": CATALOG_CAMPAIGNS, "key": {"campaign_id": campaign_id},
                 "set": {"daily_budget": int(round(float(value)))}}]

    if what == "status":
        blinkit_status = _STATUS_TO_BLINKIT.get(value)
        if blinkit_status is None:
            return []
        patch = {"table": CATALOG_CAMPAIGNS, "key": {"campaign_id": campaign_id},
                 "set": {"status": blinkit_status}}
        # The restart's budget. Only on the way UP, and only when one was actually sent —
        # a stop is a bodiless DELETE that changes no budget at all.
        if value == "running" and budget is not None:
            patch["set"]["daily_budget"] = int(round(float(budget)))
        return [patch]

    if what == "bid":
        # `_api_match`, not the rule's own word: the scrape keys these rows by Blinkit's
        # vocabulary (`EXACT` / `SMART`), so a BROAD rule's bid belongs on the SMART row —
        # the same translation `apply_bid` applies on the way out. Keying by the rule's
        # word would silently patch nothing for every BROAD rule.
        return [{"table": CATALOG_KEYWORDS,
                 "key": {"campaign_id": campaign_id, "keyword": keyword,
                         "match_type": _api_match(match_type)},
                 "set": {"current_cpm": int(value)}}]

    return []


def campaign_name(detail: dict) -> str | None:
    """The campaign's name out of a raw detail. Blinkit calls it `name`."""
    return (detail or {}).get("name")


def resume_overwrites(detail: dict, budget: float | None) -> dict | None:
    """What a RESTART will silently rewrite (AD10) — logged before it happens, so a
    reverted bid is visible now rather than discovered weeks later."""
    return restart.overwrites(detail, budget=budget or 0)
