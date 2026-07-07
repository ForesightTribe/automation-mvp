import { useState } from "react";
import { useDistribution } from "./hooks";
import { InvKpis } from "./components/InvKpis";
import { DistributionCard } from "./components/DistributionCard";
import { AvailabilityHistoryCard } from "./components/AvailabilityHistoryCard";
import { PricingCard } from "./components/PricingCard";
import { AvailabilityListCard } from "./components/AvailabilityListCard";
import { FreshnessBadge } from "../../components/ui/FreshnessBadge";
import { ViewToggle } from "../../components/ui/ViewToggle";

const KIND_OPTIONS = [
	{ value: "main", label: "Main SKUs" },
	{ value: "combo", label: "Combos" },
	{ value: "all", label: "All" },
];

/**
 * Inventory — "where am I actually on the shelf?" The home for the targeted own-SKU
 * scrape (sku_snapshots): distribution %, availability trend, price dispersion, and
 * the store-level out-of-stock list. Combos/multipacks are stocked selectively, so
 * a page-level Main/Combos/All toggle keeps them from being compared against
 * singular main SKUs (default: Main SKUs). All public data is weekly, so the header
 * carries a freshness badge and each section keys on the global window's `days`.
 */
export const InventoryPage = () => {
	const [kind, setKind] = useState("main");
	// Page freshness comes from the distribution `as_of` (same sku_snapshots source).
	const { data: distribution } = useDistribution(kind);

	return (
		<div className="flex flex-col gap-6">
			<div className="flex flex-wrap items-start justify-between gap-3">
				<div>
					<h1 className="font-display text-xl font-bold text-content">
						Inventory
					</h1>
					<p className="text-sm text-content-muted">
						Where you are actually on the shelf.
					</p>
				</div>
				<div className="flex items-center gap-3">
					<ViewToggle
						options={KIND_OPTIONS}
						value={kind}
						onChange={setKind}
					/>
					<FreshnessBadge at={distribution?.as_of} />
				</div>
			</div>

			<InvKpis kind={kind} />

			<DistributionCard kind={kind} />

			<div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
				<AvailabilityHistoryCard kind={kind} />
				<PricingCard kind={kind} />
			</div>

			<AvailabilityListCard kind={kind} />
		</div>
	);
};
