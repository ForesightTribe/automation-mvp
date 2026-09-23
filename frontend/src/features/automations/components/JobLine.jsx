import { describeOutcome, useRunOutcome } from "../../../lib/actions";
import { useJob } from "../hooks";

/**
 * What a job is doing, and then what it actually DID — for the wizard's campaign toggle.
 *
 * Rendered inside the wizard rather than on the page: the wizard is a full-screen overlay,
 * so anything on the page behind it cannot be seen while the toggle that caused it is open.
 *
 * ⚠️ Two different questions. `status: success` means the process exited cleanly, nothing
 * more — the CM commands never set a non-zero exit code, so a write the marketplace REFUSED
 * settles exactly like one it accepted. A settled job is permission to go and look; the
 * answer is the run's own rows, found by the job's `run_id`. The words for that answer come
 * from `describeOutcome`, shared with One-time Ops, so the two pages can never disagree
 * about what the same run did.
 */
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

	// A job type that records nothing — a catalogue refresh writes only the catalogue — so
	// "it finished" is the whole truth available.
	if (!job?.run_id)
		return <span className="text-xs text-success">Finished</span>;

	const outcome = describeOutcome(rows);
	// The rows have not arrived. Say nothing rather than guess — guessing is the bug this
	// component exists to fix.
	if (!outcome)
		return <span className="text-xs text-content-muted">Checking…</span>;

	return (
		<span
			className={`text-xs ${outcome.className}`}
			title={outcome.detail ?? undefined}
		>
			{outcome.detail && outcome.className !== "text-success"
				? `${outcome.text} — ${outcome.detail}`
				: outcome.text}
		</span>
	);
};
