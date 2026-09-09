import { useJob } from "../hooks";

const LABEL = {
	pending: "Queued…",
	running: "Running…",
	success: "Done ✓",
	failed: "Failed",
};

/** Enqueue→poll status for one job. Exported so every enqueueing action on the page
 * (reset, set-budget-now, refresh campaigns) reports progress the same way. */
export const JobLine = ({ jobId }) => {
	const { data: job } = useJob(jobId);
	if (!jobId) return null;
	const status = job?.status ?? "pending";
	const terminal = status === "success" || status === "failed";
	const tone =
		status === "success"
			? "text-success"
			: status === "failed"
				? "text-danger"
				: "text-content-muted";
	return (
		<span className={`inline-flex items-center gap-2 text-xs ${tone}`}>
			{!terminal && (
				<span className="h-3 w-3 animate-spin rounded-full border-2 border-border border-t-primary" />
			)}
			{LABEL[status]}
			{status === "failed" && job?.error ? `: ${job.error}` : ""}
		</span>
	);
};
