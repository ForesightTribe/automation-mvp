import { useState } from "react";
import { usePricePosition } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { DataTable } from "../../../components/ui/DataTable";
import { ViewToggle } from "../../../components/ui/ViewToggle";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCurrency, formatUnitPrice } from "../../../lib/format";

const KIND_OPTIONS = [
	{ value: "main", label: "Main" },
	{ value: "combo", label: "Combos" },
	{ value: "all", label: "All" },
];

const band = (lo, hi) => {
	if (lo == null && hi == null) return "—";
	return `${formatCurrency(lo)} – ${formatCurrency(hi)}`;
};

const perUnit = (value, uom) => formatUnitPrice(value, uom);

/**
 * Price positioning — per keyword, the own brand's price band vs the competitor
 * band, so you can see whether you're priced into or out of the consideration set.
 * Shows both the raw rupee band (absolute shelf price) and the per-unit band
 * (₹/100 ml · 100 g · piece), which compares fairly across pack sizes. A comparison
 * table (no chart): the numbers are the point.
 */
export const PricePositionCard = () => {
	const [kind, setKind] = useState("main");
	const { data, isLoading, error, refetch } = usePricePosition(kind);
	const rows = data?.rows ?? [];

	const columns = [
		{ key: "keyword", label: "Keyword" },
		{
			key: "own_avg_price",
			label: "Your avg",
			align: "right",
			render: (r) => formatCurrency(r.own_avg_price),
		},
		{
			key: "own_band",
			label: "Your range",
			align: "right",
			render: (r) => band(r.own_min_price, r.own_max_price),
		},
		{
			key: "comp_median_price",
			label: "Comp. median",
			align: "right",
			render: (r) => formatCurrency(r.comp_median_price),
		},
		{
			key: "comp_band",
			label: "Comp. range",
			align: "right",
			render: (r) => band(r.comp_min_price, r.comp_max_price),
		},
		{
			key: "own_avg_unit_price",
			label: "Your / unit",
			align: "right",
			render: (r) => perUnit(r.own_avg_unit_price, r.unit_uom),
		},
		{
			key: "comp_median_unit_price",
			label: "Comp. / unit",
			align: "right",
			render: (r) => perUnit(r.comp_median_unit_price, r.unit_uom),
		},
	];

	return (
		<Card
			title="Price positioning"
			actions={
				<ViewToggle
					options={KIND_OPTIONS}
					value={kind}
					onChange={setKind}
				/>
			}
		>
			{isLoading && <Loading label="Loading prices…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(rows.length === 0 ? (
					<EmptyState message="No priced listings in this window." />
				) : (
					<DataTable
						columns={columns}
						rows={rows}
						rowKey={(r) => r.keyword}
					/>
				))}
		</Card>
	);
};
