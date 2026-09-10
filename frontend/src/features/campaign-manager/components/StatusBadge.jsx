/**
 * Computed run-status badge — Running (window open now) / Scheduled (upcoming) / Ended
 * (a one-time window whose date passed) / Paused / Stopped. This is the API's derived
 * `status`, NOT the raw D19 `state` — so a spent one-time automation reads "Ended", not
 * a misleading "Active". A live "Running" pip pulses.
 */
const STYLES = {
	running: "bg-success-soft text-success",
	scheduled: "bg-info-soft text-info",
	ended: "bg-muted text-content-subtle",
	paused: "bg-warning-soft text-warning",
	stopped: "bg-muted text-content-muted",
};

const LABEL = {
	running: "Running",
	scheduled: "Scheduled",
	ended: "Ended",
	paused: "Paused",
	stopped: "Stopped",
};

export const StatusBadge = ({ status }) => (
	<span
		className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${
			STYLES[status] ?? STYLES.scheduled
		}`}
	>
		{status === "running" && (
			<span className="h-1.5 w-1.5 animate-pulse rounded-full bg-success" />
		)}
		{LABEL[status] ?? status}
	</span>
);
