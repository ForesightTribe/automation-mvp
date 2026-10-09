import { useMemo, useState } from "react";
import { useAdsPerformance } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { ViewToggle } from "../../../components/ui/ViewToggle";
import { MarketplaceLines } from "./MarketplaceLines";
import { chartColor } from "../../../lib/marketplaceColors";
import { marketplaceName } from "../../../lib/marketplace";
import { formatCurrency, formatDate, formatNumber } from "../../../lib/format";

const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;

/** Three separate views, never two y-scales on one chart. */
const METRICS = [
	{ value: "spend", label: "Spend" },
	{ value: "revenue", label: "Revenue" },
	{ value: "roas", label: "RoAS" },
];

/** RoAS is rebuilt from the day's bases, never averaged from daily ratios. */
const valueOf = (slice, metric) => {
	if (!slice) return null;
	if (metric === "spend") return slice.budget_consumed ?? 0;
	if (metric === "revenue") return slice.ad_sales ?? 0;
	return slice.budget_consumed ? slice.ad_sales / slice.budget_consumed : null;
};

/**
 * Spend, revenue and RoAS over the window, one line per marketplace. The channel
 * list starts with everything selected and filters by deselection.
 */
export const SpendRevenueChart = () => {
	const { data, isLoading, error, refetch } = useAdsPerformance();
	const [metric, setMetric] = useState("spend");
	const [dropped, setDropped] = useState([]);
	const rows = data ?? [];

	// Every marketplace that reported on any day in the window.
	const slugs = useMemo(() => {
		const seen = new Set();
		for (const r of rows) for (const s of Object.keys(r.by_marketplace ?? {})) seen.add(s);
		return [...seen].sort();
	}, [rows]);

	const selected = slugs.filter((s) => !dropped.includes(s));
	const toggle = (slug) =>
		setDropped((d) =>
			d.includes(slug) ? d.filter((x) => x !== slug) : [...d, slug],
		);

	const fmt = metric === "roas" ? formatRoas : formatCurrency;

	// Window totals per channel, for the list. RoAS from summed bases.
	const totals = useMemo(() => {
		const acc = {};
		for (const s of slugs) {
			let spend = 0, sales = 0;
			for (const r of rows) {
				const sl = r.by_marketplace?.[s];
				if (!sl) continue;
				spend += sl.budget_consumed ?? 0;
				sales += sl.ad_sales ?? 0;
			}
			acc[s] =
				metric === "spend" ? spend
				: metric === "revenue" ? sales
				: spend ? sales / spend : null;
		}
		return acc;
	}, [rows, slugs, metric]);

	const option = useMemo(
		() => ({
			tooltip: {
				trigger: "axis",
				valueFormatter: (v) => (v == null ? "—" : fmt(v)),
			},
			// No legend box: the channel list beside the chart is the legend.
			grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
			xAxis: {
				type: "category",
				boundaryGap: false,
				data: rows.map((r) => formatDate(r.date)),
			},
			yAxis: {
				type: "value",
				splitLine: { lineStyle: { opacity: 0.25 } },
			},
			series: selected.map((slug) => ({
				name: marketplaceName(slug),
				type: "line",
				smooth: true,
				showSymbol: false,
				lineStyle: { width: 2 },
				itemStyle: { color: chartColor(slug) },
				// A day a channel did not report is a gap, not a zero.
				connectNulls: false,
				data: rows.map((r) => valueOf(r.by_marketplace?.[slug], metric)),
			})),
		}),
		// eslint-disable-next-line react-hooks/exhaustive-deps
		[rows, selected.join(","), metric],
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
		{ key: "roas", label: "RoAS", align: "right", render: (r) => formatRoas(r.roas) },
	];

	return (
		<ChartTableCard
			title="Spend and Revenue"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No ad data in this window."
			renderChart={() => (
				<div className="flex flex-col gap-4 lg:flex-row lg:items-start">
					<MarketplaceLines
						slugs={slugs}
						selected={selected}
						onToggle={toggle}
						totals={totals}
						format={fmt}
					/>
					<div className="min-w-0 flex-1">
						<EChart option={option} height={300} />
					</div>
				</div>
			)}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.date}
			extraActions={
				<ViewToggle options={METRICS} value={metric} onChange={setMetric} />
			}
		/>
	);
};
