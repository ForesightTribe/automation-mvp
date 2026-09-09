import { useEffect, useRef } from "react";
import { useJob } from "../hooks";

/**
 * Live status of an enqueued job — the enqueue→poll UX. Polls until the job
 * terminates (via `useJob`'s self-stopping interval), then shows the outcome.
 * `onDone(status)` fires once when it finishes (e.g. to refresh history).
 */
const LABEL = {
	pending: "Queued…",
	running: "Running…",
	success: "Done ✓",
	failed: "Failed",
};

export const JobStatus = ({ jobId, onDone }) => {
	const { data: job } = useJob(jobId);
	const status = job?.status ?? "pending";
	const terminal = status === "success" || status === "failed";
	const fired = useRef(false);

	useEffect(() => {
		fired.current = false;
	}, [jobId]);

	useEffect(() => {
		if (terminal && !fired.current) {
			fired.current = true;
			onDone?.(status);
		}
	}, [terminal, status, onDone]);

	if (!jobId) return null;

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
			{status === "failed" && job?.error ? ` — ${job.error}` : ""}
		</span>
	);
};
