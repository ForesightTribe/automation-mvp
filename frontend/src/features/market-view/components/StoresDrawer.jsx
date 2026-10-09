import { useStoreExplorer } from "../hooks";
import { useMarketView } from "../viewContext";
import { Drawer } from "../../../components/ui/Drawer";
import { DataTable } from "../../../components/ui/DataTable";
import { Loading } from "../../../components/feedback/Loading";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { PresenceBar } from "./PresenceBar";
import { formatNumber } from "../../../lib/format";

const rank = (v) => (v == null ? "—" : `#${Number(v).toFixed(1)}`);

/**
 * Every dark store behind the numbers above — deliberately behind a click.
 *
 * Two thousand rows is a reference, not a reading: it belongs where someone
 * goes looking for it, not in the path of someone scanning the page.
 */
export const StoresDrawer = ({ open, onClose }) => {
	const { data, isLoading } = useStoreExplorer();
	const { keyword } = useMarketView();
	const rows = data?.rows ?? [];
	const absent = rows.filter((r) => r.own_avg_position == null).length;

	const columns = [
		{ key: "city", label: "City" },
		{ key: "locality", label: "Locality", render: (r) => r.locality || "—" },
		{ key: "pincode", label: "Pincode", render: (r) => r.pincode || "—" },
		{
			key: "own_avg_position",
			label: "Your rank",
			align: "right",
			render: (r) =>
				r.own_avg_position == null ? (
					<span className="font-medium text-danger">Absent</span>
				) : (
					rank(r.own_avg_position)
				),
		},
		{ key: "own_share_pct", label: "Share", render: (r) => <PresenceBar pct={r.own_share_pct} /> },
		{ key: "own_skus", label: "SKUs", align: "right", render: (r) => formatNumber(r.own_skus) },
		{
			key: "own_in_stock_pct",
			label: "In stock",
			align: "right",
			render: (r) => (r.own_in_stock_pct == null ? "—" : `${r.own_in_stock_pct}%`),
		},
		{
			key: "top_rival",
			label: "Top competitor",
			render: (r) => (r.top_rival ? `${r.top_rival} ${rank(r.top_rival_avg_position)}` : "—"),
		},
	];

	return (
		<Drawer
			open={open}
			onClose={onClose}
			title={keyword ? `Dark stores — “${keyword}”` : "Dark stores"}
			subtitle={
				rows.length
					? `${data.stores} measured${absent ? ` · ${absent} with none of your SKUs` : ""} · history from 18 Jul 2026`
					: undefined
			}
		>
			{isLoading ? (
				<Loading label="Loading stores…" />
			) : rows.length === 0 ? (
				<EmptyState message="No store-level results in this window." />
			) : (
				<DataTable
					columns={columns}
					rows={rows}
					rowKey={(r) => `${r.marketplace}-${r.store}`}
					maxHeight={620}
					minWidth={880}
				/>
			)}
		</Drawer>
	);
};
