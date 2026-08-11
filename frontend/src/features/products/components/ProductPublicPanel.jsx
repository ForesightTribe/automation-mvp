import { useProductPublic } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { FreshnessBadge } from "../../../components/ui/FreshnessBadge";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import {
	formatCurrency,
	formatNumber,
	formatUnitPrice,
} from "../../../lib/format";

const pct = (v) =>
	v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`;
const rank = (v) =>
	v === null || v === undefined ? "—" : `#${Number(v).toFixed(0)}`;
const packText = (size, uom) =>
	size == null || !uom ? null : `${size} ${uom} pack`;

/** A headline figure with a plain-language sub-line carrying the counts behind it. */
const Stat = ({ label, value, sub, tone }) => (
	<div>
		<p className="text-xs font-medium uppercase tracking-wide text-content-subtle">
			{label}
		</p>
		<p
			className={`mt-1 font-display text-2xl font-bold ${
				tone === "danger"
					? "text-danger"
					: tone === "warning"
						? "text-warning"
						: "text-content"
			}`}
		>
			{value}
		</p>
		{sub && <p className="mt-0.5 text-xs text-content-muted">{sub}</p>}
	</div>
);

/** A labelled progress bar — makes "on shelf in 427 of 2,022" legible at a glance. */
const Meter = ({ label, value, count, total, tone = "brand" }) => (
	<div>
		<div className="mb-1 flex items-baseline justify-between text-sm">
			<span className="text-content">{label}</span>
			<span className="tabular-nums text-content-muted">
				{pct(value)}
				<span className="ml-1.5 text-xs text-content-subtle">
					{formatNumber(count)} of {formatNumber(total)} stores
				</span>
			</span>
		</div>
		<div className="h-2 w-full overflow-hidden rounded-full bg-muted">
			<div
				className={`h-full rounded-full ${tone === "danger" ? "bg-danger" : tone === "success" ? "bg-success" : "bg-brand"}`}
				style={{ width: `${Math.min(Math.max(value ?? 0, 0), 100)}%` }}
			/>
		</div>
	</div>
);

/**
 * The public (scraped) side of one SKU on the product detail page, bridged from the
 * private item_id via sku_map.
 *
 * Rewritten to read like a shelf report, not a stat dump: two meters carry the story
 * (how widely it's on shelf, and how in-stock it is where listed) with their counts
 * inline, then price / discount / rating as secondary figures, then where it ranks in
 * search. Written for a brand manager — no "distribution"/"reach" jargon (which mean
 * the opposite in FMCG), and every percentage shows its "X of N". See docs/darkstores.md.
 */
export const ProductPublicPanel = ({ itemId }) => {
	const { data, isLoading, error, refetch } = useProductPublic(itemId);

	const notStocked =
		data?.mapped && data.stores_scraped
			? data.stores_scraped - data.stores_listed
			: 0;

	return (
		<Card
			title="On the shelf"
			actions={data?.mapped ? <FreshnessBadge at={data?.as_of} /> : null}
		>
			{isLoading && <Loading label="Loading shelf data…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading && !error && data && !data.mapped && (
				<EmptyState
					title="No public shelf data yet"
					message="We haven't linked this product to its Blinkit listing. Once mapped, its live shelf presence, pricing and search rank show here."
				/>
			)}
			{!isLoading && !error && data?.mapped && (
				<div className="flex flex-col gap-6">
					{/* The story: breadth (on shelf) then health (in stock). */}
					<div className="flex flex-col gap-4">
						<Meter
							label="On shelf"
							value={data.reach_pct}
							count={data.stores_listed}
							total={data.stores_scraped}
						/>
						<Meter
							label="In stock where listed"
							value={data.distribution_pct}
							count={data.stores_in_stock}
							total={data.stores_listed}
							tone={
								data.distribution_pct >= 95
									? "success"
									: "danger"
							}
						/>
					</div>

					{notStocked > 0 && (
						<p className="rounded-md bg-muted px-3 py-2 text-xs text-content-muted">
							Not carried in{" "}
							<span className="font-medium text-content">
								{formatNumber(notStocked)}
							</span>{" "}
							stores that stock the rest of your range — a listing
							opportunity.
						</p>
					)}

					{/* Secondary figures. */}
					<div className="grid grid-cols-2 gap-4 border-t border-border pt-4 sm:grid-cols-4">
						<Stat
							label="Typical price"
							value={formatCurrency(data.price_median)}
							sub={
								data.price_min != null
									? `${formatCurrency(data.price_min)}–${formatCurrency(data.price_max)} across stores`
									: undefined
							}
						/>
						<Stat
							label="Per unit"
							value={formatUnitPrice(
								data.unit_price_median,
								data.pack_uom,
							)}
							sub={packText(data.pack_size, data.pack_uom)}
						/>
						<Stat
							label="Avg discount"
							value={pct(data.avg_discount)}
						/>
						<Stat
							label="Rating"
							value={
								data.rating != null
									? data.rating.toFixed(1)
									: "—"
							}
						/>
					</div>

					{/* Where shoppers find it in search. */}
					<div className="border-t border-border pt-4">
						<p className="mb-2 text-xs font-medium uppercase tracking-wide text-content-subtle">
							Where it ranks in search
						</p>
						{data.keywords.length === 0 ? (
							<p className="text-sm text-content-muted">
								Not seen in tracked searches this window.
							</p>
						) : (
							<ul className="flex flex-col gap-1.5">
								{data.keywords.map((k) => (
									<li
										key={k.keyword}
										className="flex items-center justify-between gap-3 text-sm"
									>
										<span className="text-content">
											{k.keyword}
										</span>
										<span className="tabular-nums text-content-muted">
											position {rank(k.avg_position)}
											<span className="ml-2 text-content-subtle">
												in {formatNumber(k.stores)}{" "}
												stores
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
