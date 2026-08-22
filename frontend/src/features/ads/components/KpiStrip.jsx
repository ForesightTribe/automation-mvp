import { MetricTile } from "../../../components/ui/MetricTile";
import { formatCurrency, formatNumber, formatPercent } from "../../../lib/format";

/** RoAS like "4.2x" (null -> em dash). */
const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;

/**
 * Ads KPI strip. Each metric is a { value, prev, delta_pct } from `ads/summary`,
 * aggregated across the selected marketplaces + date range. Sparklines come from
 * `ads/performance` (the daily backbone) where a daily series exists. ACoS is
 * lower-is-better, so its growth badge colors are inverted.
 */
export const KpiStrip = ({ summary, performance = [] }) => {
	const m = (key) => summary?.[key] ?? {};
	const series = (fn) => performance.map(fn);

	const tiles = [
		{
			label: "Ad Spend",
			value: formatCurrency(m("ad_spend").value),
			delta: m("ad_spend").delta_pct,
			series: series((r) => r.budget_consumed),
			sparkColor: "#4f46e5",
		},
		{
			label: "Ad Revenue",
			value: formatCurrency(m("ad_sales").value),
			delta: m("ad_sales").delta_pct,
			series: series((r) => r.ad_sales),
			sparkColor: "#16a34a",
		},
		{
			label: "RoAS",
			value: formatRoas(m("roas").value),
			delta: m("roas").delta_pct,
			series: series((r) => r.roas),
			sparkColor: "#d97706",
		},
		{
			label: "ACoS",
			value: formatPercent(m("acos").value),
			delta: m("acos").delta_pct,
			goodWhenDown: true,
		},
		{
			label: "Impressions",
			value: formatNumber(m("impressions").value),
			delta: m("impressions").delta_pct,
			series: series((r) => r.impressions),
			sparkColor: "#0284c7",
		},
		{
			label: "Add-to-carts",
			value: formatNumber(m("atc").value),
			delta: m("atc").delta_pct,
		},
		{
			label: "Units sold",
			value: formatNumber(m("units_sold").value),
			delta: m("units_sold").delta_pct,
		},
		{
			label: "Active campaigns",
			value: formatNumber(m("active_campaigns").value),
			delta: m("active_campaigns").delta_pct,
		},
	];

	return (
		<div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
			{tiles.map((t) => (
				<MetricTile
					key={t.label}
					label={t.label}
					value={t.value}
					delta={t.delta}
					goodWhenDown={t.goodWhenDown}
					series={t.series}
					sparkColor={t.sparkColor}
				/>
			))}
		</div>
	);
};
