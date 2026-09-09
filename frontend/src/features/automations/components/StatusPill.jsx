/**
 * The API's computed `status` (running/scheduled/ended/paused/stopped) — not
 * the raw D19 `state` — so a spent one-time automation reads "Ended", not a
 * misleading "Active". Same vocabulary as Campaign Manager's own StatusBadge
 * (same backend field), kept as an independent component per this feature's
 * "don't depend on Campaign Manager" boundary.
 */
const DOT = {
	running: "bg-success",
	scheduled: "bg-info",
	ended: "bg-content-subtle",
	paused: "bg-warning",
	stopped: "bg-content-subtle",
};

// A tinted chip rather than bare text: a column of grey words reads as inert, and status
// is the one place this system does spend colour.
const TEXT = {
	running: "text-success bg-success-soft",
	scheduled: "text-info bg-info-soft",
	ended: "text-content-muted bg-muted",
	paused: "text-warning bg-warning-soft",
	stopped: "text-content-muted bg-muted",
};

const LABEL = {
	running: "Active",
	scheduled: "Scheduled",
	ended: "Ended",
	paused: "Paused",
	stopped: "Stopped",
};

export const StatusPill = ({ status }) => (
	<span
		className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold tracking-wide ${
			TEXT[status] ?? TEXT.scheduled
		}`}
	>
		<span
			className={`h-1.5 w-1.5 rounded-full ${DOT[status] ?? DOT.scheduled}`}
		/>
		{LABEL[status] ?? status}
	</span>
);
