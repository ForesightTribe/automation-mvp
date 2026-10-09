import { useState } from "react";
import { Store } from "lucide-react";
import { MarketViewProvider, useMarketView } from "./viewContext";
import { MarketFilterBar } from "./components/MarketFilterBar";
import { KeywordChips } from "./components/KeywordChips";
import { ShelfKpis } from "./components/ShelfKpis";
import { ShelfPanel } from "./components/ShelfPanel";
import { KeywordVisibilityCard } from "./components/KeywordVisibilityCard";
import { SkuVarianceCard } from "./components/SkuVarianceCard";
import { StoresDrawer } from "./components/StoresDrawer";
import { Button } from "../../components/ui/Button";
import { PageHeader } from "../../components/ui/PageHeader";

/**
 * Market View — the shelf, as a shopper meets it.
 *
 * Reads top-down rather than demanding a selection first: the chip strip is
 * the watchlist and carries each term's rank, so the weak terms are visible
 * before anything is clicked. "All terms" is a real view, not an empty state.
 *
 * Price sits beside rank throughout, because "who is beating me" and "who is
 * cheaper than me" is one question. Store-level rows — two thousand of them —
 * live behind a button: a reference someone goes looking for, not something in
 * the path of a scan.
 */
const Body = () => {
	const [storesOpen, setStoresOpen] = useState(false);
	const { keyword } = useMarketView();

	return (
		<>
			<MarketFilterBar />

			<KeywordChips />

			<ShelfKpis />

			<ShelfPanel />

			{/* All terms: the comparison across the watchlist is the point.
			    One term: that comparison is already the chip strip above. */}
			{keyword == null && <KeywordVisibilityCard />}

			<SkuVarianceCard />

			<div className="flex justify-center">
				<Button variant="secondary" onClick={() => setStoresOpen(true)}>
					<Store size={14} />
					{keyword
						? `See every dark store for “${keyword}”`
						: "See every dark store"}
				</Button>
			</div>

			<StoresDrawer open={storesOpen} onClose={() => setStoresOpen(false)} />
		</>
	);
};

export const MarketViewPage = () => (
	<MarketViewProvider>
		<div className="flex flex-col gap-6">
			<PageHeader
				title="Market View"
				subtitle="Where you sit on each shelf — rank against rivals, and what they charge for it."
			/>
			<Body />
		</div>
	</MarketViewProvider>
);
