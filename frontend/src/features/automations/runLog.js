/**
 * How a `cm_run_log` row reads, shared by every surface that shows one: the Execution
 * logs, the campaign drawer's recent activity, and the header's status summary. One
 * vocabulary, so the same row never reads three ways on one page.
 */

export const KIND_LABEL = {
	budget: "Budget change",
	bid: "Bid change",
	activation: "Start / stop",
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
	"bid:hold": "Waiting for the last change",
	"bid:skip": "Bid not changed",
	"bid:error": "Could not check or change",
	"activation:apply": "Campaign started or stopped",
	"activation:skip": "Start / stop not applied",
	"activation:no-op": "Already in that state",
	"activation:error": "Could not start or stop",
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
 * From the row's own `position` / `target` columns. Rows written before those columns
 * existed (2026-09-04) only have them inside the reason's prose, so that is read as a
 * fallback and nowhere else. Blank means "not stated", never "position zero".
 */
export const rankOf = (row) => {
	if (row.kind !== "bid") return null;
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
