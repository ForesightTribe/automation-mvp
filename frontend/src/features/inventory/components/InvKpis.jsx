import { useStores } from "../hooks";
import { MetricTile } from "../../../components/ui/MetricTile";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { formatNumber } from "../../../lib/format";

const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);

/**
 * Headline availability KPIs, for a sales / trade-marketing reader.
 *
 * Every tile is ONE consistent unit — a store count, a product count, or a
 * percentage — and never mixes them. An earlier version showed "Missing listings
 * 3,707" next to "Stores 2,004", where 3,707 is store×product gaps, not stores; the
 * two read as a contradiction. Raw gap counts now live in "Needs attention", framed
 * as work to chase, not as headline health.
 *
 * The two percentages answer different questions and are named to avoid the FMCG
 * trap where "distribution" means breadth (the opposite of this codebase's usage):
 *   On shelf — of every store×product slot, how many carry the product (breadth)
 *   In stock — of what IS carried, how much a shopper could buy now (health)
 *
 * In stock reads the same on every marketplace. It briefly did not: Zepto's parser
 * was discarding the sold-out widget, so `in_stock` was true on every stored row and
 * the tile showed a permanent 100%. That was fixed at the source (see
 * zepto/public_data/endpoints.py::PRODUCT_WIDGETS) rather than worked around here, so
 * this tile needs no marketplace-specific behaviour.
 *
 * Denominators are observed, not configured: a store that failed to answer is
 * excluded, not counted as a miss. See docs/darkstores.md.
 */
export const InvKpis = ({ kind = "main", city }) => {
	const { data, isLoading, error, refetch } = useStores({ kind, city });

	if (isLoading) return <Loading label="Loading availability…" />;
	if (error) return <ErrorState message={error.message} onRetry={refetch} />;

	const stores = data?.stores ?? [];
	const range = data?.active_range ?? 0;
	const scraped = data?.stores_scraped ?? 0;
	const nCities = new Set(stores.map((s) => s.city).filter(Boolean)).size;

	const listed = stores.reduce((a, s) => a + s.skus_listed, 0);
	const inStock = stores.reduce((a, s) => a + s.skus_in_stock, 0);
	const slots = range * stores.length;
	const perStore = stores.length ? listed / stores.length : 0;

	return (
		<div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
			<MetricTile
				label="Stores selling you"
				value={formatNumber(scraped)}
				hint={
					nCities
						? `across ${formatNumber(nCities)} ${nCities === 1 ? "city" : "cities"}`
						: undefined
				}
			/>
			<MetricTile
				label="Your products on shelf"
				value={formatNumber(range)}
				hint="found in at least one store"
			/>
			<MetricTile
				label="On shelf"
				value={pct(slots ? (listed / slots) * 100 : null)}
				hint={`avg ${perStore.toFixed(1)} of ${formatNumber(range)} products per store`}
			/>
			<MetricTile
				label="In stock"
				value={pct(listed ? (inStock / listed) * 100 : null)}
				hint="of what stores carry, on hand now"
			/>
		</div>
	);
};
