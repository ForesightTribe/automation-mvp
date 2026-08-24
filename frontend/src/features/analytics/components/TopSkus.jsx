import { useMemo } from "react";
import { useTopSkus } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { rankedBarOption } from "../../../components/charts/options";
import { formatCurrency, formatNumber } from "../../../lib/format";

const COLUMNS = [
	{
		key: "item_name",
		label: "SKU",
		render: (r) => r.item_name || r.item_id,
	},
	{
		key: "revenue",
		label: "Revenue",
		align: "right",
		render: (r) => formatCurrency(r.revenue),
	},
	{
		key: "units_sold",
		label: "Units",
		align: "right",
		render: (r) => formatNumber(r.units_sold),
	},
];

/** Best-selling SKUs by revenue — ranked bars or a table. */
export const TopSkus = () => {
	const { data, isLoading, error, refetch } = useTopSkus(10);
	const rows = data ?? [];
	const option = useMemo(
		() =>
			rankedBarOption(
				(data ?? []).map((r) => ({
					label: r.item_name || r.item_id,
					value: r.revenue,
				})),
				{ color: "#4f46e5", money: true },
			),
		[data],
	);

	return (
		<ChartTableCard
			title="Top SKUs by revenue"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No sales in this window."
			renderChart={() => <EChart option={option} height={320} />}
			columns={COLUMNS}
			rows={rows}
			rowKey={(r) => r.item_id}
		/>
	);
};
