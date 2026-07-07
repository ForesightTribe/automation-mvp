import { Card } from "../../../components/ui/Card";
import { DeltaBadge } from "../../../components/ui/DeltaBadge";
import { formatCompactCurrency, formatNumber } from "../../../lib/format";

const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;

const MetricRow = ({ label, value, delta }) => (
	<div className="flex items-center justify-between">
		<span className="text-xs text-content-muted">{label}</span>
		<span className="flex items-center gap-1.5">
			<span className="text-sm font-semibold text-content">{value}</span>
			<DeltaBadge delta={delta} />
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
 * One marketplace's ad slice. Connected marketplaces show spend/revenue/RoAS/
 * impressions with growth badges; unconnected ones render a muted "Not connected"
 * placeholder so the multi-marketplace shape is visible even while only Blinkit
 * has ad data. `row` is an AdMarketplaceRow from /ads/marketplaces.
 */
export const AdMarketplaceCard = ({ row }) => {
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
					label="Ad spend"
					value={formatCompactCurrency(m("ad_spend").value)}
					delta={m("ad_spend").delta_pct}
				/>
				<MetricRow
					label="Ad revenue"
					value={formatCompactCurrency(m("ad_sales").value)}
					delta={m("ad_sales").delta_pct}
				/>
				<MetricRow
					label="RoAS"
					value={formatRoas(m("roas").value)}
					delta={m("roas").delta_pct}
				/>
				<MetricRow
					label="Impressions"
					value={formatNumber(m("impressions").value)}
					delta={m("impressions").delta_pct}
				/>
			</div>
		</Card>
	);
};
