import { useSov } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatNumber } from "../../../lib/format";

/** Blinkit reports SOV as a 0–100 percentage (its API: 2.72, 8.61, 100.0), stored as-is.
 * ⚠️ Never rescaled: this used to treat anything ≤ 1 as a fraction and multiply by 100, so
 * a real 0.06% read as 6% (hundreds of rows a month per client). */
const toPct = (v) => v ?? 0;

/** Sponsored share-of-voice per keyword — your paid presence on each searched
 * term, with a bar for quick scanning (highest SOV first).
 *
 * `barClass` exists because this table is rendered on two pages that are on different sides
 * of the brand rollout: the Ads page keeps the primary indigo it has always had, and
 * Insights passes the brand red. One component, because the numbers must not diverge. */
export const SovTable = ({ barClass = "bg-primary" }) => {
	const { data, isLoading, error, refetch } = useSov();
	const rows = data ?? [];

	return (
		<Card title="Sponsored share of voice · Blinkit">
			{isLoading && <Loading label="Loading SOV…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(rows.length === 0 ? (
					<EmptyState message="No sponsored SOV in this window." />
				) : (
					<div className="overflow-auto" style={{ maxHeight: 360 }}>
						<table className="table-frozen w-full border-collapse text-sm">
							<thead className="sticky top-0 z-10 bg-card">
								<tr className="border-b border-border">
									<th className="px-3 py-2 text-left font-medium text-content-subtle">
										Keyword
									</th>
									<th className="px-3 py-2 text-right font-medium text-content-subtle">
										Monthly searches
									</th>
									<th className="px-3 py-2 text-left font-medium text-content-subtle">
										SOV
									</th>
								</tr>
							</thead>
							<tbody>
								{rows.map((r) => {
									const pct = toPct(r.sov);
									return (
										<tr
											key={r.keyword}
											className="border-b border-border/60 last:border-0 hover:bg-muted/50"
										>
											<td className="px-3 py-2 font-medium text-content">
												{r.keyword}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content-muted">
												{formatNumber(
													r.monthly_searches,
												)}
											</td>
											<td className="px-3 py-2">
												<div className="flex items-center gap-2">
													<div className="h-2 flex-1 rounded-full bg-muted">
														<div
															className={`h-2 rounded-full ${barClass}`}
															style={{
																width: `${Math.min(pct, 100)}%`,
															}}
														/>
													</div>
													<span className="w-12 text-right tabular-nums text-content">
														{/* Two places under 1%, where one would round 0.06 to 0.1. */}
														{pct.toFixed(
															pct > 0 && pct < 1
																? 2
																: 1,
														)}
														%
													</span>
												</div>
											</td>
										</tr>
									);
								})}
							</tbody>
						</table>
					</div>
				))}
		</Card>
	);
};
