import { useMarketing } from "../hooks";
import { formatNumber, formatCurrency } from "../../../lib/format";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";

/**
 * Marketing performance — the daily ad ledger with a Total + daily-run-rate
 * footer. Ad metrics from `blinkit_ad_campaign_daily`, total revenue from
 * `blinkit_seller_sales`, organic = total − ad. RoAS/ROI are recomputed from
 * summed inputs server-side, never averaged.
 *
 * The "Comments / Discounts & Marketing" column and the target-vs-actual budget
 * block are intentionally deferred (they need manual-input tables we chose not
 * to build yet), so this view is pure read.
 */

// Full rupee figures (₹1,23,456), not the compact ₹1.2L the KPI tiles use — this
// is a ledger the client reconciles against their own numbers, so every digit shows.
const money = (v) => formatCurrency(v);
const ratioX = (v) => (v === null || v === undefined ? "—" : `${v.toFixed(1)}x`);
const ratio = (v) => (v === null || v === undefined ? "—" : v.toFixed(1));

/** "2026-07-01" -> "01-07-26". */
const dateLabel = (iso) => {
	const [y, m, d] = iso.split("-");
	return `${d}-${m}-${y.slice(2)}`;
};

const cols = [
	{ key: "date", label: "Date", align: "left", fmt: (r) => dateLabel(r.date) },
	{ key: "spend", label: "Ad Spend", fmt: (r) => money(r.spend) },
	{ key: "ad_revenue", label: "Ad Revenue", fmt: (r) => money(r.ad_revenue) },
	{ key: "roas", label: "ROAS", fmt: (r) => ratioX(r.roas) },
	{ key: "organic_revenue", label: "Organic Rev", fmt: (r) => money(r.organic_revenue) },
	{ key: "total_revenue", label: "Total Rev", fmt: (r) => money(r.total_revenue) },
	{ key: "roi", label: "ROI", fmt: (r) => ratio(r.roi) },
	{ key: "impressions", label: "Impressions", fmt: (r) => formatNumber(r.impressions) },
];

export const MarketingReport = () => {
	const { data, isLoading, error, refetch } = useMarketing();

	if (isLoading) return <Loading label="Loading marketing report…" />;
	if (error) return <ErrorState message={error.message} onRetry={refetch} />;
	if (!data || !data.rows.length)
		return (
			<div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-content-muted shadow-[0_2px_8px_rgba(0,0,0,0.10)]">
				No marketing data in the selected window.
			</div>
		);

	const { rows, totals } = data;
	const drr = (v) => (totals.days ? v / totals.days : 0);

	return (
		<div className="overflow-x-auto rounded-xl border border-border bg-card shadow-[0_2px_8px_rgba(0,0,0,0.10)]">
			<table className="w-full border-collapse text-sm">
				<thead>
					<tr className="border-b border-border bg-muted/60 text-content-subtle">
						{cols.map((c) => (
							<th
								key={c.key}
								className={`px-3 py-2 font-medium ${
									c.align === "left" ? "text-left" : "text-right"
								}`}
							>
								{c.label}
							</th>
						))}
					</tr>
				</thead>
				<tbody>
					{rows.map((row) => (
						<tr
							key={row.date}
							className="border-b border-border/60 last:border-0 hover:bg-muted/40"
						>
							{cols.map((c) => (
								<td
									key={c.key}
									className={`px-3 py-1.5 text-content ${
										c.align === "left"
											? "text-left"
											: "text-right tabular-nums text-content-muted"
									}`}
								>
									{c.fmt(row)}
								</td>
							))}
						</tr>
					))}
				</tbody>
				<tfoot>
					{/* Window Total */}
					<tr className="border-t-2 border-border bg-muted/70 font-semibold text-content">
						<td className="px-3 py-1.5 text-left">Total</td>
						<td className="px-3 py-1.5 text-right tabular-nums">{money(totals.spend)}</td>
						<td className="px-3 py-1.5 text-right tabular-nums">{money(totals.ad_revenue)}</td>
						<td className="px-3 py-1.5 text-right tabular-nums">{ratioX(totals.roas)}</td>
						<td className="px-3 py-1.5 text-right tabular-nums">{money(totals.organic_revenue)}</td>
						<td className="px-3 py-1.5 text-right tabular-nums">{money(totals.total_revenue)}</td>
						<td className="px-3 py-1.5 text-right tabular-nums">{ratio(totals.roi)}</td>
						<td className="px-3 py-1.5 text-right tabular-nums">{formatNumber(totals.impressions)}</td>
					</tr>
					{/* Daily run rate */}
					<tr className="bg-muted/40 text-content-muted">
						<td className="px-3 py-1.5 text-left text-xs font-medium">DRR (daily avg)</td>
						<td className="px-3 py-1.5 text-right tabular-nums text-xs">{money(drr(totals.spend))}</td>
						<td className="px-3 py-1.5 text-right tabular-nums text-xs">{money(drr(totals.ad_revenue))}</td>
						<td className="px-3 py-1.5" />
						<td className="px-3 py-1.5 text-right tabular-nums text-xs">{money(drr(totals.organic_revenue))}</td>
						<td className="px-3 py-1.5 text-right tabular-nums text-xs">{money(drr(totals.total_revenue))}</td>
						<td className="px-3 py-1.5" />
						<td className="px-3 py-1.5 text-right tabular-nums text-xs">{formatNumber(Math.round(drr(totals.impressions)))}</td>
					</tr>
				</tfoot>
			</table>
		</div>
	);
};
