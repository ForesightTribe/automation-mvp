import { useMemo } from "react";
import { useShareOfVoice } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { sovTrendOption } from "../../../components/charts/options";
import { formatDate, formatNumber } from "../../../lib/format";

const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);
const rank = (v) => (v === null || v === undefined ? "—" : `#${Number(v).toFixed(1)}`);

/**
 * Share-of-voice over the window (own brand). The public scrape is weekly, so each
 * point is roughly a weekly sample. Table view exposes the exact SoV, rank, and
 * sample count behind each point.
 */
export const SovTrendCard = () => {
	const { data, isLoading, error, refetch } = useShareOfVoice();
	const rows = data?.trend ?? [];
	const option = useMemo(() => sovTrendOption(data?.trend ?? []), [data]);

	const columns = [
		{ key: "date", label: "Date", render: (r) => formatDate(r.date) },
		{ key: "avg_sov", label: "SoV", align: "right", render: (r) => pct(r.avg_sov) },
		{ key: "avg_rank", label: "Avg rank", align: "right", render: (r) => rank(r.avg_rank) },
		{
			key: "samples",
			label: "Samples",
			align: "right",
			render: (r) => formatNumber(r.samples),
		},
	];

	return (
		<ChartTableCard
			title="Share of voice"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No public search data in this window."
			renderChart={() => <EChart option={option} height={300} />}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.date}
		/>
	);
};
