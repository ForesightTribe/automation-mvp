/**
 * D19 lifecycle badge — active / paused / stopped. Colour maps to the status
 * theme tokens. Used on both budget schedules and bid rules.
 */
const STYLES = {
	active: "bg-success-soft text-success",
	paused: "bg-warning-soft text-warning",
	stopped: "bg-muted text-content-muted",
};

export const StateBadge = ({ state }) => (
	<span
		className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize ${
			STYLES[state] ?? STYLES.stopped
		}`}
	>
		{state}
	</span>
);
