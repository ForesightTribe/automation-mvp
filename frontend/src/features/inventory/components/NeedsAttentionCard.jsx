import { useState } from "react";
import { useCities, useDistribution } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { ViewToggle } from "../../../components/ui/ViewToggle";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { formatNumber } from "../../../lib/format";

const TABS = [
	{ value: "oos", label: "Out of stock" },
	{ value: "missing", label: "Missing listings" },
];

/**
 * The work queue — but summarised, not dumped.
 *
 * The first version paginated every (store × product) problem: 3,700+ rows, 300+
 * pages, useless. Nobody works a list like that. Instead it ranks the two dimensions
 * a person actually acts on — **which products** and **which places** — so the
 * biggest wins are the first thing you see. Click a product to open its drawer and
 * see the exact stores.
 *
 * Two tabs because they are two jobs for two teams: out of stock is a supply chase,
 * a missing listing is a commercial one. Keeping them apart also surfaces which is
 * bigger (all-India on 2026-07-19: 3,707 missing vs 1,206 out of stock) — a single
 * "problems" number would bury that.
 */
export const NeedsAttentionCard = ({ kind = "main", onSelectProduct, onSelectCity }) => {
	const [chosenTab, setChosenTab] = useState(null);
	const dist = useDistribution(kind);
	const cities = useCities(kind);

	const isLoading = dist.isLoading || cities.isLoading;
	const error = dist.error || cities.error;
	const refetch = () => {
		dist.refetch();
		cities.refetch();
	};

	const scraped = dist.data?.stores_scraped ?? 0;

	const tab = chosenTab ?? "oos";
	const setTab = setChosenTab;

	const productKey = tab === "oos" ? "stores_out_of_stock" : "_missing";
	const cityKey = tab === "oos" ? "skus_out_of_stock" : "skus_not_listed";

	const products = (dist.data?.skus ?? [])
		.map((s) => ({ ...s, _missing: scraped - s.stores_listed }))
		.filter((s) => s[productKey] > 0)
		.sort((a, b) => b[productKey] - a[productKey])
		.slice(0, 8);

	const places = (cities.data?.cities ?? [])
		.filter((c) => c[cityKey] > 0)
		.sort((a, b) => b[cityKey] - a[cityKey])
		.slice(0, 8);

	const maxP = products[0]?.[productKey] || 1;
	const maxC = places[0]?.[cityKey] || 1;

	// "Nothing to chase" and "nothing to look at" are different answers and must not
	// share a message. With the Combos filter on a brand that sells no multipacks
	// there are no products at all, and the healthy copy claimed everything was in
	// stock — reassuring the reader about a shelf that does not exist.
	const noData = (dist.data?.skus ?? []).length === 0;

	const verb = tab === "oos" ? "out of stock in" : "not listed in";
	const totalP = (dist.data?.skus ?? []).reduce((a, s) => a + (tab === "oos" ? s.stores_out_of_stock : scraped - s.stores_listed), 0);

	return (
		<Card>
			<div className="mb-4 flex flex-wrap items-start justify-between gap-3">
				<div>
					<h2 className="font-display text-base font-semibold text-content">
						Needs attention
					</h2>
					<p className="text-xs text-content-subtle">
						{noData
							? "Nothing matches this filter"
							: tab === "oos"
								? `${formatNumber(totalP)} shelves with your product but nothing to sell — chase supply`
								: `${formatNumber(totalP)} store shelves that could carry a product of yours — chase a listing`}
					</p>
				</div>
				<ViewToggle options={TABS} value={tab} onChange={setTab} />
			</div>

			{isLoading ? (
				<Loading label="Loading…" />
			) : error ? (
				<ErrorState message={error.message} onRetry={refetch} />
			) : products.length === 0 && places.length === 0 ? (
				<p className="py-8 text-center text-sm text-content-subtle">
					{noData
						? "No products match this filter, so there is nothing to measure."
						: tab === "oos"
							? "Everything on shelf is in stock. Nothing to chase."
							: "You're carried for every product in every store we can see."}
				</p>
			) : (
				<div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
					<Ranked
						title="Worst products"
						hint="click to see the stores"
						rows={products.map((p) => ({
							key: p.platform_product_id,
							label: p.product_name || p.platform_product_id,
							count: p[productKey],
							frac: p[productKey] / maxP,
							onClick: () => onSelectProduct?.(p.platform_product_id),
						}))}
						suffix={`stores ${verb}`}
					/>
					<Ranked
						title="Worst locations"
						hint="click to see the stores"
						rows={places.map((c) => ({
							key: c.city,
							label: c.city || "—",
							capitalize: true,
							count: c[cityKey],
							frac: c[cityKey] / maxC,
							onClick: c.city ? () => onSelectCity?.(c.city) : undefined,
						}))}
						suffix="shelves affected"
					/>
				</div>
			)}
		</Card>
	);
};

/** A compact ranked list with an inline magnitude bar. */
const Ranked = ({ title, hint, rows, suffix }) => (
	<div>
		<div className="mb-2 flex items-baseline justify-between">
			<p className="text-xs font-medium uppercase tracking-wide text-content-subtle">
				{title}
			</p>
			{hint && <p className="text-[11px] text-content-subtle">{hint}</p>}
		</div>
		<ul className="flex flex-col gap-1.5">
			{rows.map((r) => (
				<li key={r.key}>
					<button
						type="button"
						disabled={!r.onClick}
						onClick={r.onClick}
						className={`group w-full rounded-md px-2 py-1.5 text-left ${
							r.onClick ? "cursor-pointer hover:bg-surface-subtle" : "cursor-default"
						}`}
					>
						<div className="flex items-baseline justify-between gap-3 text-sm">
							<span className={`truncate text-content ${r.capitalize ? "capitalize" : ""}`}>
								{r.label}
							</span>
							<span className="shrink-0 tabular-nums text-content-muted">
								{formatNumber(r.count)}
								<span className="ml-1 text-xs text-content-subtle">{suffix}</span>
							</span>
						</div>
						<div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-surface-subtle">
							<div
								className="h-full rounded-full bg-danger/70"
								style={{ width: `${Math.max(r.frac * 100, 2)}%` }}
							/>
						</div>
					</button>
				</li>
			))}
		</ul>
	</div>
);
