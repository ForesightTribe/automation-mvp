import { ExportButton } from "../../../components/ui/ExportButton";
import { useEffect, useMemo, useState } from "react";
import { useKeywords } from "../hooks";
import { getKeywords } from "../api";
import { Card } from "../../../components/ui/Card";
import { Pagination } from "../../../components/ui/Pagination";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { useClient } from "../../../context/ClientContext";
import { useDateRange } from "../../../context/DateRangeContext";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import {
	downloadCsv,
	exportName,
	fetchAllPages,
} from "../../../lib/exportTable";
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
const TARGET_TYPE = "keyword";
const dash = "—";
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
	Target: "The search term the campaign bids on. One term can run in several campaigns, so it can appear more than once; open it to see each campaign separately.",
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
 * Search terms only. See TARGET_TYPE for what is excluded and why.
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

	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();

	useEffect(() => setPage(1), [range, selected]);

	const { data, isLoading, error, refetch, isFetching } = useKeywords({
		page,
		limit: LIMIT,
		targetType: TARGET_TYPE,
		sort: "spend",
		order: "desc",
	});

	const rows = useMemo(() => {
		const items = data?.items ?? [];
		const q = query.trim().toLowerCase();
		return q
			? items.filter((r) => r.target?.toLowerCase().includes(q))
			: items;
	}, [data, query]);

	const derived = useMemo(
		() =>
			rows.map((r) => {
				const sales = (r.direct_sales ?? 0) + (r.indirect_sales ?? 0);
				return {
					...r,
					total_sales: sales,
					atc: (r.direct_atc ?? 0) + (r.indirect_atc ?? 0),
					acos: sales ? (r.budget_consumed / sales) * 100 : null,
				};
			}),
		[rows],
	);

	const ACCESSORS = {
		target: (r) => r.target,
		match: (r) => r.match_type,
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

	const columns = [
		{ header: "Target", value: (r) => r.target },
		{ header: "Campaign ID", value: (r) => r.campaign_id },
		{ header: "Match", value: (r) => r.match_type ?? "" },
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

	// The download carries every keyword for these filters, not the page on screen.
	const onExport = async () => {
		setBusy(true);
		try {
			const all = await fetchAllPages(({ page: p, limit }) =>
				getKeywords(activeClientId, {
					marketplaces: selected,
					page: p,
					limit,
					targetType: TARGET_TYPE,
					sort: "spend",
					order: "desc",
				}),
			);
			const full = all.map((r) => {
				const sales = (r.direct_sales ?? 0) + (r.indirect_sales ?? 0);
				return {
					...r,
					total_sales: sales,
					atc: (r.direct_atc ?? 0) + (r.indirect_atc ?? 0),
					acos: sales ? (r.budget_consumed / sales) * 100 : null,
				};
			});
			downloadCsv(exportName("keyword-insights", range), [
				{
					title: `Keyword insights, ${range.from} to ${range.to}`,
					columns,
					rows: full,
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
							aria-label="Search keywords on this page"
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
									{sorted.map((r, i) => (
										<tr
											key={`${r.campaign_id}-${r.target}-${r.match_type ?? ""}-${i}`}
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
											<td
												className={`${TD} text-content-muted`}
											>
												{enumLabel(r.match_type)}
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
												{formatCurrency(r.cpm)}
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
							pages={data?.pages ?? 1}
							total={data?.total ?? 0}
							limit={LIMIT}
							onChange={setPage}
						/>
					</div>
				)}
				<KeywordDrawer
					target={openTarget}
					rows={derived}
					range={range}
					open={Boolean(openTarget)}
					onClose={() => setOpenTarget(null)}
				/>
			</Card>
		</div>
	);
};
