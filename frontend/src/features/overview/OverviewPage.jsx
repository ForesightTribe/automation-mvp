import { useOverview, useTrends } from "./hooks";
import { KpiStrip } from "./components/KpiStrip";
import { MarketplaceBreakdown } from "./components/MarketplaceBreakdown";
import { AdTrendChart } from "./components/AdTrendChart";
import { SalesTrendChart } from "./components/SalesTrendChart";
import { MonthlyTrendChart } from "./components/MonthlyTrendChart";
import { FreshnessChips } from "./components/FreshnessChips";
import { PublicShelfCard } from "./components/PublicShelfCard";
import { Loading } from "../../components/feedback/Loading";
import { ErrorState } from "../../components/feedback/ErrorState";

/**
 * Overview — "what needs my attention today". Composition root: it lays out the
 * page's sections and feeds each one data from the feature hooks. This is the
 * reference pattern every other feature page follows.
 */
export const OverviewPage = () => {
	const { data, isLoading, error, refetch } = useOverview();
	// Shared by the KPI sparklines and both charts (React Query dedupes the call).
	const { data: trends } = useTrends();

	return (
		<div className="flex flex-col gap-6">
			<div>
				<h1 className="font-display text-xl font-bold text-content">
					Overview
				</h1>
				<p className="text-sm text-content-muted">
					What needs your attention today.
				</p>
			</div>

			{/* First-load spinner only; background refetches won't flip isLoading. */}
			{isLoading && <Loading label="Loading overview…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading && !error && (
				<KpiStrip data={data} trends={trends ?? []} />
			)}

			{/* Per-marketplace breakdown owns its own fetch/loading state. */}
			<MarketplaceBreakdown />

			{/* Two trend charts side by side on wide screens. */}
			<div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
				<AdTrendChart />
				<SalesTrendChart />
			</div>

			{/* Operations — month-on-month (independent of the day-range picker).
			    All three read Blinkit seller tables, so on a Zepto-only client
			    they are permanently empty. Each says which source it is waiting
			    on rather than "No data yet", which reads as "a scrape is due". */}
			<div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
				<MonthlyTrendChart
					title="On-shelf availability (MoM)"
					seriesKey="osa_pct"
					label="OSA"
					color="#16a34a"
					type="bar"
					kind="percent"
					emptyMessage="Needs Blinkit stock-on-hand history. Zepto shelf data is on the Inventory page."
				/>
				<MonthlyTrendChart
					title="Fill rate (MoM)"
					seriesKey="fill_rate"
					label="Fill rate"
					color="#4f46e5"
					type="bar"
					kind="percent"
					emptyMessage="From the Blinkit seller scorecard. Not collected for Zepto."
				/>
				<MonthlyTrendChart
					title="PO value (MoM)"
					seriesKey="po_amount"
					label="PO value"
					color="#0284c7"
					type="bar"
					kind="currency"
					emptyMessage="From Blinkit purchase orders. Not collected for Zepto yet."
				/>
			</div>

			{/* Public shelf distribution + freshness across all scrapes. */}
			<div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
				<div className="lg:col-span-2">
					<PublicShelfCard />
				</div>
				<FreshnessChips />
			</div>
		</div>
	);
};
