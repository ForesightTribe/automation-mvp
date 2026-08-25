import { useMemo, useState } from "react";
import { useZeptoBreakdown } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { donutOption } from "../../../components/charts/options";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { formatCurrency, formatPercent } from "../../../lib/format";
import { AD_TYPE_OPTIONS, AdTypeSelect } from "./AdTypeSelect";
import { AdTypeTag } from "./AdTypeTag";

const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;

/** One card serving all three Zepto breakdown views.
 *
 * `category_table`, `city_table` and `page_table` return the same shape, so they
 * share a component the way they share a table and a parser. `dimension` picks
 * which; `label` names the first column.
 *
 * Donut plus table via `ChartTableCard`: each of these has only a handful of
 * buckets, and the useful question is what share of spend each takes. The table
 * view is one click away for exact figures.
 */
export const ZeptoBreakdownCard = ({ dimension, title, label }) => {
	const [adType, setAdType] = useState("");

	const { selected } = useMarketplaces();
	const wantsZepto = !selected?.length || selected.includes("zepto");

	const { data, isLoading, error, refetch } = useZeptoBreakdown({
		dimension,
		campaignCategory: adType,
	});
	const rows = data ?? [];

	const total = useMemo(
		() => (data ?? []).reduce((s, r) => s + r.spend, 0),
		[data],
	);
	const option = useMemo(
		() =>
			donutOption(
				(data ?? []).map((r) => ({ name: r.name, value: r.spend })),
			),
		[data],
	);

	if (!wantsZepto) return null;

	const columns = [
		{
			key: "name",
			label,
			render: (r) => (
				<div className="flex items-center gap-2">
					<span>{r.name}</span>
					<AdTypeTag types={r.ad_types} />
				</div>
			),
		},
		{
			key: "spend",
			label: "Spend",
			align: "right",
			render: (r) => formatCurrency(r.spend),
		},
		{
			key: "share",
			label: "Share",
			align: "right",
			render: (r) => formatPercent(total ? r.spend / total : null),
		},
		{
			key: "sales",
			label: "Sales",
			align: "right",
			render: (r) => formatCurrency(r.sales),
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
			title={title}
			persistentActions={
				<AdTypeSelect
					value={adType}
					onChange={setAdType}
					options={AD_TYPE_OPTIONS}
				/>
			}
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage={`No Zepto ${dimension} data in this window.`}
			renderChart={() => <EChart option={option} height={300} />}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.name}
		/>
	);
};
