import { useMemo } from "react";

const FIELD =
	"w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-content focus:border-primary focus:outline-none";

/**
 * Pick the keyword to automate from the campaign's own list, with the numbers you need in
 * order to choose.
 *
 * This replaced a native `<datalist>` typeahead, which had the numbers available and showed
 * none of them: you had to already know the keyword's name to see it, and nothing told you
 * what the campaign currently bids or what Blinkit's floor is. Both were being fetched —
 * `bid-context` returns them — and thrown away to build a list of bare strings.
 *
 * Floors vary far more than people expect (₹50 on "mango", ₹400 on "cocktail"), so the
 * floor column is the difference between setting a sane minimum and setting one Blinkit
 * will reject at write time.
 *
 * Typing still works and still accepts a keyword that is NOT on the campaign: a bid write
 * can introduce one, and refusing to type it would remove a capability the form has today.
 * The text simply filters the list as well.
 */
export const KeywordPicker = ({ value, onChange, keywords, scrapedAt, campaignId }) => {
	// One row per keyword, not per (keyword, match_type). Blinkit publishes a range for
	// every match type whether or not the campaign bids it, so prefer the row that carries
	// an actual bid; fall back to EXACT, which is what the floor lookup uses.
	const rows = useMemo(() => {
		const byKeyword = new Map();
		for (const k of keywords ?? []) {
			const prev = byKeyword.get(k.keyword);
			if (!prev || (prev.current_cpm == null && k.current_cpm != null)) {
				byKeyword.set(k.keyword, k);
			}
		}
		return [...byKeyword.values()].sort((a, b) => {
			// Keywords the campaign actually bids first — those are the ones being managed.
			const bid = (b.current_cpm != null) - (a.current_cpm != null);
			if (bid) return bid;
			return (b.keyword_searches ?? 0) - (a.keyword_searches ?? 0);
		});
	}, [keywords]);

	const query = (value ?? "").trim().toLowerCase();
	// The text field doubles as the filter, so a selection would otherwise collapse the list
	// to the row you just picked and make changing your mind awkward. Once the text EXACTLY
	// matches a keyword — which is what selecting one does — stop filtering and show the
	// whole list with that row checked.
	const exact = rows.some((r) => r.keyword.toLowerCase() === query);
	const shown =
		query && !exact ? rows.filter((r) => r.keyword.toLowerCase().includes(query)) : rows;

	return (
		<>
			<input
				value={value}
				onChange={(e) => onChange(e.target.value)}
				placeholder="goli soda"
				className={FIELD}
			/>
			{!campaignId ? null : (
				<div className="mt-2 overflow-hidden rounded-md border border-border">
					<div className="flex items-center justify-between gap-2 border-b border-border bg-muted px-2.5 py-1 text-[11px] uppercase tracking-wide text-content-subtle">
						<span className="pl-6">Keyword</span>
						<span className="flex gap-3">
							<span className="w-14 text-right">Bid</span>
							<span className="w-14 text-right">Floor</span>
							<span className="w-16 text-right">Searches</span>
						</span>
					</div>
					{/* A radio group, not checkboxes: a bid rule automates exactly ONE keyword, and
					    radios make the browser enforce that rather than us. They also give arrow-key
					    navigation and "one of N" to screen readers for free — a set of checkboxes
					    that happen to deselect each other announces the wrong thing entirely. */}
					<div
						role="radiogroup"
						aria-label="Keywords on this campaign"
						className="max-h-52 overflow-y-auto"
					>
						{shown.length === 0 && (
							<p className="px-2.5 py-2 text-xs text-content-subtle">
								{rows.length === 0
									? scrapedAt
										? "No keywords scraped for this campaign yet."
										: "This campaign hasn't been scraped yet — keywords sync nightly."
									: `No keyword matches “${value}”. It will be added to the campaign on the first write.`}
							</p>
						)}
						{shown.map((r) => {
							const selected = r.keyword.toLowerCase() === query;
							return (
								<label
									key={r.keyword}
									className={`flex cursor-pointer items-center justify-between gap-2 px-2.5 py-1.5 text-sm hover:bg-muted ${
										selected ? "bg-muted" : ""
									}`}
								>
									<span className="flex min-w-0 flex-1 items-center gap-2">
										<input
											type="radio"
											name="cm-keyword-pick"
											checked={selected}
											onChange={() => onChange(r.keyword)}
											className="h-4 w-4 shrink-0 accent-primary"
										/>
										<span className="min-w-0 truncate text-content">
											{r.keyword}
											{r.current_cpm == null && (
												<span className="ml-1.5 text-[11px] text-content-subtle">
													not bid yet
												</span>
											)}
										</span>
									</span>
									<span className="flex shrink-0 gap-3 tabular-nums text-xs">
										<span className="w-14 text-right text-content">
											{r.current_cpm != null ? `₹${r.current_cpm}` : "—"}
										</span>
										<span className="w-14 text-right text-content-subtle">
											{r.min_bid != null ? `₹${r.min_bid}` : "—"}
										</span>
										<span className="w-16 text-right text-content-subtle">
											{r.keyword_searches != null
												? r.keyword_searches.toLocaleString("en-IN")
												: "—"}
										</span>
									</span>
								</label>
							);
						})}
					</div>
				</div>
			)}
		</>
	);
};
