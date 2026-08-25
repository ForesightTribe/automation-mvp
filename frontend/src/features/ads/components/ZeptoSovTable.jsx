import { useZeptoSov } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { useMarketplaces } from "../../../context/MarketplaceContext";

/** Widest SOV observed on this account is well under 1%, so the bar is scaled
 * against the highest value on screen rather than against 100% — a bar drawn to
 * absolute scale would be invisible for every row. */
const barWidth = (v, max) => (!v || !max ? 0 : Math.max(2, (v / max) * 100));

const formatSov = (v) => (v === null || v === undefined ? "—" : `${v}%`);

const formatPos = (v) =>
	v === null || v === undefined ? "—" : v.toFixed(0);

/** Share of voice and ad position per Zepto campaign.
 *
 * Separate from `SovTable`, which is Blinkit's and reports SOV per KEYWORD with
 * search volumes. Zepto reports it per CAMPAIGN with neither.
 *
 * Deliberately labelled "as of" rather than sitting under the page's date
 * range: Zepto recomputes SOV and ad position on a trailing basis and returns
 * the same value whatever window is requested, so these figures do not describe
 * the selected period and must not look as though they do.
 */
export const ZeptoSovTable = () => {
	const { selected } = useMarketplaces();
	const wantsZepto = !selected?.length || selected.includes("zepto");

	const { data, isLoading, error, refetch } = useZeptoSov();
	const rows = data ?? [];

	if (!wantsZepto) return null;

	const max = Math.max(...rows.map((r) => r.sov ?? 0), 0);
	const asOf = rows[0]?.as_of;

	return (
		<Card
			title="Share of voice · Zepto"
			actions={
				asOf ? (
					<span className="text-xs text-content-subtle">
						Trailing 7 days, as of {asOf}
					</span>
				) : null
			}
		>
			{isLoading && <Loading label="Loading Zepto SOV…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(rows.length === 0 ? (
					<EmptyState message="No Zepto share-of-voice reported yet." />
				) : (
					<div className="overflow-auto" style={{ maxHeight: 360 }}>
						<table className="w-full border-collapse text-sm">
							<thead className="sticky top-0 z-10 bg-card">
								<tr className="border-b border-border">
									<th className="px-3 py-2 text-left font-medium text-content-subtle">
										Campaign
									</th>
									<th className="px-3 py-2 text-right font-medium text-content-subtle">
										Ad position
									</th>
									<th className="px-3 py-2 text-left font-medium text-content-subtle">
										SOV
									</th>
								</tr>
							</thead>
							<tbody>
								{rows.map((r) => (
									<tr
										key={r.campaign_id}
										className="border-b border-border/60 last:border-0 hover:bg-muted/50"
									>
										<td className="px-3 py-2">
											<div className="font-medium text-content">
												{r.campaign_name ?? r.campaign_id}
											</div>
											<div className="text-xs text-content-subtle">
												{r.campaign_type}
											</div>
										</td>
										<td className="px-3 py-2 text-right tabular-nums text-content">
											{formatPos(r.ad_position)}
										</td>
										<td className="px-3 py-2">
											<div className="flex items-center gap-2">
												<div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
													<div
														className="h-full rounded-full bg-brand"
														style={{
															width: `${barWidth(r.sov, max)}%`,
														}}
													/>
												</div>
												<span className="tabular-nums text-content">
													{formatSov(r.sov)}
												</span>
											</div>
										</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>
				))}
		</Card>
	);
};
