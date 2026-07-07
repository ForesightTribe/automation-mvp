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

/** Current stock split across backend facilities (lowest frontend first). */
export const FacilityStock = ({ facilities = [] }) => (
	<Card title="Stock by facility">
		{facilities.length === 0 ? (
			<EmptyState message="No current stock snapshot for this SKU." />
		) : (
			<DataTable
				columns={COLUMNS}
				rows={facilities}
				rowKey={(r) => r.facility_id}
			/>
		)}
	</Card>
);
