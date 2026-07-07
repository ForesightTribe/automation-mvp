import { useDistribution } from "../hooks";
import { MetricTile } from "../../../components/ui/MetricTile";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { formatNumber } from "../../../lib/format";

const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);
const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

/**
 * Headline availability KPIs, computed client-side from the distribution response:
 * average on-shelf distribution, SKUs tracked, SKUs with coverage gaps (< 100%),
 * and average discount. No growth badges — the public scrape has no prior-window
 * baseline yet (the availability trend below shows direction).
 */
export const InvKpis = ({ kind = "main" }) => {
	const { data, isLoading, error, refetch } = useDistribution(kind);

	if (isLoading) return <Loading label="Loading availability…" />;
	if (error) return <ErrorState message={error.message} onRetry={refetch} />;

	const skus = data?.skus ?? [];
	const avgDist = mean(skus.map((s) => s.distribution_pct));
	const withGaps = skus.filter((s) => s.distribution_pct < 100).length;
	const avgDisc = mean(
		skus.map((s) => s.avg_discount).filter((v) => v !== null && v !== undefined),
	);

	return (
		<div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
			<MetricTile label="Avg distribution" value={pct(avgDist)} />
			<MetricTile label="SKUs tracked" value={formatNumber(skus.length)} />
			<MetricTile label="SKUs with gaps" value={formatNumber(withGaps)} />
			<MetricTile label="Avg discount" value={pct(avgDisc)} />
		</div>
	);
};
