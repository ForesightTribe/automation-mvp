import { useAdsSummary, useAdsPerformance } from "./hooks";
import { KpiStrip } from "./components/KpiStrip";
import { AdMarketplaceBreakdown } from "./components/AdMarketplaceBreakdown";
import { SpendRevenueChart } from "./components/SpendRevenueChart";
import { BudgetSplitDonut } from "./components/BudgetSplitDonut";
import { ZeptoBudgetSplitDonut } from "./components/ZeptoBudgetSplitDonut";
import { CampaignsCard } from "./components/CampaignsCard";
import { KeywordsCard } from "./components/KeywordsCard";
import { ZeptoAssetPerformanceCard } from "./components/ZeptoAssetPerformanceCard";
import { SovTable } from "./components/SovTable";
import { ZeptoSovTable } from "./components/ZeptoSovTable";
import { VisibilityPlans, Collections } from "./components/SideLists";
import { Loading } from "../../components/feedback/Loading";
import { ErrorState } from "../../components/feedback/ErrorState";
import { useMarketplaces } from "../../context/MarketplaceContext";

export const AdsPage = () => {
	const { data: summary, isLoading, error, refetch } = useAdsSummary();
	const { data: performance } = useAdsPerformance();

	// The keyword tables are per-marketplace and cannot be merged: Blinkit's
	// rows are per campaign with a direct/indirect sales split, Zepto's are
	// brand-wide with neither. Rather than stack an empty card above a full
	// one, each is shown only when its marketplace is in scope. An empty
	// selection means "all marketplaces".
	const { selected } = useMarketplaces();
	const all = !selected?.length;
	const showBlinkit = all || selected.includes("blinkit");

	return (
		<div className="flex flex-col gap-6">
			<div>
				<h1 className="font-display text-xl font-bold text-content">Ads</h1>
				<p className="text-sm text-content-muted">Is my spend working.</p>
			</div>

			{isLoading && <Loading label="Loading ads…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading && !error && (
				<KpiStrip summary={summary} performance={performance ?? []} />
			)}

			<AdMarketplaceBreakdown />

			<div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
				<SpendRevenueChart />
				{showBlinkit && <BudgetSplitDonut />}
				<ZeptoBudgetSplitDonut />
			</div>

			<CampaignsCard />
			{showBlinkit && <KeywordsCard />}
			<ZeptoAssetPerformanceCard />

			<div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
				<div className="flex flex-col gap-6 lg:col-span-2">
					{showBlinkit && <SovTable />}
					<ZeptoSovTable />
				</div>
				{/* Blinkit-only ad products — Zepto's platform has no booked-
				    placement equivalent and no collection builder, so these
				    would be permanently empty for a Zepto-only client. */}
				{showBlinkit && (
					<div className="flex flex-col gap-6">
						<VisibilityPlans />
						<Collections />
					</div>
				)}
			</div>
		</div>
	);
};
