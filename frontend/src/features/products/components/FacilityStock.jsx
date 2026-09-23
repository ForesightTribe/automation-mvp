import { Card } from "../../../components/ui/Card";
import { DataTable } from "../../../components/ui/DataTable";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatNumber } from "../../../lib/format";
import { hasBackendStock } from "../../../lib/marketplace";

const FACILITY = {
	key: "facility_name",
	label: "Facility",
	render: (r) => r.facility_name || r.facility_id,
};

const FRONTEND = {
	key: "frontend_qty",
	label: "Frontend",
	align: "right",
	render: (r) => formatNumber(r.frontend_qty),
};

const BACKEND = {
	key: "backend_qty",
	label: "Backend",
	align: "right",
	render: (r) => formatNumber(r.backend_qty),
};

/**
 * Current stock split across facilities (lowest frontend first).
 *
 * Zepto reports one stock figure per SKU with no facility dimension, so an empty
 * table there means "not reported", not "no stock" — the SKU may well be fully
 * stocked. Saying "no snapshot" would read as missing data and send someone
 * looking for a scrape that never existed.
 *
 * Instamart HAS a facility dimension — the dark store — but no warehouse tier
 * behind it, so the Backend column is dropped rather than printed as a column
 * of zeros that reads as an empty back room. What is listed is only the stores
 * whose stock is actually known: Instamart reveals depth through the cart
 * limit, and where it gives only a per-order cap the store is left out instead
 * of being shown at zero.
 */
export const FacilityStock = ({ facilities = [], marketplace }) => {
	const columns = hasBackendStock(marketplace)
		? [FACILITY, FRONTEND, BACKEND]
		: [FACILITY, FRONTEND];

	const title =
		marketplace === "instamart" ? "Stock by store" : "Stock by facility";

	return (
		<Card title={title}>
			{facilities.length === 0 ? (
				<EmptyState
					message={
						marketplace === "zepto"
							? "Zepto reports stock per SKU, not split by facility."
							: marketplace === "instamart"
								? "No store-level stock known for this SKU yet — run the public inventory scrape."
								: "No current stock snapshot for this SKU."
					}
				/>
			) : (
				<DataTable
					columns={columns}
					rows={facilities}
					rowKey={(r) => r.facility_id}
					/* Two columns in a half-width card: the 640px default makes the
					   table scroll sideways and pushes the quantity out of view
					   entirely. Size the floor to the columns actually shown. */
					minWidth={columns.length > 2 ? 480 : 300}
				/>
			)}
		</Card>
	);
};
