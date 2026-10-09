import { useKeywordPresence } from "../hooks";
import { useMarketView } from "../viewContext";

const rank = (v) => (v == null ? "—" : `#${Number(v).toFixed(1)}`);

/**
 * The page's primary control: every tracked search term as a chip, "All" first.
 *
 * A strip rather than a dropdown because the terms are the watchlist — seeing
 * them together, each carrying its own rank, is itself the summary. Which term
 * you are losing is visible before you click anything.
 */
export const KeywordChips = () => {
	const { data } = useKeywordPresence();
	const { keyword, setKeyword } = useMarketView();
	const rows = data?.rows ?? [];

	const chip = (active) =>
		`shrink-0 rounded-full border px-3.5 py-1.5 text-sm transition-colors ${
			active
				? "border-brand bg-brand text-on-brand"
				: "border-border bg-card text-content-muted hover:border-content-subtle hover:text-content"
		}`;

	return (
		<div className="flex items-center gap-2 overflow-x-auto pb-1">
			<button
				type="button"
				onClick={() => setKeyword(null)}
				className={chip(keyword == null)}
			>
				All terms
			</button>
			{rows.map((r) => {
				const active = r.keyword === keyword;
				return (
					<button
						key={r.keyword}
						type="button"
						onClick={() => setKeyword(active ? null : r.keyword)}
						className={chip(active)}
						title={`${r.presence_pct}% of stores · avg rank ${rank(r.avg_rank)}`}
					>
						<span className="font-medium">{r.keyword}</span>
						<span
							className={`ml-2 text-xs tabular-nums ${
								active ? "text-on-brand/75" : "text-content-subtle"
							}`}
						>
							{rank(r.avg_rank)}
						</span>
					</button>
				);
			})}
		</div>
	);
};
