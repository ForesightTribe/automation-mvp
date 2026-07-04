import { useShareOfVoice } from "../hooks";
import { MetricTile } from "../../../components/ui/MetricTile";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";

const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);
const rank = (v) => (v === null || v === undefined ? "—" : `#${Number(v).toFixed(1)}`);

/**
 * Headline SoV KPIs for the own brand over the window: latest + average share of
 * voice and average rank. The share-of-voice summary carries no prior-window
 * value, so these tiles omit the growth badge (the trend chart below tells the
 * direction). Sparkline under each number reuses the SoV trend series.
 */
export const SovKpis = () => {
	const { data, isLoading, error, refetch } = useShareOfVoice();

	if (isLoading) return <Loading label="Loading share of voice…" />;
	if (error) return <ErrorState message={error.message} onRetry={refetch} />;

	const s = data?.summary ?? {};
	const sovSeries = (data?.trend ?? [])
		.map((p) => p.avg_sov)
		.filter((v) => v !== null && v !== undefined);

	return (
		<div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
			<MetricTile
				label="Latest SoV"
				value={pct(s.latest_sov)}
				series={sovSeries.length ? sovSeries : undefined}
			/>
			<MetricTile label="Avg SoV" value={pct(s.avg_sov)} />
			<MetricTile label="Avg rank" value={rank(s.avg_rank)} goodWhenDown />
		</div>
	);
};
