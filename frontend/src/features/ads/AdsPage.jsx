import { useAdsSummary, useAdsPerformance } from "./hooks";
import { KpiStrip } from "./components/KpiStrip";
import { AdMarketplaceBreakdown } from "./components/AdMarketplaceBreakdown";
import { SpendRevenueChart } from "./components/SpendRevenueChart";
import { BudgetSplitDonut } from "./components/BudgetSplitDonut";
import { CampaignsCard } from "./components/CampaignsCard";
import { KeywordsCard } from "./components/KeywordsCard";
import { SovTable } from "./components/SovTable";
import { VisibilityPlans, Collections } from "./components/SideLists";
import { Loading } from "../../components/feedback/Loading";
import { ErrorState } from "../../components/feedback/ErrorState";

/**
 * Ads — "is my spend working". Composition root: lays out the sections and feeds
 * the KPI strip from `ads/summary` + `ads/performance` (the latter shared with the
 * trend chart, deduped by React Query). Every other section owns its own fetch.
 */
export const AdsPage = () => {
	const { data: summary, isLoading, error, refetch } = useAdsSummary();
	const { data: performance } = useAdsPerformance();

	return (
		<div className="flex flex-col gap-6">
			<div>
				<h1 className="font-display text-xl font-bold text-content">
					Ads
				</h1>
				<p className="text-sm text-content-muted">
					Is my spend working.
				</p>
			</div>

			{isLoading && <Loading label="Loading ads…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading && !error && (
				<KpiStrip summary={summary} performance={performance ?? []} />
			)}

			<AdMarketplaceBreakdown />

			<div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
				<SpendRevenueChart />
				<BudgetSplitDonut />
			</div>

			<CampaignsCard />
			<KeywordsCard />

			{/* SOV table beside the visibility plans + collections side rail. */}
			<div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
				<div className="lg:col-span-2">
					<SovTable />
				</div>
				<div className="flex flex-col gap-6">
					<VisibilityPlans />
					<Collections />
				</div>
			</div>
		</div>
	);
};
