import { useOverview } from "./hooks";
import { KpiStrip } from "./components/KpiStrip";
import { Loading } from "../../components/feedback/Loading";
import { ErrorState } from "../../components/feedback/ErrorState";

/**
 * Overview — "what needs my attention today". Composition root: it lays out the
 * page's sections and feeds each one data from the feature hooks. This is the
 * reference pattern every other feature page follows.
 */
export const OverviewPage = () => {
	const { data, isLoading, error, refetch } = useOverview();

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
			{!isLoading && !error && <KpiStrip data={data} />}

			{/* TODO: Attention feed, revenue trend, freshness chips — see dashboard-views.md */}
		</div>
	);
};
