import { useState } from "react";
import { useFacilityPos } from "../hooks";
import { Pagination } from "../../../components/ui/Pagination";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCompactCurrency, formatDate, formatNumber } from "../../../lib/format";

/** The "fill loss → which POs" drill-down for one facility. Rendered inside an
 * expanded facilities-table row; fetches lazily (the hook is gated on `enabled`)
 * so POs only load when a row is opened. */
export const FacilityPos = ({ facilityId }) => {
	const [page, setPage] = useState(1);
	const { data, isLoading, error, refetch } = useFacilityPos(facilityId, {
		page,
		limit: 10,
		enabled: true,
	});
	const rows = data?.items ?? [];

	if (isLoading) return <Loading label="Loading POs…" />;
	if (error) return <ErrorState message={error.message} onRetry={refetch} />;
	if (rows.length === 0)
		return <EmptyState message="No POs found for this facility." />;

	return (
		<div>
			<table className="w-full border-collapse text-sm">
				<thead>
					<tr className="border-b border-border text-content-subtle">
						<th className="px-3 py-2 text-left font-medium">PO</th>
						<th className="px-3 py-2 text-left font-medium">State</th>
						<th className="px-3 py-2 text-left font-medium">Issued</th>
						<th className="px-3 py-2 text-right font-medium">Ordered</th>
						<th className="px-3 py-2 text-right font-medium">GRN</th>
						<th className="px-3 py-2 text-right font-medium">Value</th>
					</tr>
				</thead>
				<tbody>
					{rows.map((po) => (
						<tr
							key={po.po_number}
							className="border-b border-border/60 last:border-0"
						>
							<td className="px-3 py-2 font-medium text-content">
								{po.po_number}
							</td>
							<td className="px-3 py-2 text-content-muted">
								{po.po_state || "—"}
							</td>
							<td className="px-3 py-2 text-content-muted">
								{formatDate(po.issue_date)}
							</td>
							<td className="px-3 py-2 text-right tabular-nums text-content">
								{formatNumber(po.total_units_ordered)}
							</td>
							<td className="px-3 py-2 text-right tabular-nums text-content">
								{formatNumber(po.total_grn_quantity)}
							</td>
							<td className="px-3 py-2 text-right tabular-nums text-content">
								{formatCompactCurrency(po.total_po_amount)}
							</td>
						</tr>
					))}
				</tbody>
			</table>
			<Pagination
				page={data.page}
				pages={data.pages}
				total={data.total}
				limit={data.limit}
				onChange={setPage}
			/>
		</div>
	);
};
