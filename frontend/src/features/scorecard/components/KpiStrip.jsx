import { MetricTile } from "../../../components/ui/MetricTile";
import { formatCompactCurrency, formatNumber } from "../../../lib/format";

/** Fill rate etc. come from Blinkit as a 0–100 number already (not a fraction),
 * so format directly rather than via formatPercent (which would ×100 again). */
const formatPct = (v) =>
	v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`;

const formatRank = (v) =>
	v === null || v === undefined ? "—" : `#${formatNumber(v)}`;

/**
 * Scorecard headline KPIs for the selected week. Each metric is a
 * { value, prev, delta_pct } from `scorecard/weekly` (vs the previous week).
 * Fill rate and manufacturer rank are "better when higher / lower" respectively;
 * potential loss is lower-is-better. No sparklines — the weekly cadence is too
 * coarse; the week-over-week trend lives in its own chart below.
 */
export const KpiStrip = ({ metrics }) => {
	const m = (key) => metrics?.[key] ?? {};

	const tiles = [
		{
			label: "Fill rate",
			value: formatPct(m("fill_rate").value),
			delta: m("fill_rate").delta_pct,
		},
		{
			label: "Weighted fill rate",
			value: formatPct(m("weighted_fill_rate_percent").value),
			delta: m("weighted_fill_rate_percent").delta_pct,
		},
		{
			label: "Potential loss",
			value: formatCompactCurrency(m("potential_loss").value),
			delta: m("potential_loss").delta_pct,
			goodWhenDown: true,
		},
		{
			label: "Total GMV",
			value: formatCompactCurrency(m("total_gmv").value),
			delta: m("total_gmv").delta_pct,
		},
		{
			label: "Manufacturer rank",
			value: formatRank(m("manufacturer_rank").value),
			delta: m("manufacturer_rank").delta_pct,
			goodWhenDown: true,
		},
		{
			label: "PO quantity",
			value: formatNumber(m("total_po_quantity").value),
			delta: m("total_po_quantity").delta_pct,
		},
		{
			label: "GRN quantity",
			value: formatNumber(m("total_grn_quantity").value),
			delta: m("total_grn_quantity").delta_pct,
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
				/>
			))}
		</div>
	);
};
