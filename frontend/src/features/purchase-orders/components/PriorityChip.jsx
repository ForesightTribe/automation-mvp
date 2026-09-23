/**
 * How much money is riding on a PO — high (₹50k+ undelivered and still open), medium,
 * or low. A settled PO never reads high: nothing can be done about it now.
 */
const TONE = {
	high: "bg-danger-soft text-danger",
	medium: "bg-warning-soft text-warning",
	low: "bg-muted text-content-muted",
};

export const PriorityChip = ({ priority }) => (
	<span
		className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${TONE[priority] ?? TONE.low}`}
	>
		<span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />
		{priority}
	</span>
);

/** The marketplace's own word for where the PO stands. */
const STATE_TONE = {
	Scheduled: "bg-info-soft text-info",
	Unscheduled: "bg-warning-soft text-warning",
	Fulfilled: "bg-success-soft text-success",
	Expired: "bg-muted text-content-muted",
	Cancelled: "bg-muted text-content-subtle",
};

export const StatusChip = ({ state }) => (
	<span
		className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ${
			STATE_TONE[state] ?? "bg-muted text-content-muted"
		}`}
	>
		<span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />
		{state ?? "—"}
	</span>
);
