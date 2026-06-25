import { useMemo } from "react";
import { useCategoryTrend } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { categoryTrendOption } from "../../../components/charts/options";
import { formatCompactCurrency, formatDate } from "../../../lib/format";

/**
 * Pivot the long {date, category, revenue} rows into a date spine + one series
 * per category (aligned to the spine, null on gap days) for the stacked area,
 * plus matching table rows ({ date, [category]: revenue }).
 */
const pivot = (rows) => {
	const dates = [...new Set(rows.map((r) => r.date))].sort();
	const cats = [...new Set(rows.map((r) => r.category))];
	const idx = new Map(dates.map((d, i) => [d, i]));
	const byCat = new Map(cats.map((c) => [c, Array(dates.length).fill(null)]));
	for (const r of rows) byCat.get(r.category)[idx.get(r.date)] = r.revenue;
	const series = cats.map((name) => ({ name, data: byCat.get(name) }));
	const tableRows = dates.map((d, i) => {
		const row = { date: d };
		for (const c of cats) row[c] = byCat.get(c)[i];
		return row;
	});
	return { dates, cats, series, tableRows };
};

/** Revenue per category over time — stacked area, or a date × category table. */
export const CategoryTrendChart = () => {
	const { data, isLoading, error, refetch } = useCategoryTrend();
	const rows = data ?? [];
	const { dates, cats, series, tableRows } = useMemo(
		() => pivot(data ?? []),
		[data],
	);
	const option = useMemo(
		() => categoryTrendOption(dates, series),
		[dates, series],
	);

	const columns = [
		{ key: "date", label: "Date", render: (r) => formatDate(r.date) },
		...cats.map((c) => ({
			key: c,
			label: c,
			align: "right",
			render: (r) => formatCompactCurrency(r[c]),
		})),
	];

	return (
		<ChartTableCard
			title="Category trend over time"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No sales in this window."
			renderChart={() => <EChart option={option} height={320} />}
			columns={columns}
			rows={tableRows}
			rowKey={(r) => r.date}
		/>
	);
};
