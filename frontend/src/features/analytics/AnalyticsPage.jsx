import { useAnalyticsOverview, useAnalyticsTrends } from "./hooks";
import { KpiStrip } from "./components/KpiStrip";
import { RevenueChart } from "./components/RevenueChart";
import { TopSkus } from "./components/TopSkus";
import { CityBars } from "./components/CityBars";
import { CategoryDonut } from "./components/CategoryDonut";
import { CategoryTrendChart } from "./components/CategoryTrendChart";
import { CityCategoryHeatmap } from "./components/CityCategoryHeatmap";
import { Loading } from "../../components/feedback/Loading";
import { ErrorState } from "../../components/feedback/ErrorState";

/**
 * Sales & Analytics — "where is revenue coming from". Composition root: lays out
 * the sections and feeds each from the feature hooks. Sales-plane numbers with a
 * blended ad read up top, then the where/what cuts (over time, SKU, city,
 * category) and the deeper category-trend + city×category cross-tabs.
 */
export const AnalyticsPage = () => {
	const { data, isLoading, error, refetch } = useAnalyticsOverview();
	// Shared by the KPI sparklines (React Query dedupes the call).
	const { data: trends } = useAnalyticsTrends();

	return (
		<div className="flex flex-col gap-6">
			<div>
				<h1 className="font-display text-xl font-bold text-content">
					Sales & Analytics
				</h1>
				<p className="text-sm text-content-muted">
					Where is revenue coming from.
				</p>
			</div>

			{/* First-load spinner only; background refetches won't flip isLoading. */}
			{isLoading && <Loading label="Loading analytics…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading && !error && (
				<KpiStrip data={data} trends={trends ?? []} />
			)}

			{/* Revenue over time — full width. */}
			<RevenueChart />

			{/* Where + what: top SKUs, by city, by category. */}
			<div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
				<TopSkus />
				<CityBars />
			</div>
			<div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
				<CategoryDonut />
				<CategoryTrendChart />
			</div>

			{/* Deeper cut: city × category. */}
			<CityCategoryHeatmap />
		</div>
	);
};
