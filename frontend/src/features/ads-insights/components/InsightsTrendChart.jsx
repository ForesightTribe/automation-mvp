import { useMemo, useState } from "react";
import {
	useAdsPerformance,
	usePreviousPerformance,
	usePreviousRange,
} from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { ViewToggle } from "../../../components/ui/ViewToggle";
import {
	insightsTrendByMarketplaceOption,
	insightsTrendOption,
} from "../chartOptions";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { chartColor } from "../../../lib/marketplaceColors";
import { marketplaceName } from "../../../lib/marketplace";
import { InfoTooltip } from "../../../components/ui/InfoTooltip";
import { DeltaStrip } from "./DeltaStrip";
import { formatCurrency, formatDate, formatNumber } from "../../../lib/format";

const formatRoas = (v) => (v == null ? "—" : `${v.toFixed(2)}x`);

const METRICS = [
	{ value: "money", label: "Spend & revenue" },
	{ value: "roas", label: "RoAS" },
];

const SPLITS = [
	{ value: "total", label: "All marketplaces" },
	{ value: "marketplace", label: "By marketplace" },
];

/**
 * Spend vs revenue over the window, with RoAS as its own view rather than a second axis.
 *
 * The Ads page draws RoAS on a secondary y-axis. Two scales in one plot make the crossings
 * meaningless: where the lines meet is an artefact of the axis ranges, not a fact about the
 * account. Money and a ratio are different quantities, so they get different views of the
 * same rows, and the toggle says which you are reading.
 */
export const InsightsTrendChart = () => {
	const { data, isLoading, error, refetch } = useAdsPerformance();
	const [metric, setMetric] = useState("money");
	// "By marketplace" splits the chart: daily spend stacked per marketplace, or a RoAS line
	// each. Offered only when more than one marketplace is in view.
	const [split, setSplit] = useState("total");
	const { selected } = useMarketplaces();
	const multi = selected.length > 1;
	const bySplit = multi && split === "marketplace";
	// Compared only once asked for: the previous window is a second request, and most
	// readings of this card never need it.
	const [compare, setCompare] = useState(false);
	const { data: prev } = usePreviousPerformance(compare);
	const prevRange = usePreviousRange();

	const rows = useMemo(() => data ?? [], [data]);
	const prevRows = useMemo(() => prev ?? [], [prev]);
	// The marketplaces present in the window, biggest spender first, each in its chart colour.
	const marketplaces = useMemo(() => {
		const spend = {};
		for (const r of rows)
			for (const [slug, s] of Object.entries(r.by_marketplace ?? {}))
				spend[slug] = (spend[slug] ?? 0) + (s.budget_consumed ?? 0);
		return Object.entries(spend)
			.filter(([, v]) => v > 0)
			.sort((a, b) => b[1] - a[1])
			.map(([slug]) => ({
				slug,
				name: marketplaceName(slug),
				color: chartColor(slug),
			}));
	}, [rows]);
	const option = useMemo(
		() =>
			bySplit
				? insightsTrendByMarketplaceOption(rows, {
						metric,
						marketplaces,
					})
				: insightsTrendOption(rows, {
						metric,
						previous: compare && prevRows.length ? prevRows : null,
					}),
		[rows, metric, compare, prevRows, bySplit, marketplaces],
	);

	const totals = (list) => {
		const spend = list.reduce((s, r) => s + (r.budget_consumed ?? 0), 0);
		const revenue = list.reduce((s, r) => s + (r.ad_sales ?? 0), 0);
		return { spend, revenue, roas: spend ? revenue / spend : null };
	};

	const columns = [
		{ key: "date", label: "Date", render: (r) => formatDate(r.date) },
		{
			key: "budget_consumed",
			label: "Spend",
			align: "right",
			render: (r) => formatCurrency(r.budget_consumed),
		},
		{
			key: "ad_sales",
			label: "Revenue",
			align: "right",
			render: (r) => formatCurrency(r.ad_sales),
		},
		{
			key: "roas",
			label: "RoAS",
			align: "right",
			render: (r) => formatRoas(r.roas),
		},
		{
			key: "impressions",
			label: "Impressions",
			align: "right",
			render: (r) => formatNumber(r.impressions),
		},
	];

	return (
		<ChartTableCard
			title={
				<span className="inline-flex items-center gap-1.5">
					{metric === "money"
						? "Spend and revenue"
						: "Return on ad spend"}
					<InfoTooltip
						label={
							metric === "money"
								? "Ad spend is what the marketplace billed for the ads in this window. Ad revenue is the sales it attributes to them. Both are daily totals from each marketplace's ads scrape, so the last day moves until that day's scrape lands."
								: "RoAS is ad revenue divided by ad spend for the day. 3x means three rupees back for every rupee spent. It is a ratio, so it is shown on its own scale rather than beside the money lines."
						}
					/>
				</span>
			}
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={!rows.length}
			renderChart={() => (
				<div className="flex flex-col gap-3">
					<EChart option={option} height={300} />
					{/* Below the chart, not in the header: it reveals what sits underneath, so it
					    belongs at the end of the thing it extends rather than above it. The
					    comparison overlays the totals, so the split view does not offer it. */}
					{!bySplit && (
						<button
							type="button"
							aria-expanded={compare}
							onClick={() => setCompare((v) => !v)}
							className="flex w-fit items-center gap-1 self-start rounded-md border border-border px-2.5 py-1 text-xs font-medium text-content-muted transition-colors hover:border-content-subtle hover:text-content"
						>
							{compare ? "Hide comparison" : "Show comparison"}
						</button>
					)}
					{compare && !bySplit && (
						<>
							<p className="text-xs text-content-subtle">
								Compared with {prevRange.from} to {prevRange.to}
								, the {prevRange.days} days before this window.
								Dashed lines are that period, aligned day for
								day.
							</p>
							<DeltaStrip
								now={totals(rows)}
								before={totals(prevRows)}
							/>
						</>
					)}
				</div>
			)}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.date}
			extraActions={
				<>
					{multi && (
						<ViewToggle
							options={SPLITS}
							value={split}
							onChange={setSplit}
						/>
					)}
					<ViewToggle
						options={METRICS}
						value={metric}
						onChange={setMetric}
					/>
				</>
			}
		/>
	);
};
