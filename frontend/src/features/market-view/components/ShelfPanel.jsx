import { useMemo } from "react";
import { useBrandComparison } from "../hooks";
import { useMarketView } from "../viewContext";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { formatCurrency, formatNumber } from "../../../lib/format";

const pct = (v) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);
const rank = (v) => (v == null ? "—" : `#${Number(v).toFixed(1)}`);
const BASIS = { ml: "/100ml", g: "/100g", pc: "/pc" };

/**
 * Price against rank, every brand on one shelf — the page's centrepiece.
 *
 * A scatter rather than two bar charts: the question is whether the brands
 * beating you are cheaper than you, and that is a relationship between two
 * numbers, not two rankings. Cheap-and-winning sits bottom-left, and anything
 * up and to the right of you is losing on both.
 *
 * Rank runs DOWNWARD on the y axis so "higher on the chart" means "higher on
 * the shelf", which is the opposite of what the raw number does.
 */
export const ShelfPanel = () => {
	const { data, isLoading, error, refetch } = useBrandComparison();
	const { keyword } = useMarketView();
	const rows = data?.rows ?? [];

	const option = useMemo(() => {
		const pts = (data?.rows ?? []).filter(
			(r) => r.avg_unit_price != null && r.avg_position != null,
		);
		const basis = pts[0]?.unit_basis ?? "";
		return {
			tooltip: {
				trigger: "item",
				formatter: (p) => {
					const r = p.data.row;
					return `<b>${r.brand}</b><br/>Rank ${rank(r.avg_position)}<br/>₹${r.avg_unit_price}${BASIS[r.unit_basis] ?? ""}<br/>${pct(r.presence_pct)} of stores`;
				},
			},
			grid: { left: 8, right: 24, top: 16, bottom: 32, containLabel: true },
			xAxis: {
				type: "value",
				name: `₹ ${BASIS[basis] ?? "per unit"}`,
				nameLocation: "middle",
				nameGap: 26,
				splitLine: { lineStyle: { opacity: 0.25 } },
			},
			yAxis: {
				type: "value",
				name: "Avg rank",
				// Lower rank number = better, so invert: best sits at the top.
				inverse: true,
				splitLine: { lineStyle: { opacity: 0.25 } },
			},
			series: [
				{
					type: "scatter",
					symbolSize: (d) => 12 + (d.row.presence_pct ?? 0) / 8,
					data: pts.map((r) => ({
						value: [r.avg_unit_price, r.avg_position],
						row: r,
						itemStyle: { opacity: r.is_own ? 1 : 0.55 },
						label: {
							show: true,
							position: "right",
							formatter: r.brand,
							fontSize: 11,
							fontWeight: r.is_own ? "bold" : "normal",
						},
					})),
				},
			],
		};
	}, [data]);

	const columns = [
		{
			key: "brand",
			label: "Brand",
			render: (r) => (r.is_own ? `${r.brand} (you)` : r.brand),
		},
		{ key: "avg_position", label: "Avg rank", align: "right", render: (r) => rank(r.avg_position) },
		{ key: "avg_price", label: "Avg price", align: "right", render: (r) => formatCurrency(r.avg_price) },
		{
			key: "avg_unit_price",
			label: "Per unit",
			align: "right",
			render: (r) =>
				r.avg_unit_price == null
					? "—"
					: `${formatCurrency(r.avg_unit_price)}${BASIS[r.unit_basis] ?? ""}`,
		},
		{ key: "avg_discount_pct", label: "Discount", align: "right", render: (r) => pct(r.avg_discount_pct) },
		{ key: "presence_pct", label: "Stores", align: "right", render: (r) => pct(r.presence_pct) },
		{ key: "paid_share_pct", label: "Paid slots", align: "right", render: (r) => pct(r.paid_share_pct) },
		{ key: "skus", label: "SKUs", align: "right", render: (r) => formatNumber(r.skus) },
	];

	return (
		<ChartTableCard
			title={keyword ? `The shelf for “${keyword}”` : "The shelf, all terms"}
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No listings in this window."
			renderChart={() => <EChart option={option} height={320} />}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.brand}
		/>
	);
};
