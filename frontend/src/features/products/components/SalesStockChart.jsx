import { useMemo } from "react";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { salesStockOption } from "../../../components/charts/options";
import {
	formatCompactCurrency,
	formatDate,
	formatNumber,
} from "../../../lib/format";

const num = (v) => (v === null || v === undefined ? "—" : formatNumber(v));

const COLUMNS = [
	{ key: "date", label: "Date", render: (r) => formatDate(r.date) },
	{
		key: "units_sold",
		label: "Units",
		align: "right",
		render: (r) => num(r.units_sold),
	},
	{
		key: "revenue",
		label: "Revenue",
		align: "right",
		render: (r) =>
			r.revenue === null ? "—" : formatCompactCurrency(r.revenue),
	},
	{
		key: "frontend_qty",
		label: "FE stock",
		align: "right",
		render: (r) => num(r.frontend_qty),
	},
	{
		key: "backend_qty",
		label: "BE stock",
		align: "right",
		render: (r) => num(r.backend_qty),
	},
];

/** Align the sales trend and the stock trend on one date spine; a metric is null
 * on days its source has no row (honest gaps, not fake zeros). */
const mergeByDate = (trend, stockTrend) => {
	const map = new Map();
	for (const t of trend) {
		map.set(t.date, {
			date: t.date,
			units_sold: t.units_sold,
			revenue: t.revenue,
			frontend_qty: null,
			backend_qty: null,
		});
	}
	for (const s of stockTrend) {
		const e = map.get(s.date) ?? {
			date: s.date,
			units_sold: null,
			revenue: null,
		};
		e.frontend_qty = s.frontend_qty;
		e.backend_qty = s.backend_qty;
		map.set(s.date, e);
	}
	return [...map.values()].sort((a, b) => (a.date < b.date ? -1 : 1));
};

/** Units sold vs. frontend stock over time — the sell-through/stockout story. */
export const SalesStockChart = ({ detail }) => {
	const rows = useMemo(
		() => mergeByDate(detail?.trend ?? [], detail?.stock_trend ?? []),
		[detail],
	);
	const option = useMemo(() => salesStockOption(rows), [rows]);

	return (
		<ChartTableCard
			title="Sales & stock over time"
			isLoading={false}
			error={null}
			isEmpty={rows.length === 0}
			emptyMessage="No daily data in this window."
			renderChart={() => <EChart option={option} height={320} />}
			columns={COLUMNS}
			rows={rows}
			rowKey={(r) => r.date}
		/>
	);
};
