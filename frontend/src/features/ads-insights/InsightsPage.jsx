import { useAdsSummary, useAdsPerformance } from "./hooks";
import { InsightsKpiStrip } from "./components/InsightsKpiStrip";
import { InsightsTrendChart } from "./components/InsightsTrendChart";
import { SpendSplitCard } from "./components/SpendSplitCard";
import { PerformanceExplorer } from "./components/explorer/PerformanceExplorer";
import { SovCard } from "./components/SovCard";
import { ExportButton } from "../../components/ui/ExportButton";
import { downloadCsv, exportName } from "../../lib/exportTable";
import { useDateRange } from "../../context/DateRangeContext";
import { Loading } from "../../components/feedback/Loading";
import { ErrorState } from "../../components/feedback/ErrorState";
import { PageHeader } from "../../components/ui/PageHeader";

/**
 * Ads Insights: where the ad spend went, and what it returned.
 *
 * One card per QUESTION, not per marketplace (2026-10-08, PLAN-ads-insights, designed in the
 * Insights lab): the KPI strip (each tile split by marketplace), the spend and revenue trend,
 * where the spend goes, the Performance explorer (campaigns, keywords, products, categories
 * and cities in one table) and share of voice. Every marketplace in view shares each card and
 * every row says whose it is; a card no marketplace in view can fill hides itself.
 */
// The tiles the summary download carries, in the order the strip shows them.
const SUMMARY_ROWS = [
	["Ad spend", "ad_spend"],
	["Ad revenue", "ad_sales"],
	["RoAS", "roas"],
	["ACoS", "acos"],
	["Impressions", "impressions"],
	["Add-to-carts", "atc"],
	["Units sold", "units_sold"],
	["Campaigns", "active_campaigns"],
];

export const InsightsPage = () => {
	const { data: summary, isLoading, error, refetch } = useAdsSummary();
	const { data: performance } = useAdsPerformance();
	const { range } = useDateRange();

	return (
		<div className="flex flex-col gap-6">
			{/* The headline numbers and the daily series, as one file. Each table
			    below carries its own download. */}
			<PageHeader
				title="Ads Insights"
				actions={
					<ExportButton
						label="Export summary"
						disabled={!summary}
						onExport={() =>
							downloadCsv(exportName("ads-insights", range), [
								{
									title: `Ads insights, ${range.from} to ${range.to}`,
									columns: [
										{
											header: "Metric",
											value: (r) => r.label,
										},
										{
											header: "This window",
											value: (r) => r.value,
										},
										{
											header: "Previous window",
											value: (r) => r.prev,
										},
										{
											header: "Change %",
											value: (r) => r.delta,
										},
									],
									rows: SUMMARY_ROWS.map(([label, key]) => ({
										label,
										value: summary?.[key]?.value ?? "",
										prev: summary?.[key]?.prev ?? "",
										// delta_pct is a FRACTION (0.066 = +6.6%), the same as the badge reads.
										delta:
											summary?.[key]?.delta_pct == null
												? ""
												: (
														summary[key].delta_pct *
														100
													).toFixed(1),
									})),
								},
								{
									title: "Daily performance",
									columns: [
										{
											header: "Date",
											value: (r) => r.date,
										},
										{
											header: "Ad spend",
											value: (r) => r.budget_consumed,
										},
										{
											header: "Ad sales",
											value: (r) => r.ad_sales,
										},
										{
											header: "Impressions",
											value: (r) => r.impressions,
										},
										{
											header: "RoAS",
											value: (r) => r.roas,
										},
									],
									rows: performance ?? [],
								},
							])
						}
					/>
				}
			/>

			{isLoading && <Loading label="Loading insights…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading && !error && (
				<InsightsKpiStrip
					summary={summary}
					performance={performance ?? []}
				/>
			)}

			<InsightsTrendChart />
			<SpendSplitCard />
			<PerformanceExplorer />
			<SovCard />
		</div>
	);
};
