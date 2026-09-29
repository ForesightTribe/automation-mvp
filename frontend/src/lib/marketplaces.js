/**
 * What differs between marketplaces on the ads action pages (Automations, One-time ops,
 * Ads Insights' actions), in one place. In `lib/` because those features must not import
 * each other.
 *
 * Only DISPLAY facts live here — words, units, which raw status means what. Rules the
 * engine enforces (floors, the minimum budget, which campaigns may be automated) come from
 * the API, never from a copy kept here, so the dashboard cannot drift from what the engine
 * will actually accept.
 */

/**
 * What a bid buys. The same ₹ figure is very different money: Blinkit prices per 1,000
 * impressions, Zepto per click. `bid-context` also returns the unit for a campaign; this is
 * for the surfaces that talk about bids before any campaign is chosen.
 */
const BID_UNIT = {
	blinkit: { code: "CPM", per: "per 1,000 views" },
	zepto: { code: "CPC", per: "per click" },
};

export const bidUnit = (mp) => BID_UNIT[mp] ?? { code: "bid", per: "" };

/**
 * Why a HELD campaign is held, in the reader's words, keyed on the marketplace's raw status.
 *
 * `held` (from `CampaignRow.state`) is the marketplace pausing delivery on its own — the
 * campaign is still live, so the control offers Stop, never Start. The two Zepto reasons
 * need different fixes, which is why the raw word is kept alongside the state.
 */
const HOLD_REASON = {
	ON_HOLD: (name) =>
		`Its budget is used up, so ${name} has paused delivery. Raise the campaign's budget to bring it back — there is nothing to restart.`,
	DAILY_BUDGET_EXHAUSTED: (name) =>
		`Today's budget is used up, so ${name} has paused delivery until tomorrow. Raise the budget to bring it back today — there is nothing to restart.`,
	INSUFFICIENT_WALLET_BALANCE: (name) =>
		`The ${name} ad wallet is empty, so delivery is paused. Top up the wallet on ${name} — there is nothing to restart.`,
};

export const holdReason = (status, name) =>
	HOLD_REASON[status]?.(name) ??
	`${name} has paused delivery on its own. The campaign is still live, so there is nothing to restart.`;

/** A marketplace's own name for display, from its slug, when no reference row is at hand. */
export const marketplaceName = (mp) =>
	mp ? mp.charAt(0).toUpperCase() + mp.slice(1) : "the marketplace";

/**
 * Whether a keyword rule may leave its city empty on this marketplace. On Zepto the API
 * then picks one of the campaign's OWN cities (a frozen one first, else the one with the
 * most stores — `repo.pick_rule_location`) and saves the rule by it. Blinkit has no such
 * pick: an empty city there measures at a default store nobody chose, so it stays required.
 */
export const autoPicksLocation = (mp) => mp === "zepto";

/**
 * Campaign state helpers, on `CampaignRow.state` (running / paused / held / ended / draft)
 * — never the raw status, whose words differ per marketplace. `held` is the marketplace
 * pausing delivery itself (budget used up, wallet empty): still LIVE, so it can be stopped
 * and its budget can be written, but there is nothing to start.
 */
export const isLiveState = (state) => state === "running" || state === "held";
export const isEndedState = (state) => state === "ended";

/**
 * Whether the marketplace accepts a budget write on a PAUSED campaign. Zepto does (verified
 * live on the test campaign, ZC-C11 — the adapter's `BUDGET_WHILE_PAUSED`); Blinkit refuses
 * one, so there a budget waits until the campaign is started. Mirrors the adapter flag for
 * the dialog's wording only: the engine re-checks against a fresh read either way.
 */
const BUDGET_WHILE_PAUSED = new Set(["zepto"]);

export const canWriteBudget = (mp, state) =>
	isLiveState(state) || (state === "paused" && BUDGET_WHILE_PAUSED.has(mp));
