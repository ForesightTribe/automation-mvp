import { Link } from "react-router-dom";
import { ArrowRight, Info } from "lucide-react";
import { usePricePosition } from "../hooks";
import { marketplaceName } from "../../../lib/marketplace";
import { MarketplaceMark } from "../../../components/ui/MarketplaceMark";
import { HoverHint } from "../../../components/ui/HoverHint";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";

/**
 * What we charge against what the rest of the shelf charges, per keyword.
 *
 * Compared PER UNIT (₹/100 ml, ₹/100 g), never per pack: a 750 ml bottle beside a
 * 200 ml can says nothing about who is dearer. Our average is set against the
 * competitor MEDIAN, because a single ₹500 outlier moves a mean and the median
 * is what a shopper actually meets on the shelf.
 *
 * ⚠️ Gated on DISTINCT PRODUCTS, not the API's `*_samples`, which counts
 * listing rows (product × store × scrape day) and overstates the basis by
 * orders of magnitude.
 */
const MIN_OWN_PRODUCTS = 3;
const MIN_COMP_PRODUCTS = 5;

/** ₹ to two decimals — per-unit prices are small and rounding hides the gap. */
const unitPrice = (v) =>
	v == null
		? "—"
		: `₹${v.toLocaleString("en-IN", {
				minimumFractionDigits: 2,
				maximumFractionDigits: 2,
			})}`;

/** One row per keyword and shelf, so a keyword on two shelves opens separately. */
const rowKey = (r) => `${r.marketplace ?? ""}|${r.keyword}`;

export const PricePanel = () => {
	// Split by shelf: a price band is per marketplace, so the same keyword can
	// sit above the competitor set on one and below it on another.
	const { data, isLoading, error, refetch } = usePricePosition({
		byMarketplace: true,
	});

	const rows = (data?.rows ?? [])
		.filter(
			(r) =>
				r.own_avg_unit_price != null &&
				r.comp_median_unit_price > 0 &&
				r.own_products >= MIN_OWN_PRODUCTS &&
				r.comp_products >= MIN_COMP_PRODUCTS,
		)
		.map((r) => ({
			...r,
			multiple: r.own_avg_unit_price / r.comp_median_unit_price,
		}))
		.sort((a, b) => b.multiple - a.multiple);

	// The typical position across keywords, not the mean: with four rows a single
	// keyword at ten times the median would otherwise become the headline.
	const showChannel =
		new Set(rows.map((r) => r.marketplace).filter(Boolean)).size > 1;

	const median = rows.length
		? [...rows].sort((a, b) => a.multiple - b.multiple)[
				Math.floor(rows.length / 2)
			].multiple
		: null;

	return (
		<section className="flex flex-col">
			<div className="flex flex-col gap-5 rounded-xl border border-border bg-card p-6">
				<div className="flex flex-col gap-5">
					{isLoading && <Loading label="Loading prices…" />}
					{error && (
						<ErrorState message={error.message} onRetry={refetch} />
					)}

					{!isLoading && !error && (
						<div className="flex flex-col gap-1">
							<p className="flex items-center gap-1 text-[11px] font-semibold tracking-[0.1em] text-content-subtle uppercase">
								Price position
								{/* What the multiple is measured against, out of
								    the way until asked for. */}
								<HoverHint
									placement="bottom"
									width={250}
									label={
										median == null
											? "No keyword has a comparable set of competitors."
											: "Our average against the market median, per unit."
									}
								>
									<button
										type="button"
										aria-label="How price position is measured"
										className="rounded text-content-subtle transition-colors hover:text-content"
									>
										<Info size={12} aria-hidden />
									</button>
								</HoverHint>
							</p>
							<p className="font-display text-3xl font-bold text-content tabular-nums">
								{median == null ? "—" : `${median.toFixed(1)}×`}
							</p>
						</div>
					)}
				</div>

				{!isLoading && !error && rows.length === 0 && (
					<EmptyState message="No keyword has enough competitor products to compare on." />
				)}

				{rows.length > 0 && (
					<>
						<div className="flex items-baseline gap-3 border-b border-border pb-1.5 text-[11px] tracking-wide text-content-subtle uppercase">
							{showChannel && (
								<span className="w-24 pl-2">Channel</span>
							)}
							<span className="flex-1 pl-2">Keyword</span>
							<span className="w-20 text-right">Ours</span>
							<span className="w-20 text-right">Market</span>
							<span className="w-20 text-right">vs market</span>
						</div>
						<ul className="flex flex-col">
							{rows.map((r) => (
								<li
									key={rowKey(r)}
									className="flex items-center gap-3 border-b border-border py-2 last:border-0"
								>
									{showChannel && (
										<span className="flex w-24 min-w-0 items-center gap-1.5 pl-2 text-sm text-content">
											<MarketplaceMark
												marketplace={{
													slug: r.marketplace,
													name: marketplaceName(
														r.marketplace,
													),
												}}
												size={15}
											/>
											<span className="truncate">
												{marketplaceName(r.marketplace)}
											</span>
										</span>
									)}
									<span className="min-w-0 flex-1 truncate pl-2 text-sm text-content capitalize">
										{r.keyword}
										{r.unit_uom && (
											<span className="ml-1.5 text-[11px] text-content-subtle">
												₹/100 {r.unit_uom}
											</span>
										)}
									</span>
									<span className="w-20 text-right text-sm font-medium text-content tabular-nums">
										{unitPrice(r.own_avg_unit_price)}
									</span>
									<span className="w-20 text-right text-sm text-content-muted tabular-nums">
										{unitPrice(r.comp_median_unit_price)}
									</span>
									<span className="w-20 text-right text-sm font-medium text-content tabular-nums">
										{r.multiple.toFixed(2)}×
									</span>
								</li>
							))}
						</ul>

						<Link
							to="/competition"
							className="mt-4 flex items-center justify-end gap-1 border-t border-border pt-3 text-xs font-medium text-brand hover:underline"
						>
							See price detail
							<ArrowRight size={12} aria-hidden />
						</Link>
					</>
				)}
			</div>
		</section>
	);
};
