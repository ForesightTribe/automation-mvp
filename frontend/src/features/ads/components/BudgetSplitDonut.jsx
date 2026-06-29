import { useMemo } from "react";
import { useBudgetSplit } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { donutOption } from "../../../components/charts/options";
import { formatCompactCurrency, formatPercent } from "../../../lib/format";

const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;

/** Pretty-print a campaign type enum: PRODUCT_LISTING -> "Product listing". */
const typeLabel = (t) =>
	t
		? t
				.toLowerCase()
				.replace(/_/g, " ")
				.replace(/^\w/, (c) => c.toUpperCase())
		: "Unknown";

/** Budget split by campaign type — spend-share donut, or a table that also shows
 * each type's recomputed RoAS. */
export const BudgetSplitDonut = () => {
	const { data, isLoading, error, refetch } = useBudgetSplit();
	const rows = data ?? [];
	const total = useMemo(
		() => (data ?? []).reduce((s, r) => s + r.budget_consumed, 0),
		[data],
	);
	const option = useMemo(
		() =>
			donutOption(
				(data ?? []).map((r) => ({
					name: typeLabel(r.campaign_type),
					value: r.budget_consumed,
				})),
			),
		[data],
	);

	const columns = [
		{
			key: "campaign_type",
			label: "Type",
			render: (r) => typeLabel(r.campaign_type),
		},
		{
			key: "budget_consumed",
			label: "Spend",
			align: "right",
			render: (r) => formatCompactCurrency(r.budget_consumed),
		},
		{
			key: "share",
			label: "Share",
			align: "right",
			render: (r) =>
				formatPercent(total ? r.budget_consumed / total : null),
		},
		{
			key: "roas",
			label: "RoAS",
			align: "right",
			render: (r) => formatRoas(r.roas),
		},
	];

	return (
		<ChartTableCard
			title="Budget split by type"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No spend in this window."
			renderChart={() => <EChart option={option} height={300} />}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.campaign_type ?? "unknown"}
		/>
	);
};
