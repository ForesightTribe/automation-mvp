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
 * On-shelf summary for the Overview — average shelf presence across own SKUs, how
 * many have gaps, and the least-available ones — so a shelf problem surfaces here
 * without opening the Inventory page. "On shelf" = reach (breadth); the endpoint
 * (`/inventory/distribution`) returns per-SKU `reach_pct`, worst first. Owns its own
 * fetch/loading (like MarketplaceBreakdown).
 */
export const PublicShelfCard = () => {
	const { data, isLoading, error, refetch } = usePublicShelf();
	const skus = data?.skus ?? [];
	const scraped = data?.stores_scraped ?? 0;
	const avgOnShelf = mean(skus.map((s) => s.reach_pct));
	const withGaps = skus.filter((s) => s.reach_pct < 100).length;
	const worst = skus.slice(0, 5); // endpoint returns worst-reach-first

	return (
		<Card title="On the shelf" actions={<FreshnessBadge at={data?.as_of} />}>
			{isLoading && <Loading label="Loading shelf data…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(skus.length === 0 ? (
					<EmptyState message="No shelf data yet." />
				) : (
					<div className="flex flex-col gap-4">
						<div className="grid grid-cols-2 gap-4">
							<div>
								<p className="text-xs font-medium uppercase tracking-wide text-content-subtle">
									Avg on shelf
								</p>
								<p className="mt-1 font-display text-2xl font-bold text-content">
									{pct(avgOnShelf)}
								</p>
							</div>
							<div>
								<p className="text-xs font-medium uppercase tracking-wide text-content-subtle">
									Products with gaps
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
								Least available
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
											{pct(s.reach_pct)}
											<span className="ml-1 text-content-subtle">
												({formatNumber(s.stores_listed)}/
												{formatNumber(scraped)} stores)
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
