"""The adapter contract (D17).

An adapter exposes one marketplace's *mechanism*; `writes.py` owns the *policy*
(dry-run default, bounds, no-op suppression, rate limiting, audit) and calls into
an adapter only when a real mutation is due. That split is the whole point: policy
is written once and applies everywhere; mechanism is per-marketplace and may differ
wildly.

## Why this file exists NOW and not before

It was deliberately empty until a second marketplace landed. One implementation
produces an interface shaped like that implementation; two produce a seam. Zepto is
MP#2, so the contract below is written against **two real adapters**, not one and a
guess.

The encouraging result: the informal contract survived. `read_budget` /
`apply_budget` / `read_status` / `apply_status` / `read_bids` / `apply_bid` all map
cleanly onto Zepto even though its mechanism is completely different — Blinkit
issues targeted calls, Zepto must read the whole campaign, translate it, mutate one
field and PUT it back. The caller cannot tell, which is what an interface is for.

## This is a Protocol, not an ABC

Adapters are **modules**, not classes (docs/code-standards.md: functions, not
classes). A Protocol documents and type-checks that shape without forcing anyone to
inherit anything. Nothing imports this at runtime; it exists to be read and to be
checked.

## ⚠️ Cost is part of the contract

Two adapters can satisfy the same signature at wildly different cost, and a caller
that assumes otherwise will design the wrong loop. Each method below states its
real cost on both marketplaces. In particular:

- `apply_budget`/`apply_bid` on **Zepto** are read-modify-write on the WHOLE
  campaign. A malformed payload there can silently wipe geo targeting, the product
  list, or every other keyword's bid — a class of damage Blinkit's targeted writes
  cannot cause. Zepto's adapter therefore enforces its own invariant (re-read, then
  refuse unless the diff contains exactly the intended field). **That is mechanism,
  not policy** — it protects against a Zepto-specific hazard, so it lives in the
  Zepto adapter rather than in `writes.py`.
- Position lookup is a *session* on both, but Blinkit's costs a browser warm-up and
  a per-keyword search; Zepto's shape is still being determined.

## What is NOT in this contract

`setup()` returns `(playwright, browser, client)` — visibly Blinkit's shape. Zepto
needs no persistent browser and returns `(None, None, client)`; the engines already
guard `if browser is not None`, so this works today. It is left as-is deliberately:
churning Blinkit to introduce a `Client` handle with `aclose()` would be a real
refactor of working, tested code for a cosmetic gain. Revisit at MP#3 — if a third
marketplace also has no browser, the triple has outlived its usefulness.

Optional methods are marked. An adapter that does not implement one simply omits
it, and the engine that needs it is responsible for checking.
"""
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CampaignAdapter(Protocol):
    """The surface the engines actually call. Verified against the call sites."""

    # ── session lifecycle ────────────────────────────────────────────────────
    async def setup(self, tenant_id: str) -> tuple[Any, Any, Any]:
        """Return `(playwright, browser, client)` for a tenant.

        Blinkit: launches Chromium and restores the marketplace session into it.
        Zepto:   returns `(None, None, client)` — the client mints a short-lived
                 AWS WAF token with a headless browser that it closes immediately,
                 then talks plain HTTP.

        Raises `RuntimeError` when no usable session exists; every engine treats
        that as `logs.session_expired` and returns rather than crashing.
        """

    # ── reads (safe; no mutation) ────────────────────────────────────────────
    async def list_campaigns(self, client, days: int = 90) -> list[dict]:
        """The account's campaigns. ONE call on both marketplaces.

        ⚠️ `days` is a date window on both, and a narrow one hides campaigns the
        window excludes — which then age out of the catalogue. Callers should pass
        a generous window, not a tight one.
        """

    async def read_campaign(self, client, campaign_id: int) -> tuple[str | None, int | None, dict]:
        """`(name, budget, raw_detail)` for one campaign. One call."""

    async def read_budget(self, client, campaign_id: int) -> int | None:
        """Current daily budget, or None if unreadable."""

    async def read_status(self, client, campaign_id: int) -> str | None:
        """Canonical status — the vocabulary the engines compare against, NOT the
        marketplace's raw string. Adapters map their own vocabulary inward."""

    async def read_bids(self, client, campaign_id: int) -> dict[str, int]:
        """All keyword bids for a campaign.

        ⚠️ Keyed by keyword TEXT. Zepto bids the same keyword under several match
        types at different rates, so its adapter must not collapse them — a
        keyword's identity there is `(text, match_type)`.
        """

    async def read_products(self, client, campaign_id: int) -> list[dict]:
        """Products a campaign advertises, as `{pid, name}`.

        ⚠️ The SHAPE is part of the contract. The engine passes this straight to
        `locate_position` and never reads inside it — an adapter returning its own
        field names produces no match at all, silently, which reads as "our ad isn't
        there" rather than as a bug. Blinkit's `pid` is a product id; Zepto's is the
        `product_variant_id`, which is exactly what its consumer search reports back.
        """

    # ── writes (guarded; only reached via writes.py) ─────────────────────────
    async def apply_budget(self, client, campaign_id: int, budget: float) -> dict:
        """Set the daily budget.

        Blinkit: a targeted call.
        Zepto:   read → translate → verify no drift → mutate ONE field → PUT the
                 whole campaign. See the blast-radius note in this module's
                 docstring.
        """

    async def apply_bid(self, client, campaign_id: int, keyword: str, cpm: int,
                        match_type: str = ...) -> dict:
        """Set one keyword's bid. Sibling keywords MUST survive unchanged.

        ⚠️ The `cpm` name is Blinkit's; Zepto bids in CPC. The engines step it by
        PERCENTAGE, which is unit-agnostic — but the absolute floors
        (`BID_RAISE_MIN_STEP`, `BID_DRIFT_MIN_STEP`) are rupee values and need
        per-platform tuning: a floor sensible against a ₹200 CPM dominates a ₹16 CPC.
        """

    async def apply_status(self, client, campaign_id: int, target: str, *,
                           budget: float | None = None) -> dict:
        """Start or stop a campaign.

        Blinkit: `DELETE` means stop, and a restart re-submits the campaign AND
                 needs a budget — hence the `budget` argument.
        Zepto:   dedicated pause/activate endpoints; an idempotent flip that keeps
                 the prior budget and bids. `budget` is unused.
        """

    # ── account identity ─────────────────────────────────────────────────────
    def set_advertiser(self, client, advertiser_id: int) -> None:
        """Pin the ad account for this client's writes (B3).

        Blinkit exposes the advertiser id NOWHERE in its read APIs, so it must be
        stored and sent explicitly — a stale value writes to the wrong account with
        real money. Zepto returns its `brand_id` in the login response, so it is
        derivable; it is still asserted rather than trusted.
        """

    # ── position (OPTIONAL — bid optimisation only) ──────────────────────────
    async def open_position_session(self, pw, lat: float | None = None,
                                    lon: float | None = None) -> dict:
        """Open a reusable session for position lookups.

        Blinkit: one browser warm-up captures the session-bound headers its own
        search request carries; every keyword afterwards is a sub-second in-page
        fetch, with the store chosen by lat/lon HEADERS (no navigation).
        """

    async def fetch_positions(self, session: dict, keyword: str,
                              lat: float, lon: float) -> list[dict]:
        """Search results for one keyword at one store, ad-flagged."""

    def locate_position(self, results: list[dict], keyword: str,
                        lat: float, lon: float, *, products: list[dict],
                        campaign_id: Any, match_type: str,
                        brand_name: str | None) -> tuple[float | None, str]:
        """Find OUR sponsored slot in those results. Returns (position | None, reason).

        Every argument is passed unconditionally so the engine needs no
        per-marketplace branching; an adapter ignores what its marketplace does not
        expose, and should accept `**_ignored` so a later addition cannot break it.

        - **Blinkit** has no per-slot attribution, so it matches by product identity
          (pid, then name tokens, then brand) and ignores `campaign_id`/`match_type`.
        - **Zepto** stamps every sponsored row with a `uclId` naming the campaign,
          the campaign KEYWORD and the match type that won it, so it matches on
          (campaign, keyword, match_type) — campaign alone would credit one slot to
          every rule in a multi-keyword campaign.

        ⚠️ The failure mode to design against is silence, not error: a results
        source that cannot identify sponsored placements returns everything as
        organic, which reads as "nothing to do" and produces no bid decision, ever.
        Blinkit's DOM fallback was deleted for exactly this. An adapter that cannot
        positively identify our ad should say so in the reason string — and where it
        genuinely could not look, `fetch_positions` should raise instead.
        """

    async def close_position_session(self, session: dict) -> None:
        """Release whatever `open_position_session` acquired."""
