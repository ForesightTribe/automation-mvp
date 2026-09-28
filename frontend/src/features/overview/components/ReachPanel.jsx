import { Info } from "lucide-react";
import { useDistribution, useDistributionByMarketplace } from "../hooks";
import { ChannelSplit } from "./ChannelSplit";
import { HoverHint } from "../../../components/ui/HoverHint";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { formatNumber } from "../../../lib/format";

/**
 * How much of the shelf each SKU is actually on.
 *
 * Two different failures live here and they need different people to fix them:
 *
 *   reach        stores that LIST it      ÷ stores covered   — a listings problem
 *   in stock     stores that HAVE it      ÷ stores that list it — a supply problem
 *
 * Collapsing them into one "availability" number hides which one is happening. A
 * SKU listed in a fifth of the country and in stock in every one of those is not
 * short of supply; it is short of listings, and no amount of replenishment moves
 * it.
 *
 * Sorted by reach ascending, so the SKU with the most ground to gain leads.
 */
/** One qualifying figure beneath the headline: label, value, and an optional
 *  note about how it was measured. */
const Row = ({ label, value, note }) => (
	<div className="flex items-baseline gap-3 border-b border-border py-2 last:border-0">
		<span className="flex-1 text-[11px] font-semibold tracking-wide text-content-subtle uppercase">
			{label}
		</span>
		<span className="w-28 text-right font-display text-base font-bold text-content tabular-nums">
			{value}
		</span>
		<span className="w-36 text-[11px] text-content-subtle">{note}</span>
	</div>
);

export const ReachPanel = () => {
	const { data, isLoading, error, refetch } = useDistribution();
	const { data: byChannel } = useDistributionByMarketplace();

	const skus = [...(data?.skus ?? [])].sort(
		(a, b) => a.reach_pct - b.reach_pct,
	);
	const covered = data?.stores_scraped ?? 0;

	// Weighted by stores, not a mean of percentages: a SKU listed in 300 stores
	// and one listed in 1,700 should not count the same toward "our reach".
	const listed = skus.reduce((s, r) => s + (r.stores_listed ?? 0), 0);
	const inStock = skus.reduce((s, r) => s + (r.stores_in_stock ?? 0), 0);
	const reach =
		skus.length && covered ? listed / (skus.length * covered) : null;
	const stocked = listed ? inStock / listed : null;

	return (
		<section className="flex flex-col">
			<div className="flex flex-col gap-6 rounded-xl border border-border bg-card p-6">
				<div className="flex flex-col gap-5">
					{isLoading && <Loading label="Loading reach…" />}
					{error && (
						<ErrorState message={error.message} onRetry={refetch} />
					)}

					{!isLoading && !error && (
						<>
							<div className="flex flex-col gap-1">
								<p className="flex items-center gap-1 text-[11px] font-semibold tracking-[0.1em] text-content-subtle uppercase">
									Reach
									<HoverHint
										placement="bottom"
										width={260}
										label="Stores that list our SKUs, against every store the scrape covered. Being in stock is counted separately — a SKU can be in stock everywhere it is listed and still reach very little of the country."
									>
										<button
											type="button"
											aria-label="How reach is measured"
											className="rounded text-content-subtle transition-colors hover:text-content"
										>
											<Info size={12} aria-hidden />
										</button>
									</HoverHint>
								</p>
								<p className="font-display text-3xl font-bold text-content tabular-nums">
									{reach == null
										? "—"
										: `${(reach * 100).toFixed(1)}%`}
								</p>
							</div>

							{/* In stock and coverage are in the table below, per
							    channel. This is the fallback for a tenant with no
							    channel breakdown to show. */}
							{(byChannel ?? []).length < 2 && (
								<div className="flex flex-col">
									<Row
										label="In stock where listed"
										value={
											stocked == null
												? "—"
												: `${(stocked * 100).toFixed(1)}%`
										}
									/>
									<Row
										label="Stores covered"
										value={formatNumber(covered)}
									/>
								</div>
							)}
						</>
					)}
				</div>

				{/* Every channel's shelf side by side. Each reach is against
				    that channel's OWN coverage, so these are not shares of one
				    number. */}
				<ChannelSplit
					rows={byChannel ?? []}
					metric="reach"
					label="Reach"
					format="percent"
					showShare={false}
					wide
					extras={[
						{
							label: "In stock",
							width: "w-20",
							value: (m) =>
								m.in_stock?.value == null
									? "—"
									: `${m.in_stock.value.toFixed(1)}%`,
						},
						{
							label: "SKUs",
							width: "w-16",
							value: (m) => formatNumber(m.skus),
						},
						{
							label: "Listings",
							width: "w-20",
							value: (m) => formatNumber(m.listings),
						},
						{
							label: "Stocking",
							width: "w-20",
							value: (m) => formatNumber(m.stores_stocked),
						},
						{
							label: "Covered",
							width: "w-20",
							value: (m) => formatNumber(m.stores_scraped),
						},
					]}
				/>
			</div>
		</section>
	);
};
