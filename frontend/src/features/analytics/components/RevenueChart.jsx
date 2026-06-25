import { useMemo, useState } from "react";
import { useRevenue } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { ViewToggle } from "../../../components/ui/ViewToggle";
import { dailyMetricOption } from "../../../components/charts/options";
import {
	formatCompactCurrency,
	formatDate,
	formatNumber,
} from "../../../lib/format";

const METRIC_OPTIONS = [
	{ value: "revenue", label: "Revenue" },
	{ value: "units", label: "Units" },
];

const COLUMNS = [
	{ key: "date", label: "Date", render: (r) => formatDate(r.date) },
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

/** Revenue or units per day (bars), switchable; table shows both columns. */
export const RevenueChart = () => {
	const { data, isLoading, error, refetch } = useRevenue();
	const rows = data ?? [];
	const [metric, setMetric] = useState("revenue");
	const option = useMemo(
		() => dailyMetricOption(data ?? [], { metric }),
		[data, metric],
	);

	return (
		<ChartTableCard
			title="Revenue & units over time"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No sales in this window."
			renderChart={() => <EChart option={option} height={320} />}
			columns={COLUMNS}
			rows={rows}
			rowKey={(r) => r.date}
			extraActions={
				<ViewToggle
					options={METRIC_OPTIONS}
					value={metric}
					onChange={setMetric}
				/>
			}
		/>
	);
};
