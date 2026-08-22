import { useMemo, useState } from "react";
import { useSalesByCategory, useCityCategory } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { ViewToggle } from "../../../components/ui/ViewToggle";
import { stackedBarOption } from "../../../components/charts/options";
import {
	formatCurrency,
	formatNumber,
	formatPercent,
} from "../../../lib/format";

/** Bars (the ranked dimension) and coloured segments (the split dimension). */
const TOP_BARS = 10;
const TOP_STACKS = 6;
const OTHER = "Other";

const GROUP_OPTIONS = [
	{ value: "category", label: "By category" },
	{ value: "city", label: "By city" },
];

/**
 * Fold {city, category, revenue, units_sold} cells into a stacked-bar matrix.
 * `bar` names the ranked dimension, `stack` the one that splits each bar. Bars are
 * the top TOP_BARS by revenue, segments the top TOP_STACKS — everything past that
 * sums into "Other" rather than taking a new hue.
 *
 * `barTotals` (revenue + units keyed by bar) overrides each bar's total. It's used
 * in category grouping, where sales-by-category counts every city but the cells
 * only cover the top ones: the shortfall is real revenue, so it lands in "Other".
 */
const pivot = (cells, bar, stack, barTotals) => {
	const revenueBy = (key) => {
		const sums = new Map();
		for (const c of cells) sums.set(c[key], (sums.get(c[key]) ?? 0) + c.revenue);
		return sums;
	};

	const barRevenue = revenueBy(bar);
	if (barTotals) for (const [k, t] of barTotals) barRevenue.set(k, t.revenue);
	const ranked = (sums, n) =>
		[...sums.entries()]
			.sort((a, b) => b[1] - a[1])
			.slice(0, n)
			.map(([name]) => name);

	const bars = ranked(barRevenue, TOP_BARS);
	const topStacks = new Set(ranked(revenueBy(stack), TOP_STACKS));
	const kept = new Set(bars);

	// bar -> { [segment]: revenue }, plus each bar's covered revenue and units.
	const grid = new Map(bars.map((b) => [b, {}]));
	const covered = new Map(bars.map((b) => [b, 0]));
	const units = new Map(bars.map((b) => [b, 0]));
	for (const c of cells) {
		if (!kept.has(c[bar])) continue;
		const seg = topStacks.has(c[stack]) ? c[stack] : OTHER;
		const row = grid.get(c[bar]);
		row[seg] = (row[seg] ?? 0) + c.revenue;
		covered.set(c[bar], covered.get(c[bar]) + c.revenue);
		units.set(c[bar], units.get(c[bar]) + c.units_sold);
	}

	if (barTotals) {
		for (const b of bars) {
			const total = barTotals.get(b);
			if (!total) continue;
			units.set(b, total.units_sold);
			// Revenue from cities outside the top-12 cell set — honest, so keep it.
			const gap = total.revenue - covered.get(b);
			if (gap > 1) grid.get(b)[OTHER] = (grid.get(b)[OTHER] ?? 0) + gap;
		}
	}

	const totals = new Map(
		bars.map((b) => [
			b,
			Object.values(grid.get(b)).reduce((s, v) => s + v, 0),
		]),
	);
	// Only the segments that actually carry revenue become series ("Other" last).
	const segments = [...topStacks, OTHER].filter((s) =>
		bars.some((b) => grid.get(b)[s]),
	);

	return { bars, segments, grid, totals, units };
};

/**
 * Revenue by category and city in one card — the bar length is the category's
 * total revenue (what the donut used to say) and its segments are the cities that
 * make it up (what the city × category matrix used to say). The header toggle
 * flips which dimension ranks and which splits; the table view carries the exact
 * matrix, with a share-of-total column.
 */
export const CategoryCityCard = () => {
	const [group, setGroup] = useState("category");
	const byCategory = useSalesByCategory();
	const cityCategory = useCityCategory(12);

	const isLoading = byCategory.isLoading || cityCategory.isLoading;
	const error = byCategory.error || cityCategory.error;
	const refetch = () => {
		byCategory.refetch();
		cityCategory.refetch();
	};

	const cells = cityCategory.data ?? [];
	const byCategoryRows = byCategory.data ?? [];

	const { bars, segments, grid, totals, units } = useMemo(() => {
		const catTotals = new Map(byCategoryRows.map((r) => [r.category, r]));
		return group === "category"
			? pivot(cells, "category", "city", catTotals)
			: pivot(cells, "city", "category");
	}, [cells, byCategoryRows, group]);

	const grandTotal = useMemo(
		() => [...totals.values()].reduce((s, v) => s + v, 0),
		[totals],
	);

	const option = useMemo(
		() =>
			stackedBarOption(
				bars,
				segments.map((s) => ({
					name: s,
					data: bars.map((b) => grid.get(b)[s] ?? null),
				})),
				{ otherName: OTHER },
			),
		[bars, segments, grid],
	);

	const barLabel = group === "category" ? "Category" : "City";
	const columns = [
		{ key: "name", label: barLabel },
		{
			key: "total",
			label: "Revenue",
			align: "right",
			render: (r) => formatCurrency(r.total),
		},
		{
			key: "share",
			label: "Share",
			align: "right",
			render: (r) => formatPercent(grandTotal ? r.total / grandTotal : null),
		},
		{
			key: "units",
			label: "Units",
			align: "right",
			render: (r) => formatNumber(r.units),
		},
		...segments.map((s) => ({
			key: s,
			label: s,
			align: "right",
			render: (r) => formatCurrency(r[s]),
		})),
	];

	const rows = bars.map((b) => ({
		name: b,
		total: totals.get(b),
		units: units.get(b),
		...grid.get(b),
	}));

	// One bar per row → ~34px each, with headroom for the axis + legend.
	const height = Math.max(320, bars.length * 34 + 90);

	return (
		<ChartTableCard
			title="Revenue by category & city"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={bars.length === 0}
			emptyMessage="No sales in this window."
			renderChart={() => <EChart option={option} height={height} />}
			persistentActions={
				<ViewToggle
					options={GROUP_OPTIONS}
					value={group}
					onChange={setGroup}
				/>
			}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.name}
		/>
	);
};
