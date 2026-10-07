import { useAdsSummary, useAdsPerformance } from "./hooks";
import { InsightsKpiStrip } from "./components/InsightsKpiStrip";
import { InsightsTrendChart } from "./components/InsightsTrendChart";
import { InsightsBudgetDonut } from "./components/InsightsBudgetDonut";
import { ZeptoBudgetSplitDonut } from "../ads/components/ZeptoBudgetSplitDonut";
import { InstamartBudgetSplitDonut } from "../ads/components/InstamartBudgetSplitDonut";
import { useState } from "react";
import { CampaignInsightsCard } from "./components/CampaignInsightsCard";
import { CampaignDrawer } from "./components/CampaignDrawer";
import { ZeptoAssetPerformanceCard } from "../ads/components/ZeptoAssetPerformanceCard";
import { InstamartAssetPerformanceCard } from "../ads/components/InstamartAssetPerformanceCard";
import { SovTable } from "../ads/components/SovTable";
import { ZeptoSovTable } from "../ads/components/ZeptoSovTable";
import { KeywordInsightsCard } from "./components/KeywordInsightsCard";
import { CategoryInsightsCard } from "./components/CategoryInsightsCard";
import { ExportButton } from "../../components/ui/ExportButton";
import { downloadCsv, exportName } from "../../lib/exportTable";
import { useDateRange } from "../../context/DateRangeContext";
import { Loading } from "../../components/feedback/Loading";
import { ErrorState } from "../../components/feedback/ErrorState";
import { useMarketplaces } from "../../context/MarketplaceContext";

/**
 * Insights: a second, independent view over the ads data.
 *
 * It starts as the Ads page's composition so nothing is lost on day one, and it is a
 * SEPARATE page so it can change without touching /ads, which is in production use. The
 * cards are imported from the Ads feature rather than copied: reusing them keeps the two
 * pages honest while they show the same thing, and anything Insights needs to render
 * differently gets its own component in ./components instead of an edit over there.
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
	["Campaigns that ran", "active_campaigns"],
];

export const InsightsPage = () => {
	const { data: summary, isLoading, error, refetch } = useAdsSummary();
	const { data: performance } = useAdsPerformance();

	// The keyword tables are per-marketplace and cannot be merged: Blinkit's rows are per
	// campaign with a direct/indirect sales split, Zepto's are brand-wide with neither.
	// Each is shown only when its marketplace is in scope.
	const [detailCampaign, setDetailCampaign] = useState(null);
	const { selected } = useMarketplaces();
	const { range } = useDateRange();
	const showBlinkit = selected.includes("blinkit");

	return (
		<div className="flex flex-col gap-6">
			<div className="flex items-start justify-between gap-4">
				<div>
					<h1 className="font-display text-2xl font-semibold tracking-tight text-content">
						Ads Insights
					</h1>
					<p className="text-sm text-content-muted">
						Where the ad spend went, and what it returned.
					</p>
				</div>
				{/* The headline numbers and the daily series, as one file. Each table below
				    carries its own download, because a single file of everything is a file
				    nobody opens. */}
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
													summary[key].delta_pct * 100
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
			</div>

			{isLoading && <Loading label="Loading insights…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading && !error && (
				<InsightsKpiStrip
					summary={summary}
					performance={performance ?? []}
				/>
			)}

			<div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
				<InsightsTrendChart />
				{showBlinkit && <InsightsBudgetDonut />}
				<ZeptoBudgetSplitDonut />
				<InstamartBudgetSplitDonut />
			</div>

			<CampaignInsightsCard onOpenCampaign={setDetailCampaign} />
			{showBlinkit && <KeywordInsightsCard />}
			<CategoryInsightsCard />
			<ZeptoAssetPerformanceCard />
			<InstamartAssetPerformanceCard />

			<div className="flex flex-col gap-6">
				{showBlinkit && <SovTable barClass="bg-brand" />}
				<ZeptoSovTable />
			</div>
			<CampaignDrawer
				open={detailCampaign != null}
				campaignId={detailCampaign}
				onClose={() => setDetailCampaign(null)}
			/>
		</div>
	);
};
