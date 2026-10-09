import { useBrandComparison, useKeywordPresence } from "../hooks";
import { useMarketView } from "../viewContext";
import { MetricTile } from "../../../components/ui/MetricTile";

const pct = (v) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);

/**
 * The four numbers that decide whether to read further, for whichever shelf is
 * selected. Rank is shown against the best rival rather than alone: "#23" means
 * nothing until you know someone else is at #15.
 */
export const ShelfKpis = () => {
	const { keyword } = useMarketView();
	const { data: brands } = useBrandComparison();
	const { data: keywords } = useKeywordPresence();

	const rows = brands?.rows ?? [];
	const own = rows.find((r) => r.is_own);
	const bestRival = rows.find((r) => !r.is_own && r.avg_position != null);
	const kwRow = (keywords?.rows ?? []).find((r) => r.keyword === keyword);

	// Cheaper rivals on the same basis — raw rupees across pack sizes is noise.
	const cheaper = own?.avg_unit_price
		? rows.filter(
				(r) =>
					!r.is_own &&
					r.unit_basis === own.unit_basis &&
					r.avg_unit_price != null &&
					r.avg_unit_price < own.avg_unit_price,
			).length
		: null;

	return (
		<div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
			<MetricTile
				label="Your avg rank"
				value={own?.avg_position == null ? "—" : `#${own.avg_position.toFixed(1)}`}
				hint={
					bestRival
						? `Best rival: ${bestRival.brand} at #${bestRival.avg_position.toFixed(1)}`
						: "No rival ranked here"
				}
			/>
			<MetricTile
				label="Stores you're in"
				value={pct(own?.presence_pct)}
				hint={`${brands?.stores_measured ?? 0} stores measured`}
			/>
			<MetricTile
				label="Share of results"
				value={pct(kwRow?.avg_sov_pct ?? null)}
				hint={keyword ? `For “${keyword}”` : "Pick a term for this figure"}
			/>
			<MetricTile
				label="Rivals cheaper than you"
				value={cheaper == null ? "—" : `${cheaper} of ${rows.length - 1}`}
				hint="Compared per unit, same basis only"
			/>
		</div>
	);
};
