import { useMemo } from "react";
import { useSalesByCity } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { rankedBarOption } from "../../../components/charts/options";
import { formatCompactCurrency, formatNumber } from "../../../lib/format";

/** The chart shows the top N; the table shows every city the endpoint returns. */
const TOP_N = 12;

const COLUMNS = [
	{ key: "city", label: "City" },
	{
		key: "revenue",
		label: "Revenue",
		align: "right",
		render: (r) => formatCompactCurrency(r.revenue),
	},
	{
		key: "units_sold",
		label: "Units",
		align: "right",
		render: (r) => formatNumber(r.units_sold),
	},
];

/** Revenue by city — top-N ranked bars, or the full city list as a table. */
export const CityBars = () => {
	const { data, isLoading, error, refetch } = useSalesByCity();
	const rows = data ?? [];
	const option = useMemo(
		() =>
			rankedBarOption(
				(data ?? []).slice(0, TOP_N).map((r) => ({
					label: r.city,
					value: r.revenue,
				})),
				{ color: "#0284c7", money: true },
			),
		[data],
	);

	return (
		<ChartTableCard
			title="Revenue by city"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No sales in this window."
			renderChart={() => <EChart option={option} height={320} />}
			columns={COLUMNS}
			rows={rows}
			rowKey={(r) => r.city}
		/>
	);
};
