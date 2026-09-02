import { Card } from "../../../components/ui/Card";
import { DataTable } from "../../../components/ui/DataTable";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatNumber } from "../../../lib/format";

const COLUMNS = [
	{
		key: "facility_name",
		label: "Facility",
		render: (r) => r.facility_name || r.facility_id,
	},
	{
		key: "frontend_qty",
		label: "Frontend",
		align: "right",
		render: (r) => formatNumber(r.frontend_qty),
	},
	{
		key: "backend_qty",
		label: "Backend",
		align: "right",
		render: (r) => formatNumber(r.backend_qty),
	},
];

/**
 * Current stock split across backend facilities (lowest frontend first).
 *
 * Zepto reports one stock figure per SKU with no facility dimension, so an empty
 * table there means "not reported", not "no stock" — the SKU may well be fully
 * stocked. Saying "no snapshot" would read as missing data and send someone
 * looking for a scrape that never existed.
 */
export const FacilityStock = ({ facilities = [], marketplace }) => (
	<Card title="Stock by facility">
		{facilities.length === 0 ? (
			<EmptyState
				message={
					marketplace === "zepto"
						? "Zepto reports stock per SKU, not split by facility."
						: "No current stock snapshot for this SKU."
				}
			/>
		) : (
			<DataTable
				columns={COLUMNS}
				rows={facilities}
				rowKey={(r) => r.facility_id}
			/>
		)}
	</Card>
);
