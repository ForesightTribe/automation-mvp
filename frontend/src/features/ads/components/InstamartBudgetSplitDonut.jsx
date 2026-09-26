import { useMemo } from "react";
import { useInstamartBudgetSplit } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { donutOption } from "../../../components/charts/options";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { formatCurrency, formatPercent } from "../../../lib/format";

const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;

/** Instamart's campaign types come back SCREAMING_SNAKE ("SEARCH_AUTO_SUGGEST"),
 * with the redundant "CAMPAIGN_TYPE_" prefix already stripped server-side —
 * this just makes what's left readable ("Search Auto Suggest"). */
const typeLabel = (t) =>
	t
		? t
				.toLowerCase()
				.split("_")
				.map((w) => w.charAt(0).toUpperCase() + w.slice(1))
				.join(" ")
		: "Unknown";

/** Budget split by Instamart campaign type, windowed by the date picker —
 * see instamart_ads.budget_split's docstring for the source.
 *
 * A separate card from `BudgetSplitDonut` (Blinkit) and `ZeptoBudgetSplitDonut`
 * because neither of those can see Instamart's data.
 *
 * Hidden when Instamart is out of scope, rather than rendering an empty donut.
 */
export const InstamartBudgetSplitDonut = () => {
	const { selected } = useMarketplaces();
	const wantsInstamart = !selected?.length || selected.includes("instamart");

	const { data, isLoading, error, refetch } = useInstamartBudgetSplit();
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

	if (!wantsInstamart) return null;

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
			title="Budget split by type · Instamart"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No Instamart campaign spend yet."
			renderChart={() => <EChart option={option} height={300} />}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.campaign_type ?? "unknown"}
		/>
	);
};
