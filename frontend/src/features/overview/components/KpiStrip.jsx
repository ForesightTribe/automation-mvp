import { Card } from "../../../components/ui/Card";
import { formatCompactCurrency, formatNumber } from "../../../lib/format";

/**
 * Headline KPI tiles. One subsection of the Overview page = one file (per the
 * dashboard-views catalog). Renders whatever `data` the overview endpoint
 * returns; fields below are placeholders to wire against the real response.
 */
export const KpiStrip = ({ data }) => {
	const kpis = [
		{ label: "Revenue", value: formatCompactCurrency(data?.revenue) },
		{ label: "Units sold", value: formatNumber(data?.units) },
		{ label: "Active SKUs", value: formatNumber(data?.skus) },
		{ label: "Ad spend", value: formatCompactCurrency(data?.adSpend) },
	];

	return (
		<div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
			{kpis.map((kpi) => (
				<Card key={kpi.label}>
					<p className="text-xs font-medium uppercase tracking-wide text-content-subtle">
						{kpi.label}
					</p>
					<p className="mt-2 font-display text-2xl font-bold text-content">
						{kpi.value}
					</p>
				</Card>
			))}
		</div>
	);
};
