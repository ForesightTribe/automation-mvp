import { useProductPublic } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { FreshnessBadge } from "../../../components/ui/FreshnessBadge";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCurrency, formatNumber } from "../../../lib/format";

const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);
const rank = (v) => (v === null || v === undefined ? "—" : `#${Number(v).toFixed(1)}`);

const Stat = ({ label, value, sub }) => (
	<div>
		<p className="text-xs font-medium uppercase tracking-wide text-content-subtle">
			{label}
		</p>
		<p className="mt-1 font-display text-2xl font-bold text-content">{value}</p>
		{sub && <p className="text-xs text-content-muted">{sub}</p>}
	</div>
);

/**
 * The public (scraped) side of one SKU, bridged from the private item_id via
 * sku_map: on-shelf distribution, price band, discount, rating, and where it ranks
 * per keyword. When the SKU isn't mapped yet, prompts to run `sku-map`.
 */
export const ProductPublicPanel = ({ itemId }) => {
	const { data, isLoading, error, refetch } = useProductPublic(itemId);

	return (
		<Card
			title="On the shelf (public)"
			actions={data?.mapped ? <FreshnessBadge at={data?.as_of} /> : null}
		>
			{isLoading && <Loading label="Loading public data…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading && !error && data && !data.mapped && (
				<EmptyState
					title="Not mapped to public data"
					message="This SKU has no public listing mapped yet. Run `sku-map build` (and confirm any unmatched) to link it."
				/>
			)}
			{!isLoading && !error && data?.mapped && (
				<div className="flex flex-col gap-5">
					<div className="grid grid-cols-2 gap-4 md:grid-cols-5">
						<Stat
							label="Distribution"
							value={pct(data.distribution_pct)}
							sub={`${formatNumber(data.in_stock_locations)} / ${formatNumber(
								data.total_locations,
							)} locations in stock`}
						/>
						<Stat
							label="Reach"
							value={pct(data.reach_pct)}
							sub={`${formatNumber(data.total_locations)} / ${formatNumber(
								data.covered_locations,
							)} covered areas`}
						/>
						<Stat
							label="Price"
							value={formatCurrency(data.price_median)}
							sub={
								data.price_min != null
									? `${formatCurrency(data.price_min)} – ${formatCurrency(
											data.price_max,
										)} across locations`
									: undefined
							}
						/>
						<Stat label="Avg discount" value={pct(data.avg_discount)} />
						<Stat
							label="Rating"
							value={data.rating != null ? data.rating.toFixed(2) : "—"}
						/>
					</div>

					<div>
						<p className="mb-2 text-xs font-medium uppercase tracking-wide text-content-subtle">
							Where it ranks
						</p>
						{data.keywords.length === 0 ? (
							<p className="text-sm text-content-muted">
								Not seen in tracked keyword searches this window.
							</p>
						) : (
							<ul className="flex flex-col gap-1.5">
								{data.keywords.map((k) => (
									<li
										key={k.keyword}
										className="flex items-center justify-between gap-3 text-sm"
									>
										<span className="text-content">{k.keyword}</span>
										<span className="tabular-nums text-content-muted">
											rank {rank(k.avg_position)}
											<span className="ml-2 text-content-subtle">
												(in {formatNumber(k.locations)} locations)
											</span>
										</span>
									</li>
								))}
							</ul>
						)}
					</div>
				</div>
			)}
		</Card>
	);
};
