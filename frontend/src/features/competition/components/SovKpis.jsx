import { useShareOfVoice, useTopCompetitors } from "../hooks";
import { MetricTile } from "../../../components/ui/MetricTile";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { formatNumber } from "../../../lib/format";

const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);
const rank = (v) => (v === null || v === undefined ? "—" : `#${Number(v).toFixed(1)}`);

/**
 * Headline SoV KPIs for the own brand over the window: latest + average share of
 * voice, average rank, and how many competitors were seen. The summary carries no
 * prior-window value, so these tiles omit the growth badge (the trend below shows
 * direction). Sparkline under the first number reuses the SoV trend series.
 *
 * Each tile states what it is measured over. A share or an average rank means very
 * little without knowing whether it came from 12 searches or 60,000 — same rule the
 * Inventory KPIs follow.
 */
export const SovKpis = () => {
	const { data, isLoading, error, refetch } = useShareOfVoice();
	const { data: comp } = useTopCompetitors();

	if (isLoading) return <Loading label="Loading share of voice…" />;
	if (error) return <ErrorState message={error.message} onRetry={refetch} />;

	const s = data?.summary ?? {};
	const sovSeries = (data?.trend ?? [])
		.map((p) => p.avg_sov)
		.filter((v) => v !== null && v !== undefined);
	const searches = s.total_samples ?? 0;
	const rivals = (comp?.competitors ?? []).length;

	return (
		<div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
			<MetricTile
				label="Search share today"
				value={pct(s.latest_sov)}
				hint={
					data?.trend?.length
						? `on ${data.trend[data.trend.length - 1].date}`
						: undefined
				}
				series={sovSeries.length ? sovSeries : undefined}
			/>
			<MetricTile
				label="Avg search share"
				value={pct(s.avg_sov)}
				hint={`over ${formatNumber(searches)} searches`}
			/>
			<MetricTile
				label="Avg position"
				value={rank(s.avg_rank)}
				hint="where you appear in results"
				goodWhenDown
			/>
			<MetricTile
				label="Competitors"
				value={formatNumber(rivals)}
				hint="also showing up in your searches"
			/>
		</div>
	);
};
