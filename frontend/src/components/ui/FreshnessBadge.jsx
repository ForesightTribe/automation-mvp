import { formatDate } from "../../lib/format";

/**
 * "Updated N days ago" chip for the public scrapes. They run weekly / on-demand,
 * so this makes the snapshot age explicit — a stale reading must never look live.
 * `at` is an ISO timestamp (a section's `as_of`); null renders nothing.
 */
const relative = (at) => {
	const then = new Date(at);
	if (Number.isNaN(then.getTime())) return null;
	const hours = (Date.now() - then.getTime()) / 3.6e6;
	if (hours < 1) return "just now";
	if (hours < 24) return `${Math.round(hours)}h ago`;
	return `${Math.round(hours / 24)}d ago`;
};

export const FreshnessBadge = ({ at }) => {
	if (!at) return null;
	const rel = relative(at);
	if (!rel) return null;
	return (
		<span
			className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/50 px-2.5 py-1 text-xs text-content-muted"
			title={`Public data scraped ${formatDate(at)}`}
		>
			<span className="h-1.5 w-1.5 rounded-full bg-success" />
			Updated {rel}
		</span>
	);
};
