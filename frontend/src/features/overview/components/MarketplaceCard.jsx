import { Card } from "../../../components/ui/Card";
import { DeltaBadge } from "../../../components/ui/DeltaBadge";
import {
	formatCompactCurrency,
	formatNumber,
	formatPercent,
} from "../../../lib/format";

const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;
const formatRank = (v) => (v === null || v === undefined ? "—" : v.toFixed(1));

/** Label + value + growth badge for one metric inside a marketplace card. */
const MetricRow = ({ label, value, delta, goodWhenDown = false }) => (
	<div className="flex items-center justify-between">
		<span className="text-xs text-content-muted">{label}</span>
		<span className="flex items-center gap-1.5">
			<span className="text-sm font-semibold text-content">{value}</span>
			<DeltaBadge delta={delta} goodWhenDown={goodWhenDown} />
		</span>
	</div>
);

const Header = ({ row }) => (
	<div className="mb-3 flex items-center gap-2">
		{row.color && (
			<span
				className="inline-block h-2.5 w-2.5 rounded-full"
				style={{ backgroundColor: row.color }}
			/>
		)}
		<h3 className="font-display text-sm font-semibold text-content">
			{row.name}
		</h3>
	</div>
);

/**
 * One marketplace's slice of the overview. Connected marketplaces show the full
 * metric set (each with its growth badge); unconnected ones render a muted
 * "Not connected" placeholder instead of faking numbers. `row` is a
 * MarketplaceRow from /overview/marketplaces.
 */
export const MarketplaceCard = ({ row }) => {
	if (!row.connected) {
		return (
			<Card className="opacity-70">
				<Header row={row} />
				<p className="text-xs text-content-subtle">
					Not connected — coming soon.
				</p>
			</Card>
		);
	}

	const m = (key) => row[key] ?? {};

	return (
		<Card>
			<Header row={row} />
			<div className="flex flex-col gap-2">
				<MetricRow
					label="Revenue"
					value={formatCompactCurrency(m("revenue").value)}
					delta={m("revenue").delta_pct}
				/>
				<MetricRow
					label="RoAS"
					value={formatRoas(m("roas").value)}
					delta={m("roas").delta_pct}
				/>
				<MetricRow
					label="Ad spend"
					value={formatCompactCurrency(m("ad_spend").value)}
					delta={m("ad_spend").delta_pct}
				/>
				<MetricRow
					label="Units sold"
					value={formatNumber(m("units_sold").value)}
					delta={m("units_sold").delta_pct}
				/>
				<MetricRow
					label="Visibility"
					value={formatPercent(m("visibility").value)}
					delta={m("visibility").delta_pct}
				/>
				<MetricRow
					label="Avg rank"
					value={formatRank(m("avg_rank").value)}
					delta={m("avg_rank").delta_pct}
					goodWhenDown
				/>
			</div>
		</Card>
	);
};
