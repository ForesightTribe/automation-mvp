import { Button } from "./Button";
import { formatNumber } from "../../lib/format";

/**
 * Page navigator for server-paginated tables. Reads the `{ page, pages, total,
 * limit }` envelope the API returns (see schemas.common.Page) and emits the next
 * page number via `onChange`. Renders nothing when there's no data; the prev/next
 * buttons disable at the ends. Reused across products/inventory/competition.
 */
export const Pagination = ({ page, pages, total, limit, onChange }) => {
	if (!total) return null;
	const from = (page - 1) * limit + 1;
	const to = Math.min(page * limit, total);
	return (
		<div className="mt-3 flex items-center justify-between text-xs text-content-muted">
			<span>
				{from}–{to} of {formatNumber(total)}
			</span>
			<div className="flex items-center gap-2">
				<Button
					variant="secondary"
					size="sm"
					disabled={page <= 1}
					onClick={() => onChange(page - 1)}
				>
					Prev
				</Button>
				<span className="tabular-nums">
					Page {page} of {pages}
				</span>
				<Button
					variant="secondary"
					size="sm"
					disabled={page >= pages}
					onClick={() => onChange(page + 1)}
				>
					Next
				</Button>
			</div>
		</div>
	);
};
