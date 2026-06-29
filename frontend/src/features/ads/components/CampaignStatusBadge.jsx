/**
 * Campaign status pill. Blinkit's status strings vary in casing/spacing, so we
 * normalize (lowercase, spaces→underscores) before matching and fall back to a
 * neutral chip for anything unrecognised — the table never breaks on a new status.
 */
const STYLES = {
	active: { label: "Active", cls: "bg-success-soft text-success" },
	running: { label: "Active", cls: "bg-success-soft text-success" },
	paused: { label: "Paused", cls: "bg-warning-soft text-warning" },
	completed: { label: "Completed", cls: "bg-muted text-content-muted" },
	expired: { label: "Expired", cls: "bg-muted text-content-muted" },
	rejected: { label: "Rejected", cls: "bg-danger-soft text-danger" },
	draft: { label: "Draft", cls: "bg-muted text-content-muted" },
	scheduled: { label: "Scheduled", cls: "bg-info-soft text-info" },
	under_review: { label: "Under review", cls: "bg-info-soft text-info" },
};

const norm = (status) =>
	(status ?? "").toLowerCase().trim().replace(/\s+/g, "_");

export const CampaignStatusBadge = ({ status }) => {
	const s = STYLES[norm(status)] ?? {
		label: status ?? "—",
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
