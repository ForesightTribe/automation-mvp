import { useTopSkus, useDistribution } from "../hooks";
import { Loading } from "../../../components/feedback/Loading";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCurrency, formatNumber } from "../../../lib/format";

/**
 * What each SKU sells, against how much of the shelf it is actually on.
 *
 * The pairing is the point. A SKU selling well from a fifth of the country is a
 * listings conversation; the same revenue from near-full coverage is a mature
 * line with little headroom left. Neither figure says that on its own, and they
 * live on opposite sides of the product — sales are private seller data, reach
 * comes from the public scrape.
 *
 * ⚠️ The two sides use different id systems — sales are keyed on Blinkit's
 * private `item_id`, reach on the public `platform_product_id`, with no shared
 * code between them. Pairs are matched by normalised name; unmatched SKUs are
 * dropped and their count shown. A rename on either side breaks the pair.
 */
const SHOWN = 10;

/** Names differ in case, punctuation and pack suffixes across the two feeds. */
const norm = (s) =>
	String(s ?? "")
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, " ")
		.trim();

export const SalesVsReach = () => {
	const { data: skus, isLoading } = useTopSkus(50);
	const { data: dist } = useDistribution();

	const reach = new Map(
		(dist?.skus ?? []).map((r) => [norm(r.product_name), r]),
	);

	const all = (skus ?? []).map((s) => ({
		name: s.item_name ?? s.item_id,
		revenue: s.revenue,
		match: reach.get(norm(s.item_name)),
	}));
	const rows = all
		.filter((r) => r.match)
		.sort((a, b) => b.revenue - a.revenue)
		.slice(0, SHOWN);
	const unmatched = all.length - all.filter((r) => r.match).length;

	return (
		<section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
			<div className="flex flex-col gap-0.5">
				<h2 className="font-display text-base font-semibold text-content">
					Sales against availability
				</h2>
				<p className="text-xs text-content-muted">
					What each SKU earns, beside how many covered stores list it
					and how many hold stock.
				</p>
			</div>

			{isLoading && <Loading label="Loading…" />}
			{!isLoading && rows.length === 0 && (
				<EmptyState message="No SKU could be matched across sales and availability." />
			)}

			{rows.length > 0 && (
				<>
					<div className="flex items-baseline gap-3 border-b border-border pb-1.5 text-[11px] tracking-wide text-content-subtle uppercase">
						<span className="flex-1 pl-2">SKU</span>
						<span className="w-28 text-right">Revenue</span>
						<span className="w-20 text-right">Listed</span>
						<span className="w-28 text-right">Reach</span>
						<span className="w-16 text-right">In stock</span>
					</div>
					<ul className="flex flex-col">
						{rows.map((r) => (
							<li
								key={r.name}
								className="flex items-baseline gap-3 border-b border-border py-2 last:border-0"
							>
								<span
									title={r.name}
									className="min-w-0 flex-1 truncate pl-2 text-sm text-content"
								>
									{r.name}
								</span>
								<span className="w-28 text-right text-sm font-medium text-content tabular-nums">
									{formatCurrency(r.revenue)}
								</span>
								<span className="w-20 text-right text-sm text-content-muted tabular-nums">
									{formatNumber(r.match.stores_listed)}
								</span>
								<span className="flex w-28 shrink-0 items-center gap-2">
									<span
										aria-hidden
										className="relative block h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
									>
										<span
											className="absolute inset-y-0 left-0 rounded-full bg-info"
											style={{
												width: `${Math.max(2, r.match.reach_pct)}%`,
											}}
										/>
									</span>
									<span className="w-9 shrink-0 text-right text-sm font-medium text-content tabular-nums">
										{r.match.reach_pct.toFixed(0)}%
									</span>
								</span>
								<span className="w-16 text-right text-sm text-content-muted tabular-nums">
									{r.match.distribution_pct.toFixed(0)}%
								</span>
							</li>
						))}
					</ul>

					{/* A table that silently drops rows reads as a complete one. */}
					{unmatched > 0 && (
						<p className="text-[11px] text-content-subtle">
							{unmatched} selling{" "}
							{unmatched === 1 ? "SKU" : "SKUs"} could not be
							matched to public availability data and{" "}
							{unmatched === 1 ? "is" : "are"} not shown.
						</p>
					)}
				</>
			)}
		</section>
	);
};
