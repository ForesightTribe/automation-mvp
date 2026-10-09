import { useState } from "react";
import { useStores } from "./hooks";
import { InvKpis } from "./components/InvKpis";
import { NeedsAttentionCard } from "./components/NeedsAttentionCard";
import { AvailabilityExplorer } from "./components/AvailabilityExplorer";
import { StoreDrawer } from "./components/StoreDrawer";
import { ProductDrawer } from "./components/ProductDrawer";
import { CityDrawer } from "./components/CityDrawer";
import { AvailabilityHistoryCard } from "./components/AvailabilityHistoryCard";
import { PricingCard } from "./components/PricingCard";
import { FreshnessBadge } from "../../components/ui/FreshnessBadge";
import { ViewToggle } from "../../components/ui/ViewToggle";

const KIND_OPTIONS = [
	{ value: "main", label: "Main SKUs" },
	{ value: "combo", label: "Combos" },
	{ value: "all", label: "All" },
];

/**
 * Availability — "which stores carry your products, and which have run out?", at
 * DARK STORE grain.
 *
 * Three levels of disclosure, not a wall of sibling cards:
 *   1. KPI strip        — four numbers, consistent units, no jargon
 *   2. Needs attention  — the work queue, ranked by product and by place (not dumped)
 *   3. Explorer         — one sortable table, three lenses; clicking a row drills,
 *                         and leaf levels open a drawer (store shelf / product spread)
 *
 * Trend and price sit below as context. Two drawers — store and product — are the
 * mirror-image detail views, opened from the explorer or Needs attention.
 * See docs/darkstores.md for the store model.
 */
export const InventoryPage = () => {
	const [kind, setKind] = useState("main");
	const [storeId, setStoreId] = useState(null);
	const [productId, setProductId] = useState(null);
	const [cityName, setCityName] = useState(null);
	const { data: stores } = useStores({ kind });

	return (
		<div className="flex flex-col gap-6">
			<div className="flex flex-wrap items-start justify-between gap-3">
				<div>
					<h1 className="font-display text-xl font-bold text-content">
						Availability
					</h1>
					<p className="text-sm text-content-muted">
						Which stores carry your products, and which have run out.
					</p>
				</div>
				<div className="flex items-center gap-3">
					<ViewToggle options={KIND_OPTIONS} value={kind} onChange={setKind} />
					<FreshnessBadge at={stores?.as_of} />
				</div>
			</div>

			<InvKpis kind={kind} />

			{/* One always-visible line: the two ideas that drive every number here are
			    easy to conflate, so they're stated plainly rather than in a tooltip. */}
			<p className="-mt-2 text-xs text-content-subtle">
				<span className="font-medium text-content-muted">On shelf</span> means the
				store carries your product.{" "}
				<span className="font-medium text-content-muted">In stock</span> means a
				shopper could buy it right now. A product that was never listed is a sales
				opportunity; one listed but empty is a supply problem.
			</p>

			<NeedsAttentionCard
				kind={kind}
				onSelectProduct={setProductId}
				onSelectCity={setCityName}
			/>

			<AvailabilityExplorer
				kind={kind}
				onSelectStore={setStoreId}
				onSelectProduct={setProductId}
				onSelectCity={setCityName}
			/>

			<div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
				<AvailabilityHistoryCard kind={kind} />
				<PricingCard kind={kind} />
			</div>

			<StoreDrawer merchantId={storeId} kind={kind} onClose={() => setStoreId(null)} />
			<ProductDrawer productId={productId} kind={kind} onClose={() => setProductId(null)} />
			{/* City drawer lists a city's stores; picking one opens the store drawer,
			    continuing city → store → shelf in the same overlay pattern. */}
			<CityDrawer
				city={cityName}
				kind={kind}
				onClose={() => setCityName(null)}
				onSelectStore={(id) => {
					setCityName(null);
					setStoreId(id);
				}}
			/>
		</div>
	);
};
