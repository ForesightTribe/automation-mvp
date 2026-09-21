import { ExportButton } from "../../../components/ui/ExportButton";
import { useEffect, useMemo, useState } from "react";
import { useAllKeywordRows } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { Pagination } from "../../../components/ui/Pagination";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { useDateRange } from "../../../context/DateRangeContext";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { downloadCsv, exportName } from "../../../lib/exportTable";
import { formatCurrency, formatNumber } from "../../../lib/format";
import {
	LIFTED_L,
	NUM,
	NameCell,
	SectionExport,
	STICKY_HEAD,
	STICKY_NAME,
	SortHead,
	TD,
	enumLabel,
	useClientSort,
} from "./insightsTable";
import { KeywordDrawer } from "./KeywordDrawer";

const LIMIT = 20;

/**
 * Keywords only, filtered at the query rather than in the browser.
 *
 * The endpoint also returns recommendation rows, where the target is a PLACEMENT Blinkit
 * sells (Retargeting, Similar Products, a banner slot) rather than a search term anyone
 * typed. Those have no match type and no position because they are never matched and never
 * ranked, and they are tuned by moving budget between placements rather than by bidding. So
 * they are a different question, and mixing them in here would put them into this table's
 * totals and its export without belonging to either.
 */
const dash = "—";

/**
 * One line per search term, summed across every campaign that bids on it.
 *
 * ⚠️ The endpoint's grain is campaign × keyword × match type, and this table used to render
 * that grain directly with no campaign column, so "soda" appeared once per campaign (eight
 * times) and read as duplicates. The per-campaign split is still one click away in the
 * drawer. RoAS and ACoS are recomputed from the sums, never averaged. CPM is the
 * impression-weighted mean of Blinkit's reported figures, because Blinkit's CPM is not
 * spend ÷ impressions and deriving it here would disagree with every single-campaign row.
 */
const groupByKeyword = (rows) => {
	const by = new Map();
	for (const r of rows) {
		if (!by.has(r.target)) by.set(r.target, []);
		by.get(r.target).push(r);
	}
	return [...by.entries()].map(([target, members]) => {
		const sum = (pick) => members.reduce((s, r) => s + (pick(r) ?? 0), 0);
		const spend = sum((r) => r.budget_consumed);
		const direct = sum((r) => r.direct_sales);
		const indirect = sum((r) => r.indirect_sales);
		const sales = direct + indirect;
		const impressions = sum((r) => r.impressions);
		const positions = members
			.map((r) => r.most_viewed_position)
			.filter((p) => p != null);
		return {
			target,
			match_types: [
				...new Set(members.map((r) => r.match_type).filter(Boolean)),
			],
			campaigns: new Set(members.map((r) => r.campaign_id)).size,
			budget_consumed: spend,
			direct_sales: direct,
			indirect_sales: indirect,
			total_sales: sales,
			total_roas: spend ? sales / spend : null,
			direct_roas: spend ? direct / spend : null,
			acos: sales ? (spend / sales) * 100 : null,
			impressions,
			cpm: impressions
				? sum((r) => (r.cpm ?? 0) * (r.impressions ?? 0)) / impressions
				: (members[0].cpm ?? null),
			atc: sum((r) => (r.direct_atc ?? 0) + (r.indirect_atc ?? 0)),
			most_viewed_position: positions.length
				? Math.min(...positions)
				: null,
		};
	});
};

const matchText = (types) => types.map(enumLabel).join(", ") || dash;
const roas = (v) => (v == null ? dash : `${v.toFixed(2)}x`);

// ⚠️ NOT `formatPercent`, which takes a FRACTION and multiplies by 100. The ratios computed
// here are already percentages, so passing one through it renders 5188% for 51.88%.
const pctText = (v) => (v == null ? "—" : `${v.toFixed(1)}%`);

/**
 * What each column measures. Direct and indirect is the split that trips people up, so it
 * is spelled out in both places it appears.
 */
/** What each column measures, in plain terms. Definitions, not platform notes. */
const ABOUT = {
	Target: "The search term bid on, totalled across every campaign that runs it. Open it to see each campaign separately.",
	Campaigns: "How many current campaigns bid on this term.",
	Match: "How closely a shopper's search had to match the term for the ad to be eligible.",
	Spend: "The money spent on this keyword.",
	"Direct sales": "Sales of the advertised product itself.",
	"Indirect sales":
		"Sales of the brand's other products bought in the same basket.",
	"Total sales": "Direct and indirect sales added together.",
	RoAS: "Return on ad spend: total sales divided by spend. Higher is better.",
	"Direct RoAS":
		"The same measure counting only sales of the advertised product. The stricter reading.",
	ACoS: "Advertising cost of sale: spend as a percentage of total sales. Lower is better.",
	Impressions: "How many times the ads were shown.",
	CPM: "Cost per thousand impressions: what it costs to be shown a thousand times.",
	"Add to cart":
		"How many times a shopper added a product to their cart after seeing the ad.",
	Position:
		"Where the ad most often appeared in the results. Lower is nearer the top. Blank where no position was recorded.",
};

/**
 * Keyword insights: the same table treatment as Campaign insights, one level down.
 *
 * Search terms only (`target_type=keyword` in getKeywordRowsPage), current campaigns only.
 * One row per term; see groupByKeyword.
 *
 * The rows come from the latest campaign-detail snapshot, which is a window aggregate
 * rather than a daily series, so this table answers "which keywords earn their spend" and
 * not "what happened on Tuesday".
 */
export const KeywordInsightsCard = () => {
	const [page, setPage] = useState(1);
	const [query, setQuery] = useState("");
	const [scrolled, setScrolled] = useState(false);
	const [busy, setBusy] = useState(false);
	const [openTarget, setOpenTarget] = useState(null);

	const { range } = useDateRange();
	const { selected } = useMarketplaces();

	const { data, isLoading, error, refetch, isFetching } = useAllKeywordRows();

	// Search runs over every keyword, not just the page on screen.
	const derived = useMemo(() => {
		const q = query.trim().toLowerCase();
		const grouped = groupByKeyword(data ?? []);
		return q
			? grouped.filter((r) => r.target?.toLowerCase().includes(q))
			: grouped;
	}, [data, query]);

	const ACCESSORS = {
		target: (r) => r.target,
		campaigns: (r) => r.campaigns,
		match: (r) => r.match_types.join(","),
		spend: (r) => r.budget_consumed,
		direct_sales: (r) => r.direct_sales,
		indirect_sales: (r) => r.indirect_sales,
		total_sales: (r) => r.total_sales,
		roas: (r) => r.total_roas,
		direct_roas: (r) => r.direct_roas,
		acos: (r) => r.acos,
		impressions: (r) => r.impressions,
		cpm: (r) => r.cpm,
		atc: (r) => r.atc,
		position: (r) => r.most_viewed_position,
	};
	const { sorted, sort, order, onSort } = useClientSort(
		derived,
		ACCESSORS,
		"spend",
	);

	// Paged in the browser: the whole set is already here, and sorting has to see all of it
	// for "highest spend" to mean highest across the account rather than on this page.
	const pages = Math.max(1, Math.ceil(sorted.length / LIMIT));
	useEffect(() => setPage(1), [range, selected, query, sort, order]);
	const visible = sorted.slice((page - 1) * LIMIT, page * LIMIT);

	const columns = [
		{ header: "Target", value: (r) => r.target },
		{ header: "Campaigns", value: (r) => r.campaigns },
		{ header: "Match", value: (r) => r.match_types.join(", ") },
		{ header: "Spend", value: (r) => r.budget_consumed },
		{ header: "Direct sales", value: (r) => r.direct_sales },
		{ header: "Indirect sales", value: (r) => r.indirect_sales },
		{ header: "Total sales", value: (r) => r.total_sales },
		{ header: "RoAS", value: (r) => r.total_roas },
		{ header: "Direct RoAS", value: (r) => r.direct_roas },
		{
			header: "ACoS %",
			value: (r) => (r.acos == null ? "" : r.acos.toFixed(1)),
		},
		{ header: "Impressions", value: (r) => r.impressions },
		{ header: "CPM", value: (r) => r.cpm },
		{ header: "Add to cart", value: (r) => r.atc },
		{
			header: "Most viewed position",
			value: (r) => r.most_viewed_position ?? "",
		},
	];

	// The download carries every keyword for these filters, in the table's order, not the
	// page on screen. Everything is already loaded, so it costs no request.
	const onExport = async () => {
		setBusy(true);
		try {
			downloadCsv(exportName("keyword-insights", range), [
				{
					title: `Keyword insights, ${range.from} to ${range.to}`,
					columns,
					rows: sorted,
				},
			]);
		} finally {
			setBusy(false);
		}
	};

	const head = (label, key) => (
		<SortHead
			label={label}
			hint={ABOUT[label]}
			sortKey={key}
			sort={sort}
			order={order}
			onSort={onSort}
		/>
	);

	return (
		<div>
			<SectionExport>
				<ExportButton
					onExport={onExport}
					busy={busy}
					disabled={!derived.length}
				/>
			</SectionExport>
			<Card
				title="Keyword insights"
				actions={
					<div className="flex items-center gap-2">
						<input
							type="search"
							value={query}
							onChange={(e) => setQuery(e.target.value)}
							placeholder="Search keyword"
							aria-label="Search keywords"
							className="w-44 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-content transition-colors focus:border-brand focus:outline-none"
						/>
					</div>
				}
			>
				{isLoading && <Loading label="Loading keywords…" />}
				{error && (
					<ErrorState message={error.message} onRetry={refetch} />
				)}
				{!isLoading && !error && sorted.length === 0 && (
					<EmptyState message="No keyword rows for these filters in this window." />
				)}
				{!isLoading && !error && sorted.length > 0 && (
					<div
						className={
							isFetching ? "opacity-60 transition-opacity" : ""
						}
					>
						<div
							onScroll={(e) =>
								setScrolled(e.currentTarget.scrollLeft > 0)
							}
							className="max-h-[70vh] overflow-auto"
						>
							<table
								className="w-full border-collapse"
								style={{ minWidth: 1140 }}
							>
								<thead className="bg-card">
									<tr className="border-b border-border">
										<SortHead
											label="Target"
											hint={ABOUT.Target}
											sortKey="target"
											sort={sort}
											order={order}
											onSort={onSort}
											className={`${STICKY_NAME} ${STICKY_HEAD} ${scrolled ? LIFTED_L : ""} z-30`}
										/>
										{head("Campaigns", "campaigns")}
										{head("Match", "match")}
										{head("Spend", "spend")}
										{head("Direct sales", "direct_sales")}
										{head(
											"Indirect sales",
											"indirect_sales",
										)}
										{head("Total sales", "total_sales")}
										{head("RoAS", "roas")}
										{head("Direct RoAS", "direct_roas")}
										{head("ACoS", "acos")}
										{head("Impressions", "impressions")}
										{head("CPM", "cpm")}
										{head("Add to cart", "atc")}
										{head("Position", "position")}
									</tr>
								</thead>
								<tbody>
									{visible.map((r) => (
										<tr
											key={r.target}
											className="group border-b border-border/60 last:border-0 hover:bg-muted"
										>
											<NameCell
												name={r.target}
												scrolled={scrolled}
												width="14rem"
												onOpen={() =>
													setOpenTarget(r.target)
												}
											/>
											<td className={NUM}>
												{formatNumber(r.campaigns)}
											</td>
											<td
												className={`${TD} text-content-muted`}
											>
												{matchText(r.match_types)}
											</td>
											<td className={NUM}>
												{formatCurrency(
													r.budget_consumed,
												)}
											</td>
											<td className={NUM}>
												{formatCurrency(r.direct_sales)}
											</td>
											<td className={NUM}>
												{formatCurrency(
													r.indirect_sales,
												)}
											</td>
											<td className={NUM}>
												{formatCurrency(r.total_sales)}
											</td>
											<td className={NUM}>
												{roas(r.total_roas)}
											</td>
											<td className={NUM}>
												{roas(r.direct_roas)}
											</td>
											<td className={NUM}>
												{pctText(r.acos)}
											</td>
											<td className={NUM}>
												{formatNumber(r.impressions)}
											</td>
											<td className={NUM}>
												{r.cpm == null
													? dash
													: formatCurrency(r.cpm)}
											</td>
											<td className={NUM}>
												{formatNumber(r.atc)}
											</td>
											<td className={NUM}>
												{r.most_viewed_position == null
													? dash
													: `#${r.most_viewed_position}`}
											</td>
										</tr>
									))}
								</tbody>
							</table>
						</div>
						<Pagination
							page={page}
							pages={pages}
							total={sorted.length}
							limit={LIMIT}
							onChange={setPage}
						/>
					</div>
				)}
				{/* The RAW rows, not the grouped ones: the drawer breaks a keyword out by campaign,
				    and every campaign's row is here, not just those on the visible page. */}
				<KeywordDrawer
					target={openTarget}
					rows={data}
					range={range}
					open={Boolean(openTarget)}
					onClose={() => setOpenTarget(null)}
				/>
			</Card>
		</div>
	);
};
