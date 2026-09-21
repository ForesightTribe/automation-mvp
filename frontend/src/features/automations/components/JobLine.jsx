import { formatCurrency } from "../../../lib/format";
import { useJob, useRunOutcome } from "../hooks";

/**
 * What a job is doing, and then what it actually DID.
 *
 * ⚠️ Those are two different questions, and conflating them is the bug this component used
 * to have. `status: success` means the process exited cleanly — nothing more. The CM
 * commands return their counts and never set a non-zero exit code, so a write the
 * marketplace REFUSED settles exactly like one it accepted. This line therefore read
 * "Done ✓" while starting an ON_HOLD campaign, setting a budget below Blinkit's floor, or
 * tripping a rate limit — every case where nothing happened at all.
 *
 * So a settled job is not an answer, it is permission to go and look. The answer is the
 * engine's own account in the run log, found by the job's `run_id` — an id the queue mints
 * at enqueue and hands to the run, so the rows it wrote and the job that wrote them share
 * one key. Nothing here is inferred from timing or from which campaign we think we touched.
 */

/** Actions that mean the marketplace did NOT change. Everything else (apply, reset,
 *  bounds, drift, recover…) moved something. */
const NO_CHANGE = new Set(["skip", "hold", "no-op", "error"]);

const changed = (r) => r.success && !NO_CHANGE.has(r.action);

/** A row's own number, when it has one. Budgets and bids are both rupees; activation rows
 *  carry none and say what happened in `reason` instead. */
const withValue = (r) =>
	r.new_value != null ? ` · now ${formatCurrency(r.new_value)}` : "";

export const JobLine = ({ jobId }) => {
	const { data: job } = useJob(jobId);
	const status = job?.status ?? "pending";
	const settled = status === "success" || status === "failed";
	const { data: rows } = useRunOutcome(job?.run_id, settled);

	if (!jobId) return null;

	if (!settled)
		return (
			<span className="inline-flex items-center gap-2 text-xs text-content-muted">
				<span className="h-3 w-3 animate-spin rounded-full border-2 border-border border-t-primary" />
				{status === "running" ? "Applying…" : "Queued…"}
			</span>
		);

	if (status === "failed")
		return (
			<span className="text-xs text-danger">
				Failed{job?.error ? `: ${job.error}` : ""}
			</span>
		);

	// A job type that records nothing — a catalogue refresh reads Blinkit and writes only
	// the catalogue. "The run finished" is the whole truth available, so it is all we claim.
	if (!job?.run_id)
		return <span className="text-xs text-success">Run finished</span>;

	// Settled with a run to look up, but the rows have not arrived. Say nothing rather than
	// guess — guessing here is the exact bug this component exists to fix.
	if (!rows)
		return <span className="text-xs text-content-muted">Checking…</span>;

	// An EMPTY run is a real outcome, not a missing one: the engines deliberately write no
	// history row for a tick that changed nothing (docs D6), so this is the hourly poll
	// finding everything already correct.
	if (rows.length === 0)
		return (
			<span className="text-xs text-content-muted">
				Nothing needed changing
			</span>
		);

	// One row — a single-campaign action (Set budget, Start/Pause, Reset). Report it
	// exactly, including the engine's own sentence when it refused.
	if (rows.length === 1) {
		const r = rows[0];
		if (changed(r))
			return (
				<span className="text-xs text-success">
					Applied
					{withValue(r)}
				</span>
			);
		return (
			<span
				className="text-xs text-warning"
				title={r.reason ?? undefined}
			>
				{r.reason
					? `Nothing changed — ${r.reason}`
					: "Nothing changed — the platform did not accept this change."}
			</span>
		);
	}

	// Many rows — an engine run across several campaigns or keywords. Summarise rather than
	// pick one, and keep the failures visible: a run that changed 3 things and failed 2 is
	// not a success, and rounding it to one would hide the half that needs attention.
	const applied = rows.filter(changed).length;
	const failed = rows.filter((r) => !r.success).length;
	const tone = failed ? "text-warning" : "text-success";
	return (
		<span
			className={`text-xs ${tone}`}
			title={rows
				.map((r) =>
					[r.campaign_name, r.keyword, r.reason]
						.filter(Boolean)
						.join(" · "),
				)
				.join("\n")}
		>
			{`${applied} of ${rows.length} changed`}
			{failed ? ` · ${failed} failed` : ""}
		</span>
	);
};
