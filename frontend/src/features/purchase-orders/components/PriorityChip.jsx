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
	// Green because a slot is booked: the delivery is arranged and on its way,
	// which is the good end of an OPEN PO. Unscheduled is the amber one — live,
	// undelivered, and nobody has booked an appointment for it.
	Scheduled: "bg-success-soft text-success",
	Unscheduled: "bg-warning-soft text-warning",
	Fulfilled: "bg-success-soft text-success",
	Expired: "bg-muted text-content-muted",
	Cancelled: "bg-muted text-content-subtle",
};

export const StatusChip = ({ state }) => (
	<span
		className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ${
			STATE_TONE[state] ??
			(state?.startsWith("Cancel")
				? STATE_TONE.Cancelled
				: "bg-muted text-content-muted")
		}`}
	>
		<span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />
		{state ?? "—"}
	</span>
);
