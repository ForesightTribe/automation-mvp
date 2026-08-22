import { useMemo } from "react";
import { useZeptoBudgetSplit } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { donutOption } from "../../../components/charts/options";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { formatCurrency, formatPercent } from "../../../lib/format";

const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;

/** Zepto's campaign types are already display-ready ("PLA", "Display") rather
 * than the SCREAMING_SNAKE enums Blinkit returns, so only the null case needs
 * handling. */
const typeLabel = (t) => t || "Unknown";

/** Budget split by Zepto campaign type — PLA vs Display.
 *
 * A separate card from `BudgetSplitDonut` because that one reads Blinkit's
 * daily table and cannot see Zepto's. The row shape is identical, so both use
 * the same `ChartTableCard` and donut option; only the data source differs.
 *
 * Hidden when Zepto is out of scope, rather than rendering an empty donut.
 */
export const ZeptoBudgetSplitDonut = () => {
	const { selected } = useMarketplaces();
	const wantsZepto = !selected?.length || selected.includes("zepto");

	const { data, isLoading, error, refetch } = useZeptoBudgetSplit();
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

	if (!wantsZepto) return null;

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
			render: (r) => formatCurrency(r.budget_consumed),
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
			title="Budget split by type · Zepto"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No Zepto spend in this window."
			renderChart={() => <EChart option={option} height={300} />}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.campaign_type ?? "unknown"}
		/>
	);
};
