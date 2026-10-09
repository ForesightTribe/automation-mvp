import { useMemo, useState } from "react";
import { useAdsPerformance } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { ViewToggle } from "../../../components/ui/ViewToggle";
import { adTrendOption } from "../../../components/charts/options";
import { formatCurrency, formatDate, formatNumber } from "../../../lib/format";

const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;

const ROAS_OPTIONS = [
	{ value: "off", label: "Hide RoAS" },
	{ value: "on", label: "Show RoAS" },
];

/**
 * Ad spend vs ad revenue over the window (the return-on-spend story), with an
 * optional RoAS line on a secondary axis. The Table view exposes the exact daily
 * numbers the chart smooths over.
 */
export const SpendRevenueChart = () => {
	const { data, isLoading, error, refetch } = useAdsPerformance();
	const [roas, setRoas] = useState("off");
	const rows = data ?? [];
	const option = useMemo(
		() => adTrendOption(data ?? [], { showRoas: roas === "on" }),
		[data, roas],
	);

	const columns = [
		{ key: "date", label: "Date", render: (r) => formatDate(r.date) },
		{
			key: "budget_consumed",
			label: "Spend",
			align: "right",
			render: (r) => formatCurrency(r.budget_consumed),
		},
		{
			key: "impressions",
			label: "Impressions",
			align: "right",
			render: (r) => formatNumber(r.impressions),
		},
		{
			key: "ad_sales",
			label: "Ad revenue",
			align: "right",
			render: (r) => formatCurrency(r.ad_sales),
		},
		{
			key: "roas",
			label: "RoAS",
			align: "right",
			render: (r) => formatRoas(r.roas),
		},
	];

	return (
		<ChartTableCard
			title="Spend vs revenue"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No ad data in this window."
			renderChart={() => <EChart option={option} height={300} />}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.date}
			extraActions={
				<ViewToggle
					options={ROAS_OPTIONS}
					value={roas}
					onChange={setRoas}
				/>
			}
		/>
	);
};
