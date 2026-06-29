import { useMemo, useState } from "react";
import { useScorecardTrend } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { ViewToggle } from "../../../components/ui/ViewToggle";
import { scorecardTrendOption } from "../../../components/charts/options";
import { formatCompactCurrency, formatDate, formatNumber } from "../../../lib/format";

const METRIC_OPTIONS = [
	{ value: "fill_rate", label: "Fill rate" },
	{ value: "potential_loss", label: "Potential loss" },
	{ value: "total_gmv", label: "GMV" },
];

const formatPct = (v) =>
	v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`;

/**
 * Week-over-week scorecard trend. The chart shows one metric at a time (fill
 * rate / potential loss / GMV) toggled in the header; the Table view exposes
 * every weekly number the chart smooths over. Not week-scoped — it always shows
 * the last N weeks regardless of the selected week, for context.
 */
export const FillTrendChart = () => {
	const { data, isLoading, error, refetch } = useScorecardTrend(12);
	const [metric, setMetric] = useState("fill_rate");
	const rows = data ?? [];
	const option = useMemo(
		() => scorecardTrendOption(data ?? [], { metric }),
		[data, metric],
	);

	const columns = [
		{
			key: "from_date",
			label: "Week of",
			render: (r) => formatDate(r.from_date),
		},
		{
			key: "fill_rate",
			label: "Fill rate",
			align: "right",
			render: (r) => formatPct(r.fill_rate),
		},
		{
			key: "weighted_fill_rate_percent",
			label: "Weighted",
			align: "right",
			render: (r) => formatPct(r.weighted_fill_rate_percent),
		},
		{
			key: "potential_loss",
			label: "Potential loss",
			align: "right",
			render: (r) => formatCompactCurrency(r.potential_loss),
		},
		{
			key: "total_gmv",
			label: "GMV",
			align: "right",
			render: (r) => formatCompactCurrency(r.total_gmv),
		},
		{
			key: "manufacturer_rank",
			label: "Rank",
			align: "right",
			render: (r) => formatNumber(r.manufacturer_rank),
		},
	];

	return (
		<ChartTableCard
			title="Fill-rate trend"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No scorecard history yet."
			renderChart={() => <EChart option={option} height={300} />}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.from_date}
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
