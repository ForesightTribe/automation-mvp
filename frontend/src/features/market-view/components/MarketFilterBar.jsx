import { useMemo } from "react";
import { useMarketView } from "../viewContext";
import { useStoreExplorer } from "../hooks";
import { Select } from "../../../components/ui/Select";

/**
 * City filter for the whole page.
 *
 * Cities come from the stores actually measured, not a fixed list — offering a
 * city with no scrape behind it would send the reader to an empty page.
 */
export const MarketFilterBar = () => {
	const { city, setCity, keyword, setKeyword } = useMarketView();
	const { data } = useStoreExplorer();

	const cities = useMemo(
		() => [...new Set((data?.rows ?? []).map((r) => r.city).filter(Boolean))].sort(),
		[data],
	);

	return (
		<div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card px-4 py-3">
			<span className="text-xs font-semibold tracking-wide text-content-subtle uppercase">
				City
			</span>
			<Select
				ariaLabel="City"
				value={city ?? ""}
				onChange={(v) => setCity(v || null)}
				options={[
					["", cities.length ? "All cities" : "No cities yet"],
					...cities.map((c) => [c, c]),
				]}
			/>
			{keyword && (
				<button
					type="button"
					onClick={() => setKeyword(null)}
					className="ml-auto rounded-lg border border-border px-2.5 py-1 text-xs font-medium text-content-muted transition-colors hover:text-content"
				>
					Clear “{keyword}”
				</button>
			)}
		</div>
	);
};
