import { useMemo } from "react";
import { useSalesByCategory } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { donutOption } from "../../../components/charts/options";
import {
	formatCompactCurrency,
	formatNumber,
	formatPercent,
} from "../../../lib/format";

/** Revenue share by category — donut, or a table with each category's share. */
export const CategoryDonut = () => {
	const { data, isLoading, error, refetch } = useSalesByCategory();
	const rows = data ?? [];
	const total = useMemo(
		() => (data ?? []).reduce((s, r) => s + r.revenue, 0),
		[data],
	);
	const option = useMemo(
		() =>
			donutOption(
				(data ?? []).map((r) => ({ name: r.category, value: r.revenue })),
			),
		[data],
	);

	const columns = [
		{ key: "category", label: "Category" },
		{
			key: "revenue",
			label: "Revenue",
			align: "right",
			render: (r) => formatCompactCurrency(r.revenue),
		},
		{
			key: "share",
			label: "Share",
			align: "right",
			render: (r) => formatPercent(total ? r.revenue / total : null),
		},
		{
			key: "units_sold",
			label: "Units",
			align: "right",
			render: (r) => formatNumber(r.units_sold),
		},
	];

	return (
		<ChartTableCard
			title="Revenue by category"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No sales in this window."
			renderChart={() => <EChart option={option} height={320} />}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.category}
		/>
	);
};
