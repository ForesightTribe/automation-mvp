import { usePublicShelf } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { FreshnessBadge } from "../../../components/ui/FreshnessBadge";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatNumber } from "../../../lib/format";

const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);
const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

/**
 * On-shelf distribution summary for the Overview — the public availability headline
 * (avg distribution across own SKUs, count with coverage gaps) plus the worst-covered
 * SKUs, so a distribution problem surfaces here without opening the Inventory page.
 * Owns its own fetch/loading (like MarketplaceBreakdown).
 */
export const PublicShelfCard = () => {
	const { data, isLoading, error, refetch } = usePublicShelf();
	const skus = data?.skus ?? [];
	const avgDist = mean(skus.map((s) => s.distribution_pct));
	const withGaps = skus.filter((s) => s.distribution_pct < 100).length;
	const worst = skus.slice(0, 5); // endpoint returns widest-gaps-first

	return (
		<Card title="On-shelf distribution" actions={<FreshnessBadge at={data?.as_of} />}>
			{isLoading && <Loading label="Loading distribution…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(skus.length === 0 ? (
					<EmptyState message="No own-SKU data yet. Run the targeted scrape (public-skus)." />
				) : (
					<div className="flex flex-col gap-4">
						<div className="grid grid-cols-2 gap-4">
							<div>
								<p className="text-xs font-medium uppercase tracking-wide text-content-subtle">
									Avg distribution
								</p>
								<p className="mt-1 font-display text-2xl font-bold text-content">
									{pct(avgDist)}
								</p>
							</div>
							<div>
								<p className="text-xs font-medium uppercase tracking-wide text-content-subtle">
									SKUs with gaps
								</p>
								<p className="mt-1 font-display text-2xl font-bold text-content">
									{formatNumber(withGaps)}
									<span className="ml-1 text-sm font-normal text-content-muted">
										/ {formatNumber(skus.length)}
									</span>
								</p>
							</div>
						</div>

						<div>
							<p className="mb-2 text-xs font-medium uppercase tracking-wide text-content-subtle">
								Widest gaps
							</p>
							<ul className="flex flex-col gap-2">
								{worst.map((s) => (
									<li
										key={s.platform_product_id}
										className="flex items-center justify-between gap-3 text-sm"
									>
										<span className="truncate text-content">
											{s.product_name || s.platform_product_id}
										</span>
										<span className="shrink-0 tabular-nums text-content-muted">
											{pct(s.distribution_pct)}
											<span className="ml-1 text-content-subtle">
												({formatNumber(s.in_stock_stores)}/
												{formatNumber(s.total_stores)})
											</span>
										</span>
									</li>
								))}
							</ul>
						</div>
					</div>
				))}
		</Card>
	);
};
