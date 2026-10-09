/**
 * How a `cm_run_log` row reads, shared by every surface that shows one: Ad Automation's
 * Execution logs, its campaign drawer and status summary, One-time Ops' Recent operations,
 * and the inline outcomes on both pages. One vocabulary, so the same row never reads two
 * ways — in lib/ rather than a feature because features may not import each other.
 */

export const KIND_LABEL = {
	budget: "Budget change",
	bid: "Bid change",
	activation: "Start / stop",
	// The engine's ad-wallet note (C12) — a warning with no campaign, written at most every
	// 6h while a prepaid wallet (Zepto) runs low. Never a write.
	wallet: "Ad wallet",
};

/**
 * What the row did, in a few words.
 *
 * The engine's `action` is a verb from its own vocabulary — drift, no-op, recover, open —
 * precise and meaningless to a reader. Every action any engine writes is listed, so a row
 * never falls through to showing the raw verb. The row's `reason` says why.
 */
const OUTCOME = {
	"budget:apply": "Budget changed",
	"budget:skip": "Budget not changed",
	"budget:no-op": "Budget already right",
	"budget:error": "Could not change the budget",
	"bid:apply": "Bid changed",
	"bid:drift": "Cost trimmed",
	"bid:recover": "Bid restored",
	"bid:open": "Window opened",
	"bid:reset": "Bid back to its floor",
	"bid:bounds": "Bid brought within limits",
	"bid:relax": "Target relaxed",
	"bid:no-op": "Rank held",
	// Two kinds of hold write this: waiting for the last change to show up in search, and
	// Zepto's out-of-stock rest (campaign_manager/rotation.py). "Bid held" is true of both;
	// the row's reason says which.
	"bid:hold": "Bid held",
	"bid:skip": "Bid not changed",
	"bid:error": "Could not check or change",
	"activation:apply": "Campaign started or stopped",
	"activation:skip": "Start / stop not applied",
	"activation:no-op": "Already in that state",
	"activation:error": "Could not start or stop",
	"wallet:warn": "Ad wallet running low",
	"wallet:error": "Ad wallet empty",
};

// Lifecycle rows (backend lifecycle.py) carry the same action whatever the kind.
const LIFECYCLE = {
	ended: "Automation ended",
	reopened: "Automation reopened",
	settled: "Automation wrapped up",
	"settle-failed": "Final reset did not land",
};

export const outcomeOf = (r) =>
	LIFECYCLE[r.action] ?? OUTCOME[`${r.kind}:${r.action}`] ?? r.action;

// Actions that are a write to the marketplace (backend repo._WRITE_ACTIONS).
const WRITES = new Set([
	"apply",
	"drift",
	"recover",
	"open",
	"reset",
	"bounds",
]);

/**
 * The row's result — five answers, where there used to be two.
 *
 * "Applied" in green used to cover every row with `success`, including skips and checks
 * that changed nothing; now a change, a correct non-change and a refusal each read as what
 * they are. Test mode first: a dry run never reaches the marketplace at all.
 */
export const resultOf = (r) => {
	if (r.dry_run) return { label: "Test mode", tone: "text-warning" };
	if (!r.success)
		return r.action === "error"
			? { label: "Error", tone: "text-danger" }
			: { label: "Not applied", tone: "text-danger" };
	if (WRITES.has(r.action)) return { label: "Applied", tone: "text-success" };
	return { label: "No change", tone: "text-content-subtle" };
};

/**
 * The position the engine saw, and the target it judged it against.
 *
 * Since the switch to AD SLOTS (2026-10, `measured_in: "ad_slot"`): `slot` is our ad slot —
 * the Nth sponsored listing — and `target` is an ad slot too; `at` is where our slot sat on
 * the page. `slot` null on such a row means our ad held no slot at all. `adSlots` says which
 * kind of row this is; `rankText` words either kind.
 *
 * From the row's own `position` / `target` columns. Rows written before those columns
 * existed (2026-09-04) only have them inside the reason's prose, so that is read as a
 * fallback and nowhere else. Blank means "not stated", never "position zero".
 */
export const rankOf = (row) => {
	if (row.kind !== "bid") return null;
	if (row.measured_in === "ad_slot")
		return {
			adSlots: true,
			slot: row.ad_slot ?? null,
			at: row.position != null ? Math.round(row.position) : null,
			target: row.target,
		};
	if (row.position != null || row.target != null)
		return {
			at: row.position != null ? Math.round(row.position) : null,
			target: row.target,
		};
	if (!row.reason) return null;
	const at = row.reason.match(/position (\d+)/i);
	const target = row.reason.match(/target (\d+)/i);
	if (!at && !target) return null;
	return { at: at?.[1] ?? null, target: target?.[1] ?? null };
};

/**
 * `rankOf` in words: `{ seen, target }`.
 *   ad-slot rows   seen "Ad #2 · pos 5" | "",  target "Ad #1"
 *   older rows     seen "#5" | "",             target "#1"
 * `seen` is blank when the row has no slot: our ad wasn't showing, or the row never searched
 * (a window opening, a bounds fix, a stock skip). The row's reason says which — the columns
 * cannot, so this does not guess.
 */
export const rankText = (rank) => {
	if (!rank) return null;
	if (rank.adSlots)
		return {
			seen:
				rank.slot != null
					? `Ad #${rank.slot}${rank.at != null ? ` · pos ${rank.at}` : ""}`
					: "",
			target: rank.target != null ? `Ad #${rank.target}` : "",
		};
	return {
		seen: rank.at != null ? `#${rank.at}` : "",
		target: rank.target != null ? `#${rank.target}` : "",
	};
};
