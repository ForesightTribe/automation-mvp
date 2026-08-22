import { useEffect, useState } from "react";
import { useZeptoKeywords } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { Pagination } from "../../../components/ui/Pagination";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { AdTypeTag } from "./AdTypeTag";
import { formatCurrency, formatNumber } from "../../../lib/format";

// Matches the Blinkit keywords card, so the two paginate identically.
const LIMIT = 20;

const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;

const formatPct = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}%`;

/** Zepto's analogue of the Blinkit card's target-type filter.
 *
 * Not the same dimension: Blinkit splits keyword vs recommendation rows, which
 * Zepto's keyword table has no equivalent of — every row there is a keyword.
 * Match type is the split that matters here, because Zepto bids the same
 * keyword under several and they perform very differently.
 */
const MATCH_OPTIONS = [
	{ value: "", label: "All match types" },
	{ value: "BROAD", label: "Broad" },
	{ value: "PHRASE", label: "Phrase" },
	{ value: "EXACT", label: "Exact" },
];

/** Zepto keyword performance for the window.
 *
 * A separate card from `KeywordsCard` rather than extra rows in it: Zepto's
 * keywords carry no campaign id and no direct/indirect sales split, so they
 * cannot fill that table's shape — while Zepto reports clicks, CTR and CPC,
 * which Blinkit does not and which would be blank columns there.
 *
 * Hidden entirely when Zepto is filtered out, rather than rendering an empty
 * card next to a populated Blinkit one.
 */
export const ZeptoKeywordsCard = () => {
	const [sort, setSort] = useState("spend");
	const [order, setOrder] = useState("desc");
	const [matchType, setMatchType] = useState("");
	const [page, setPage] = useState(1);

	const { selected } = useMarketplaces();
	useEffect(() => {
		setPage(1);
	}, [matchType, sort, order, selected]);
	const wantsZepto = !selected?.length || selected.includes("zepto");

	const { data, isLoading, error, refetch, isFetching } = useZeptoKeywords({
		sort,
		order,
	});
	// Filtered here rather than server-side: the endpoint returns the whole
	// window's keywords (tens of rows for this account, not thousands), so a
	// round trip per filter change would cost more than it saves.
	const all = (data ?? []).filter(
		(r) => !matchType || r.match_type === matchType,
	);
	// Paged in the browser: the endpoint returns the whole window at once, so
	// there is no server page to ask for.
	const total = all.length;
	const pages = Math.max(1, Math.ceil(total / LIMIT));
	const current = Math.min(page, pages);
	const rows = all.slice((current - 1) * LIMIT, current * LIMIT);

	if (!wantsZepto) return null;

	const onSort = (key) => {
		if (key === sort) {
			setOrder((o) => (o === "desc" ? "asc" : "desc"));
		} else {
			setSort(key);
			setOrder("desc");
		}
	};

	const SortHead = ({ label, sortKey }) => {
		const active = sort === sortKey;
		const arrow = active ? (order === "asc" ? "▲" : "▼") : "";
		return (
			<th className="px-3 py-2 text-right">
				<button
					type="button"
					onClick={() => onSort(sortKey)}
					className={`inline-flex items-center gap-1 font-medium hover:text-content ${
						active ? "text-content" : "text-content-subtle"
					}`}
				>
					{label}
					<span className="text-[10px]" aria-hidden>
						{arrow}
					</span>
				</button>
			</th>
		);
	};

	return (
		<Card
			title="Keyword performance · Zepto"
			actions={
				<select
					value={matchType}
					onChange={(e) => setMatchType(e.target.value)}
					className="rounded-md border border-border bg-card px-2.5 py-1 text-sm text-content focus:outline-none focus:ring-2 focus:ring-brand/30"
				>
					{MATCH_OPTIONS.map((o) => (
						<option key={o.value} value={o.value}>
							{o.label}
						</option>
					))}
				</select>
			}
		>
			{isLoading && <Loading label="Loading Zepto keywords…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(rows.length === 0 ? (
					<EmptyState
						message={
							matchType
								? `No ${matchType.toLowerCase()} match keywords in this period.`
								: "No Zepto keyword data captured yet."
						}
					/>
				) : (
					<div
						className={
							isFetching ? "opacity-60 transition-opacity" : ""
						}
					>
						<div className="overflow-auto">
							<table className="w-full border-collapse text-sm">
								<thead className="sticky top-0 z-10 bg-card">
									<tr className="border-b border-border">
										<th className="px-3 py-2 text-left font-medium text-content-subtle">
											Keyword
										</th>
										<th className="px-3 py-2 text-left font-medium text-content-subtle">
											Match
										</th>
										<SortHead
											label="Impressions"
											sortKey="impressions"
										/>
										<SortHead
											label="Clicks"
											sortKey="clicks"
										/>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											CTR
										</th>
										<SortHead
											label="Spend"
											sortKey="spend"
										/>
										<SortHead
											label="Sales"
											sortKey="sales"
										/>
										<SortHead label="RoAS" sortKey="roas" />
									</tr>
								</thead>
								<tbody>
									{rows.map((r) => (
										<tr
											key={`${r.keyword}-${r.match_type ?? ""}`}
											className="border-b border-border/60 last:border-0 hover:bg-muted/50"
										>
											<td className="px-3 py-2">
												<div className="font-medium text-content">
													{r.keyword}
												</div>
												<div className="flex items-center gap-1.5 text-xs text-content-subtle">
													<AdTypeTag
														types={r.ad_types}
													/>
													<span>
														{r.units_sold} orders ·{" "}
														{r.atc} ATC
													</span>
												</div>
											</td>
											<td className="px-3 py-2 text-content-muted">
												{r.match_type || "—"}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatNumber(r.impressions)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatNumber(r.clicks)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content-muted">
												{formatPct(r.ctr)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatCurrency(r.spend)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatCurrency(r.sales)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatRoas(r.roas)}
											</td>
										</tr>
									))}
								</tbody>
							</table>
						</div>
						<Pagination
							page={current}
							pages={pages}
							total={total}
							limit={LIMIT}
							onChange={setPage}
						/>
					</div>
				))}
		</Card>
	);
};
