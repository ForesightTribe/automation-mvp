import { describeOutcome, isActive, useRunOutcome } from "../../../lib/actions";

/**
 * One operation's state: live while it runs, then what it actually did.
 *
 * Rendered in two places from one component, so the row and the operations panel can never
 * report the same operation differently — `compact` for the table cell (short text, the full
 * sentence on hover), full for the panel (the sentence written out).
 *
 * ⚠️ A finished job is not the answer. `status: success` only means the process exited — the
 * CM commands never set a non-zero exit code, so a write the marketplace REFUSED settles exactly like
 * one it accepted. Once settled, the real outcome is read from the run's own history rows by
 * its `run_id`, and worded by `describeOutcome` (shared with Ad Automation).
 */
export const OperationStatus = ({ action, compact = false }) => {
	const done = Boolean(action) && action.status === "success";
	const { data: rows } = useRunOutcome(action?.run_id, done);

	if (!action) return null;

	if (isActive(action))
		return (
			<span
				className="inline-flex items-center gap-1.5 text-xs text-content-muted"
				title={action.label ?? undefined}
			>
				<span
					aria-hidden="true"
					className="h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-border border-t-brand"
				/>
				{action.status === "pending" ? "Queued" : "In progress"}
			</span>
		);

	// The job itself died — a crash, a timeout, an expired session. Distinct from a write the
	// platform refused, which settles as `success` and is reported from its history below.
	if (action.status === "failed")
		return (
			<span
				className="text-xs text-danger"
				title={action.error ?? undefined}
			>
				{compact || !action.error
					? "Failed"
					: `Failed — ${action.error}`}
			</span>
		);

	// A job that records nothing — a catalogue refresh writes the catalogue, not the run log —
	// so "it finished" is the whole truth available.
	if (!action.run_id)
		return <span className="text-xs text-success">Finished</span>;

	const outcome = describeOutcome(rows);
	// Settled, but the rows have not arrived. Nothing rather than a guess.
	if (!outcome)
		return <span className="text-xs text-content-muted">Checking…</span>;

	const tone = outcome.className;
	if (compact)
		return (
			<span
				className={`text-xs ${tone}`}
				title={outcome.detail ?? undefined}
			>
				{outcome.text}
			</span>
		);
	return (
		<span className={`text-xs ${tone}`}>
			{outcome.text}
			{outcome.detail && (
				<span className="text-content-muted"> — {outcome.detail}</span>
			)}
		</span>
	);
};
