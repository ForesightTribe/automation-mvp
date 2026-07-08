/** Recommendation-queue status pill — mirrors ads/CampaignStatusBadge.jsx. */
const STYLES = {
	pending: { label: "Pending", cls: "bg-warning-soft text-warning" },
	approved: { label: "Approved", cls: "bg-info-soft text-info" },
	rejected: { label: "Rejected", cls: "bg-danger-soft text-danger" },
	completed: { label: "Completed", cls: "bg-success-soft text-success" },
};

export const ActionStatusBadge = ({ status }) => {
	const s = STYLES[status] ?? {
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
