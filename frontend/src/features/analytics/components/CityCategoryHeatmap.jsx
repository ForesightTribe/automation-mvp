import { useMemo } from "react";
import { useCityCategory } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { heatmapOption } from "../../../components/charts/options";
import { formatCompactCurrency } from "../../../lib/format";

/**
 * Shape the {city, category, revenue} cells into the heatmap's axis indices.
 * Cities are kept in first-seen order (the endpoint already returns top-by-revenue
 * first); categories are collected in encounter order. `max` caps the colour scale.
 */
const shape = (rows) => {
	const cities = [...new Set(rows.map((r) => r.city))];
	const cats = [...new Set(rows.map((r) => r.category))];
	const cityIdx = new Map(cities.map((c, i) => [c, i]));
	const catIdx = new Map(cats.map((c, i) => [c, i]));
	const byCity = new Map(cities.map((c) => [c, { city: c }]));
	let max = 0;
	const cells = rows.map((r) => {
		max = Math.max(max, r.revenue);
		byCity.get(r.city)[r.category] = r.revenue;
		return [catIdx.get(r.category), cityIdx.get(r.city), r.revenue];
	});
	return { cities, cats, cells, max, tableRows: cities.map((c) => byCity.get(c)) };
};

/** City × category revenue — heatmap, or the same matrix as a table. */
export const CityCategoryHeatmap = () => {
	const { data, isLoading, error, refetch } = useCityCategory(12);
	const rows = data ?? [];
	const { cities, cats, cells, max, tableRows } = useMemo(
		() => shape(data ?? []),
		[data],
	);
	const option = useMemo(
		() => heatmapOption(cities, cats, cells, max),
		[cities, cats, cells, max],
	);
	// One row per city → ~26px each, with headroom for axis + visualMap.
	const height = Math.max(280, cities.length * 26 + 120);

	const columns = [
		{ key: "city", label: "City" },
		...cats.map((c) => ({
			key: c,
			label: c,
			align: "right",
			render: (r) => formatCompactCurrency(r[c]),
		})),
	];

	return (
		<ChartTableCard
			title="City × category revenue"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No sales in this window."
			renderChart={() => <EChart option={option} height={height} />}
			columns={columns}
			rows={tableRows}
			rowKey={(r) => r.city}
		/>
	);
};
