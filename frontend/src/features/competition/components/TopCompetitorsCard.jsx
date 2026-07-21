import { useMemo } from "react";
import { useTopCompetitors } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { rankedBarOption } from "../../../components/charts/options";
import { formatCurrency, formatNumber } from "../../../lib/format";

const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);
const pos = (v) => (v === null || v === undefined ? "—" : `#${Number(v).toFixed(1)}`);

/**
 * Competitor leaderboard — who shows up in the most DARK STORES across the client's
 * searches. Chart ranks them by share of all (competitor, store) presences; the table
 * adds keyword spread, avg position, and avg price.
 *
 * "Stores" counts the store fulfilling each competitor's product, which is not
 * necessarily the store serving the coordinate — one response can span an express
 * store and a longtail hub. Rows scraped before 2026-07-18 carry no store id and are
 * excluded, so this card's window can be shorter than the SoV cards above, which stay
 * search-based. See docs/darkstores.md.
 */
export const TopCompetitorsCard = () => {
	const { data, isLoading, error, refetch } = useTopCompetitors();
	const rows = data?.competitors ?? [];

	const option = useMemo(
		() =>
			rankedBarOption(
				(data?.competitors ?? []).map((c) => ({
					label: c.competitor,
					value: c.share_pct,
				})),
				{ money: false },
			),
		[data],
	);

	const columns = [
		{ key: "competitor", label: "Competitor" },
		{ key: "share_pct", label: "Share of results", align: "right", render: (r) => pct(r.share_pct) },
		{
			key: "stores",
			label: "Stores",
			align: "right",
			render: (r) => formatNumber(r.stores),
		},
		{ key: "keywords", label: "Keywords", align: "right", render: (r) => formatNumber(r.keywords) },
		{ key: "avg_position", label: "Avg position", align: "right", render: (r) => pos(r.avg_position) },
		{
			key: "avg_price",
			label: "Avg price",
			align: "right",
			render: (r) => formatCurrency(r.avg_price),
		},
	];

	return (
		<ChartTableCard
			title="Who else shows up"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No competitor listings in this window."
			renderChart={() => <EChart option={option} height={Math.max(240, rows.length * 30)} />}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.competitor}
		/>
	);
};
