import { useMemo } from "react";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { rankedBarOption } from "../../../components/charts/options";
import { formatCurrency, formatNumber } from "../../../lib/format";

const COLUMNS = [
	{ key: "city", label: "City" },
	{
		key: "units_sold",
		label: "Units",
		align: "right",
		render: (r) => formatNumber(r.units_sold),
	},
	{
		key: "revenue",
		label: "Revenue",
		align: "right",
		render: (r) => formatCurrency(r.revenue),
	},
];

/** Where this SKU sells — top cities by revenue (bars) or the full table. */
export const CityBreakdown = ({ cities = [], marketplace }) => {
	const option = useMemo(
		() =>
			rankedBarOption(
				cities.slice(0, 10).map((c) => ({
					label: c.city,
					value: c.revenue,
				})),
				{ color: "#0284c7", money: true },
			),
		[cities],
	);

	return (
		<ChartTableCard
			title="Sales by city"
			isLoading={false}
			error={null}
			isEmpty={cities.length === 0}
			// Zepto does report sales by city, but only for the brand as a whole —
			// its API carries no product dimension on that endpoint. Showing the
			// brand split under a per-SKU heading would misattribute it, so the
			// section stays empty and says why.
			emptyMessage={
				marketplace === "zepto"
					? "Zepto reports city sales for the brand, not per SKU."
					: "No city sales in this window."
			}
			renderChart={() => <EChart option={option} height={320} />}
			columns={COLUMNS}
			rows={cities}
			rowKey={(r) => r.city}
		/>
	);
};
