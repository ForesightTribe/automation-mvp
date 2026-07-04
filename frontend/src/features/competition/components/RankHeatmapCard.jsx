import { useMemo } from "react";
import { useRankMatrix } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { rankHeatmapOption } from "../../../components/charts/options";

const MAX_CITIES = 25; // cap the heatmap; the table view carries every city

const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);
const rankLabel = (v) => (v === null || v === undefined ? "—" : `#${Number(v).toFixed(1)}`);
const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : Infinity);

/**
 * Rank heatmap — own-brand rank per (keyword × city). Keywords are columns (there
 * are few); cities are rows (there are many), so the chart shows the WEAKEST cities
 * first (highest avg rank) capped at MAX_CITIES, and the Table view lists every
 * (keyword, city) cell. This is the "where am I weak?" view.
 */
export const RankHeatmapCard = () => {
	const { data, isLoading, error, refetch } = useRankMatrix();
	const cells = data?.cells ?? [];

	const { option, height } = useMemo(() => {
		const keywords = data?.keywords ?? [];
		const cells = data?.cells ?? [];
		if (!cells.length) return { option: {}, height: 320 };

		// Rank each city by its average rank across keywords (weakest = highest).
		const byCity = {};
		cells.forEach((c) => {
			if (c.avg_rank != null) (byCity[c.city] ??= []).push(c.avg_rank);
		});
		const weakest = Object.entries(byCity)
			.map(([city, rs]) => ({ city, m: mean(rs) }))
			.sort((a, b) => b.m - a.m)
			.slice(0, MAX_CITIES)
			.map((c) => c.city);

		// ECharts y-axis draws index 0 at the bottom, so reverse to put the
		// weakest city at the top of the chart.
		const cityAxis = [...weakest].reverse();
		const xIdx = Object.fromEntries(keywords.map((k, i) => [k, i]));
		const yIdx = Object.fromEntries(cityAxis.map((c, i) => [c, i]));

		const lookup = {};
		cells.forEach((c) => {
			lookup[`${c.keyword}||${c.city}`] = c;
		});
		const points = [];
		cityAxis.forEach((city) =>
			keywords.forEach((kw) => {
				const cell = lookup[`${kw}||${city}`];
				if (cell && cell.avg_rank != null)
					points.push({
						value: [xIdx[kw], yIdx[city], Math.round(cell.avg_rank * 10) / 10],
						sov: cell.avg_sov,
					});
			}),
		);
		const maxRank = Math.max(12, ...points.map((p) => p.value[2]));
		return {
			option: rankHeatmapOption(keywords, cityAxis, points, maxRank),
			height: Math.max(320, cityAxis.length * 24 + 90),
		};
	}, [data]);

	// Table: every cell, weakest first.
	const rows = useMemo(
		() =>
			[...(data?.cells ?? [])].sort(
				(a, b) => (b.avg_rank ?? -1) - (a.avg_rank ?? -1),
			),
		[data],
	);
	const columns = [
		{ key: "city", label: "City" },
		{ key: "keyword", label: "Keyword" },
		{ key: "avg_rank", label: "Avg rank", align: "right", render: (r) => rankLabel(r.avg_rank) },
		{ key: "avg_sov", label: "SoV", align: "right", render: (r) => pct(r.avg_sov) },
	];

	return (
		<ChartTableCard
			title="Rank by keyword × city"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={cells.length === 0}
			emptyMessage="No public search data in this window."
			renderChart={() => (
				<div>
					<EChart option={option} height={height} />
					<p className="mt-2 text-xs text-content-subtle">
						Weakest {Math.min(MAX_CITIES, rows.length ? new Set(cells.map((c) => c.city)).size : 0)} cities shown
						(darker = weaker). Full grid in the Table view.
					</p>
				</div>
			)}
			columns={columns}
			rows={rows}
			rowKey={(r) => `${r.city}|${r.keyword}`}
			tableMaxHeight={480}
		/>
	);
};
