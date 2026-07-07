import { useMemo } from "react";
import { useDistribution } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { rankedBarOption } from "../../../components/charts/options";
import { formatCurrency, formatNumber } from "../../../lib/format";

const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);

/**
 * Distribution % per own SKU — the share of covered stores each SKU is actually
 * in-stock in. The endpoint returns widest-gaps-first, so the chart shows the
 * lowest-coverage SKUs on top (where you're missing shelf); the table adds store
 * counts, price, and discount.
 */
export const DistributionCard = ({ kind = "main" }) => {
	const { data, isLoading, error, refetch } = useDistribution(kind);
	const rows = data?.skus ?? [];

	// API returns worst-first; rankedBarOption puts input[0] on top → worst on top.
	const option = useMemo(
		() =>
			rankedBarOption(
				(data?.skus ?? []).map((s) => ({
					label: s.product_name || s.platform_product_id,
					value: s.distribution_pct,
				})),
				{ money: false, color: "#0284c7" },
			),
		[data],
	);

	const columns = [
		{ key: "product_name", label: "Product", render: (r) => r.product_name || r.platform_product_id },
		{
			key: "distribution_pct",
			label: "Distribution",
			align: "right",
			render: (r) => pct(r.distribution_pct),
		},
		{
			key: "locations",
			label: "In-stock / locations",
			align: "right",
			render: (r) => `${formatNumber(r.in_stock_locations)} / ${formatNumber(r.total_locations)}`,
		},
		{
			key: "avg_price",
			label: "Avg price",
			align: "right",
			render: (r) => formatCurrency(r.avg_price),
		},
		{ key: "avg_discount", label: "Avg disc.", align: "right", render: (r) => pct(r.avg_discount) },
	];

	return (
		<ChartTableCard
			title="Distribution by SKU"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No own-SKU data in this window. Run the targeted scrape (public-skus)."
			renderChart={() => <EChart option={option} height={Math.max(280, rows.length * 26)} />}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.platform_product_id}
			tableMaxHeight={480}
		/>
	);
};
