/**
 * Campaign status pill — one vocabulary and one colour scale, everywhere a campaign
 * status is shown.
 *
 * STOPPED is red because a campaign that is not running is not spending. ON_HOLD is amber
 * rather than red because it is recoverable without a decision: Blinkit pauses delivery
 * when the daily budget runs out. COMPLETED and DRAFT are neutral — neither is a problem,
 * they are just not live. The pill always carries the WORD as well, so the colour is
 * emphasis rather than the only signal.
 *
 * Blinkit's strings vary in casing and spacing, so everything is normalised before
 * matching, and anything unrecognised falls back to a neutral chip carrying the raw
 * value — a new status must never break a table.
 */
const STYLES = {
	active: { label: "Active", cls: "bg-success-soft text-success" },
	running: { label: "Active", cls: "bg-success-soft text-success" },
	scheduled: { label: "Scheduled", cls: "bg-info-soft text-info" },
	stopped: { label: "Stopped", cls: "bg-danger-soft text-danger" },
	paused: { label: "Paused", cls: "bg-warning-soft text-warning" },
	on_hold: { label: "On hold", cls: "bg-warning-soft text-warning" },
	// "Completed" is Blinkit's word for a campaign that reached its end date. "Ended" is
	// what that is, and it sits beside "Stopped" without the two reading as synonyms.
	completed: { label: "Ended", cls: "bg-muted text-content-muted" },
	expired: { label: "Expired", cls: "bg-muted text-content-muted" },
	draft: { label: "Draft", cls: "bg-muted text-content-muted" },
	rejected: { label: "Rejected", cls: "bg-danger-soft text-danger" },
	under_review: { label: "Under review", cls: "bg-info-soft text-info" },
};

const norm = (status) =>
	(status ?? "").toLowerCase().trim().replace(/\s+/g, "_");

/** The display word for a status, for places that need the text without the pill. */
export const campaignStatusLabel = (status) => {
	const s = STYLES[norm(status)];
	if (s) return s.label;
	const raw = norm(status);
	return raw
		? raw.charAt(0).toUpperCase() + raw.slice(1).replace(/_/g, " ")
		: "—";
};

export const CampaignStatusBadge = ({ status }) => {
	const s = STYLES[norm(status)] ?? {
		label: campaignStatusLabel(status),
		cls: "bg-muted text-content-muted",
	};
	return (
		<span
			className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${s.cls}`}
		>
			{s.label}
		</span>
	);
};
