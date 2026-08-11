import { useState } from "react";
import { useCities, useDistribution } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { ViewToggle } from "../../../components/ui/ViewToggle";
import { EChart } from "../../../components/charts/EChart";
import { rankedBarOption } from "../../../components/charts/options";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { formatNumber } from "../../../lib/format";

const TABS = [
	{ value: "oos", label: "Out of stock" },
	{ value: "missing", label: "Missing listings" },
];

/** Which dimension the chart ranks. Both datasets are already fetched. */
const DIMENSIONS = [
	{ value: "product", label: "Product" },
	{ value: "location", label: "Location" },
];

/**
 * Bars grade by magnitude so the worst offenders read as urgent without a
 * legend: rose at the top of the range, easing to amber at the bottom.
 */
const severity = (frac) => {
	if (frac >= 0.75) return "#f2707c";
	if (frac >= 0.45) return "#f8a08a";
	if (frac >= 0.25) return "#f9be6a";
	return "#fbd268";
};

/**
 * The work queue — but summarised, not dumped.
 *
 * The first version paginated every (store × product) problem: 3,700+ rows, 300+
 * pages, useless. Nobody works a list like that. Instead it ranks whichever
 * dimension you are acting on — **products** or **places** — biggest first, as a
 * horizontal bar chart. Clicking a bar opens that product's or city's drawer.
 *
 * Two tabs because they are two jobs for two teams: out of stock is a supply chase,
 * a missing listing is a commercial one. Keeping them apart also surfaces which is
 * bigger (all-India on 2026-07-19: 3,707 missing vs 1,206 out of stock) — a single
 * "problems" number would bury that.
 *
 * The summary tiles are limited to what `…/inventory/distribution` and
 * `…/inventory/cities` actually return. A distinct affected-store count and a
 * revenue-at-risk figure are NOT derivable from them: per-SKU store counts
 * double-count a store across products, and revenue at risk needs a units-per-day
 * assumption that exists nowhere in the API.
 */
export const NeedsAttentionCard = ({
	kind = "main",
	onSelectProduct,
	onSelectCity,
}) => {
	const [tab, setTab] = useState("oos");
	const [dimension, setDimension] = useState("product");
	const dist = useDistribution(kind);
	const cities = useCities(kind);

	const isLoading = dist.isLoading || cities.isLoading;
	const error = dist.error || cities.error;
	const refetch = () => {
		dist.refetch();
		cities.refetch();
	};

	const scraped = dist.data?.stores_scraped ?? 0;
	const productKey = tab === "oos" ? "stores_out_of_stock" : "_missing";
	const cityKey = tab === "oos" ? "skus_out_of_stock" : "skus_not_listed";

	const allProducts = (dist.data?.skus ?? [])
		.map((s) => ({ ...s, _missing: scraped - s.stores_listed }))
		.filter((s) => s[productKey] > 0)
		.sort((a, b) => b[productKey] - a[productKey]);

	const allPlaces = (cities.data?.cities ?? [])
		.filter((c) => c[cityKey] > 0)
		.sort((a, b) => b[cityKey] - a[cityKey]);

	const byProduct = dimension === "product";
	const ranked = (byProduct ? allProducts : allPlaces).slice(0, 8);

	const items = ranked.map((r) =>
		byProduct
			? {
					label: r.product_name || r.platform_product_id,
					value: r[productKey],
					id: r.platform_product_id,
				}
			: { label: r.city || "—", value: r[cityKey], id: r.city },
	);

	const totalShelves = allProducts.reduce((a, s) => a + s[productKey], 0);

	// Only metrics the two endpoints can actually support — see the docblock.
	const tiles = [
		{
			value: formatNumber(totalShelves),
			label:
				tab === "oos"
					? "Total out-of-stock shelves"
					: "Total unlisted shelves",
		},
		{
			value: formatNumber(allProducts.length),
			label: "Products affected",
		},
		{
			value: formatNumber(allPlaces.length),
			label: "Cities affected",
		},
	];

	const onBarClick = (params) => {
		const hit = items.find((i) => i.label === params?.name);
		if (!hit?.id) return;
		if (byProduct) onSelectProduct?.(hit.id);
		else onSelectCity?.(hit.id);
	};

	return (
		<Card>
			<div className="mb-4 flex flex-wrap items-start justify-between gap-3">
				<div>
					<h2 className="font-display text-base font-semibold text-content">
						Needs attention
					</h2>
					<p className="text-xs text-content-subtle">
						{tab === "oos"
							? `${formatNumber(totalShelves)} shelves with your product but nothing to sell — chase supply`
							: `${formatNumber(totalShelves)} store shelves that could carry a product of yours — chase a listing`}
					</p>
				</div>
				<div className="flex flex-wrap items-center gap-2">
					<ViewToggle options={TABS} value={tab} onChange={setTab} />
					<ViewToggle
						options={DIMENSIONS}
						value={dimension}
						onChange={setDimension}
					/>
				</div>
			</div>

			{isLoading ? (
				<Loading label="Loading…" />
			) : error ? (
				<ErrorState message={error.message} onRetry={refetch} />
			) : items.length === 0 ? (
				<p className="py-8 text-center text-sm text-content-subtle">
					{tab === "oos"
						? "Everything on shelf is in stock. Nothing to chase."
						: "You're carried for every product in every store we can see."}
				</p>
			) : (
				<>
					<div className="grid max-w-4xl grid-cols-1 gap-4 sm:grid-cols-3">
						{tiles.map((t) => (
							<div
								key={t.label}
								className="rounded-xl border border-[#a8a49e]/25 bg-card p-4 shadow-[0_2px_8px_rgba(0,0,0,0.10)] transition-[transform,box-shadow,border-color] duration-200 ease-out hover:scale-[1.02] hover:border-[#a8a49e] hover:shadow-[0_4px_16px_rgba(0,0,0,0.15)]"
							>
								<p className="font-display text-xl font-bold text-content xl:text-2xl">
									{t.value}
								</p>
								<p className="mt-1 text-xs text-content-subtle">
									{t.label}
								</p>
							</div>
						))}
					</div>

					<div className="mt-14 flex items-baseline justify-between">
						<p className="text-xs font-medium tracking-wide text-content-subtle uppercase">
							{byProduct
								? "Highest-stockout product"
								: "Highest-stockout location"}
						</p>
						<p className="text-[11px] text-content-subtle">
							click a bar to see the stores
						</p>
					</div>

					<EChart
						option={rankedBarOption(items, {
							money: false,
							barColor: severity,
							label: true,
							xName:
								tab === "oos"
									? "Out of stock count"
									: "Missing listing count",
						})}
						onSelect={onBarClick}
						height={360}
						className="mt-2 cursor-pointer"
					/>
				</>
			)}
		</Card>
	);
};
