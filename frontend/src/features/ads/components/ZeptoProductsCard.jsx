import { useState } from "react";
import { useZeptoProducts } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { formatCurrency, formatNumber } from "../../../lib/format";
import { AD_TYPE_OPTIONS, AdTypeSelect } from "./AdTypeSelect";

const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;

const formatPct = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}%`;

/** Ad spend and return per advertised SKU.
 *
 * Zepto-only — Blinkit's ad plane stops at campaign and keyword level, so there
 * is no equivalent card to merge into.
 *
 * Rows combine every ad type by default, since "what did we spend advertising
 * this SKU" is the question people ask. The dropdown narrows to one type.
 */
export const ZeptoProductsCard = () => {
	const [adType, setAdType] = useState("");

	const { selected } = useMarketplaces();
	const wantsZepto = !selected?.length || selected.includes("zepto");

	const { data, isLoading, error, refetch, isFetching } = useZeptoProducts({
		campaignCategory: adType,
	});
	const rows = data ?? [];

	if (!wantsZepto) return null;

	return (
		<Card
			title="Product performance · Zepto"
			actions={
				<AdTypeSelect
					value={adType}
					onChange={setAdType}
					options={AD_TYPE_OPTIONS}
				/>
			}
		>
			{isLoading && <Loading label="Loading Zepto products…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(rows.length === 0 ? (
					<EmptyState message="No Zepto product data in this window." />
				) : (
					<div
						className={
							isFetching ? "opacity-60 transition-opacity" : ""
						}
					>
						<div className="overflow-auto">
							<table className="w-full border-collapse text-sm">
								<thead className="sticky top-0 z-10 bg-card">
									<tr className="border-b border-border">
										<th className="px-3 py-2 text-left font-medium text-content-subtle">
											Product
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											Impressions
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											Clicks
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											CTR
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											Spend
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											Sales
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											RoAS
										</th>
									</tr>
								</thead>
								<tbody>
									{rows.map((r) => (
										<tr
											key={r.product_variant_id}
											className="border-b border-border/60 last:border-0 hover:bg-muted/50"
										>
											<td className="px-3 py-2">
												<div className="flex items-center gap-2.5">
													{r.image_link && (
														<img
															src={r.image_link}
															alt=""
															loading="lazy"
															className="h-8 w-8 shrink-0 rounded object-cover"
														/>
													)}
													<div className="min-w-0">
														<div className="truncate font-medium text-content">
															{r.product_name ??
																r.product_variant_id}
														</div>
														{/* No ad-type tag here, unlike the category/city/
														    keyword cards: no product has ever run under more
														    than one ad type, so the tag would only repeat what
														    the filter above already controls. Those other cards
														    keep it because a single row there really can sum two
														    types (Cheese, Bengaluru), which no filter can show. */}
														<div className="text-xs text-content-subtle">
															{r.product_category ?? "—"} ·{" "}
															{r.units_sold} orders ·{" "}
															{r.atc} ATC
														</div>
													</div>
												</div>
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatNumber(r.impressions)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatNumber(r.clicks)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content-muted">
												{formatPct(r.ctr)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatCurrency(r.spend)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatCurrency(r.sales)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatRoas(r.roas)}
											</td>
										</tr>
									))}
								</tbody>
							</table>
						</div>
					</div>
				))}
		</Card>
	);
};
