import {
	CampaignStatusBadge,
	campaignStatusLabel,
} from "../../../components/ui/CampaignStatusBadge";
import { ExportButton } from "../../../components/ui/ExportButton";
import { useEffect, useMemo, useState } from "react";
import { useAllCampaigns, useDailyBudgetUtilisation } from "../hooks";
import { downloadCsv, exportName } from "../../../lib/exportTable";
import {
	LIFTED_L,
	NUM,
	NameCell,
	SectionExport,
	SortHead,
	STICKY_HEAD,
	STICKY_NAME,
	TD,
	TH,
	enumLabel,
} from "./insightsTable";
import { BuDetailDrawer } from "./BuDetailDrawer";
import { BuDots, BuTooltip, useBuTooltip } from "./BuDots";
import { Card } from "../../../components/ui/Card";
import { Pagination } from "../../../components/ui/Pagination";
import { Select } from "../../../components/ui/Select";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { HoverHint } from "../../../components/ui/HoverHint";
import { useDateRange } from "../../../context/DateRangeContext";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { formatCurrency, formatNumber } from "../../../lib/format";

const LIMIT = 20;
const formatRoas = (v) => (v == null ? "—" : `${v.toFixed(2)}x`);

/**
 * The statuses this page offers as a FILTER, in the order they matter to someone reading
 * a campaign list. The wording and the colours live in the shared badge, so this is only
 * the list of what can be filtered to.
 */
const STATUSES = [
	["ACTIVE", "Active"],
	["STOPPED", "Stopped"],
	["ON_HOLD", "On hold"],
	["COMPLETED", "Ended"],
	["DRAFT", "Draft"],
];

/**
 * "PRODUCT_LISTING" is how Blinkit names a campaign type; "Product Listing" is how a person
 * reads one.
 */
const pctText = (v) => (v == null ? "—" : `${v.toFixed(1)}%`);

/** What every column actually measures, on hover. */
/**
 * What each column measures, in plain terms.
 *
 * Definitions, not platform notes. A reader hovering a column wants to know what the number
 * IS; which marketplace reported it and how it was billed is a different question, and
 * mixing the two makes the short answer hard to find.
 */
const ABOUT = {
	Campaign: "The campaign this row is for. Click it to open its full detail.",
	Type: "What the campaign advertises against. Product listing bids on search terms; recommendation buys placements beside other products.",
	Status: "Whether the campaign is currently running, paused, stopped or finished.",
	"Ad spend": "The money spent on advertising.",
	"Ad sales": "The sales revenue earned from those ads.",
	ROAS: "Return on ad spend: sales divided by spend. 3x means ₹3 back for every ₹1 spent. Higher is better.",
	ACoS: "Advertising cost of sale: spend as a percentage of sales. The inverse of ROAS, so lower is better.",
	AOV: "Average order value: sales divided by the units sold.",
	Impressions: "How many times the ads were shown.",
	"Add to cart":
		"How many times a shopper added the advertised product to their cart.",
	Units: "How many units were sold.",
	CPM: "Cost per thousand impressions: what it costs to be shown a thousand times.",
	"BU 7d":
		"Budget utilisation for each of the last 7 days, oldest on the left: how much of that day's budget was actually spent. Green is 85% and over, amber 60 to 85%, red under 60%, and grey means the campaign did not run that day, which is not the same as underspending. Hover a dot for the figures, click it for the full trend.",
};

/** Every column, including the derived ones the endpoint has no sort key for. */
const ACCESSORS = {
	name: (c) => c.name ?? "",
	type: (c) => c.type ?? "",
	status: (c) => c.status ?? "",
	spend: (c) => c.budget_consumed,
	sales: (c) => c.ad_sales,
	roas: (c) => c.roas,
	acos: (c) => c.acos,
	aov: (c) => c.aov,
	impressions: (c) => c.impressions,
	atc: (c) => c.atc,
	units: (c) => c.quantities_sold,
	cpm: (c) => c.cpm,
	bu: (c) => c.bu,
};

/**
 * Campaign insights: the performance table.
 *
 * Sorting and paging happen HERE, over the whole set fetched in one request, not on the
 * server. The endpoint sorts on four keys only, so add-to-carts, units, ACoS, AOV, CPM and
 * utilisation had no sort at all: ordering a single page of twenty and calling it an order
 * would misdescribe the other 240 rows. With every campaign in hand, every column sorts
 * honestly. Above the endpoint's 500-row ceiling that assumption breaks, and the table says
 * so rather than quietly ranking a subset.
 */
export const CampaignInsightsCard = ({ onOpenCampaign }) => {
	const [sort, setSort] = useState("spend");
	const [order, setOrder] = useState("desc");
	const [status, setStatus] = useState("");
	const [query, setQuery] = useState("");
	const [type, setType] = useState("");
	const [page, setPage] = useState(1);
	const [scrolled, setScrolled] = useState({ left: false });

	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	// AOV's and Units' whole columns are withheld in an Instamart-only view, not just
	// their values — a column of nothing but "—" is worse than no column. In a mixed
	// view both stay visible (blanked per-row already, in `derived`), since a missing
	// figure there reads fine next to real ones from other platforms.
	const instamartOnly = selected?.length === 1 && selected[0] === "instamart";
	// Which campaign's utilisation is being read day by day, or null. The daily data is
	// fetched by the drawer, on open: a column of 20 campaigns must not pay for the detail
	// of 20 campaigns nobody asked about.
	const [buFor, setBuFor] = useState(null);
	// The strip on each row is a fixed 7 days, whatever the page's window is: it is a
	// pacing read, and seven dots is the most a table cell can carry legibly. The drawer
	// is where a longer span is asked for.
	const { campaigns: buRows, dates: buDates } = useDailyBudgetUtilisation({
		days: 7,
	});
	const buTip = useBuTooltip();

	const {
		items,
		total: allCampaigns,
		counts,
		ready: countsReady,
		complete,
		isLoading,
		error,
		refetch,
	} = useAllCampaigns();

	useEffect(() => setPage(1), [sort, order, status, type, range, selected]);
	const buByCampaign = useMemo(
		() => new Map(buRows.map((c) => [c.campaign_id, c.days])),
		[buRows],
	);
	const blankDays = useMemo(
		() =>
			buDates.map((d) => ({
				date: d,
				spend: null,
				allowed: null,
				bu: null,
			})),
		[buDates],
	);

	// The window's length is what a daily budget has to be multiplied by for utilisation.
	const days = useMemo(() => {
		const from = new Date(range.from);
		const to = new Date(range.to);
		return Math.max(1, Math.round((to - from) / 86400000) + 1);
	}, [range]);

	// Filter, derive, sort, then cut the page. Deriving before sorting is what lets a
	// computed column be ordered at all.
	// Every term must match, so "soda pune" narrows rather than widens. Searching name and
	// id together because a campaign is looked up by whichever the reader happens to have.
	const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
	const filtered = useMemo(
		() =>
			items.filter((c) => {
				if (status && c.status !== status) return false;
				if (type && c.type !== type) return false;
				if (!terms.length) return true;
				const hay =
					`${c.name ?? ""} ${c.campaign_id ?? ""}`.toLowerCase();
				return terms.every((t) => hay.includes(t));
			}),
		// eslint-disable-next-line react-hooks/exhaustive-deps
		[items, status, type, query],
	);

	// Types are DERIVED from the rows, unlike statuses: the whole set is in hand, so what is
	// on the account is exactly what the filter should offer, and a new type appears on its
	// own. Counts respect the status filter, so the two controls describe each other.
	const typeOptions = useMemo(() => {
		const tally = {};
		for (const c of items) {
			if (!c.type) continue;
			if (status && c.status !== status) continue;
			tally[c.type] = (tally[c.type] ?? 0) + 1;
		}
		return Object.entries(tally).sort((a, b) => b[1] - a[1]);
	}, [items, status]);

	const derived = useMemo(
		() =>
			filtered.map((c) => {
				const allowed =
					c.daily_budget != null ? c.daily_budget * days : null;
				// Instamart's units-sold figure is unreliable (confirmed
				// 2026-09-30) — withheld here rather than shown wrong, along
				// with the AOV derived from it. Blinkit and Zepto are
				// unaffected. Nulling `quantities_sold` itself (not just aov)
				// means every reader downstream — the Units column, the sort
				// accessor, the CSV export — sees the same blank.
				const isInstamart = c.platform === "instamart";
				const quantitiesSold = isInstamart ? null : c.quantities_sold;
				return {
					...c,
					quantities_sold: quantitiesSold,
					acos: c.ad_sales
						? (c.budget_consumed / c.ad_sales) * 100
						: null,
					aov: quantitiesSold
						? c.ad_sales / quantitiesSold
						: null,
					cpm: c.impressions
						? (c.budget_consumed / c.impressions) * 1000
						: null,
					bu: allowed ? (c.budget_consumed / allowed) * 100 : null,
				};
			}),
		[filtered, days],
	);

	const sorted = useMemo(() => {
		const pick = ACCESSORS[sort];
		if (!pick) return derived;
		const dir = order === "asc" ? 1 : -1;
		return [...derived].sort((a, b) => {
			const x = pick(a);
			const y = pick(b);
			// Blanks sink in both directions: a missing figure is not a small one.
			if (x == null && y == null) return 0;
			if (x == null) return 1;
			if (y == null) return -1;
			return typeof x === "string"
				? dir * x.localeCompare(y)
				: dir * (x - y);
		});
	}, [derived, sort, order]);

	const rows = useMemo(
		() => sorted.slice((page - 1) * LIMIT, page * LIMIT),
		[sorted, page],
	);

	const onSort = (key) => {
		if (key === sort) setOrder((o) => (o === "desc" ? "asc" : "desc"));
		else {
			setSort(key);
			setOrder("desc");
		}
	};

	// No paging to walk any more: the rows are already here, and they leave in the order the
	// screen is showing them, filters and sort included.
	const onExport = () => {
		downloadCsv(exportName("campaign-insights", range), [
			{
				title: `Campaign insights, ${range.from} to ${range.to}`,
				columns: [
					{ header: "Campaign", value: (c) => c.name },
					{ header: "Campaign ID", value: (c) => c.campaign_id },
					{ header: "Type", value: (c) => enumLabel(c.type) },
					{
						header: "Status",
						value: (c) => campaignStatusLabel(c.status),
					},
					{
						header: "Daily budget",
						value: (c) => c.daily_budget ?? "",
					},
					{ header: "Ad spend", value: (c) => c.budget_consumed },
					{ header: "Ad sales", value: (c) => c.ad_sales },
					{ header: "ROAS", value: (c) => c.roas },
					{
						header: "ACoS %",
						value: (c) => (c.acos == null ? "" : c.acos.toFixed(2)),
					},
					...(instamartOnly
						? []
						: [
								{
									header: "AOV",
									value: (c) =>
										c.aov == null ? "" : c.aov.toFixed(2),
								},
							]),
					{ header: "Impressions", value: (c) => c.impressions },
					{ header: "Add to cart", value: (c) => c.atc },
					...(instamartOnly
						? []
						: [{ header: "Units", value: (c) => c.quantities_sold }]),
					{
						header: "CPM",
						value: (c) => (c.cpm == null ? "" : c.cpm.toFixed(2)),
					},
					{
						header: "Budget utilisation %",
						value: (c) => (c.bu == null ? "" : c.bu.toFixed(1)),
					},
				],
				rows: sorted,
			},
		]);
	};

	const onScroll = (e) => {
		const el = e.currentTarget;
		setScrolled({ left: el.scrollLeft > 0 });
	};

	return (
		<div>
			<SectionExport>
				<ExportButton disabled={!sorted.length} onExport={onExport} />
			</SectionExport>
			<Card
				title="Campaign insights"
				actions={
					<div className="flex items-center gap-2">
						{/* Counts sit in the open list, where they help you choose. On the closed
					    trigger they would just be noise beside the answer. */}
						<Select
							ariaLabel="Filter by campaign type"
							value={type}
							onChange={setType}
							options={[
								[
									"",
									"All types",
									countsReady
										? formatNumber(
												typeOptions.reduce(
													(n, [, v]) => n + v,
													0,
												),
											)
										: null,
								],
								...typeOptions.map(([value, n]) => [
									value,
									enumLabel(value),
									formatNumber(n),
								]),
							]}
						/>
						<Select
							ariaLabel="Filter by status"
							value={status}
							onChange={setStatus}
							options={[
								[
									"",
									"All statuses",
									countsReady
										? formatNumber(allCampaigns)
										: null,
								],
								...STATUSES.map(([value, label]) => [
									value,
									label,
									countsReady
										? formatNumber(counts[value] ?? 0)
										: null,
								]),
							]}
						/>
						<input
							type="search"
							value={query}
							onChange={(e) => setQuery(e.target.value)}
							placeholder="Search name or ID"
							aria-label="Search campaigns by name or ID"
							className="w-44 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-content transition-colors focus:border-brand focus:outline-none"
						/>
					</div>
				}
			>
				{isLoading && <Loading label="Loading campaigns…" />}
				{error && (
					<ErrorState message={error.message} onRetry={refetch} />
				)}
				{!isLoading && !error && sorted.length === 0 && (
					<EmptyState message="No campaigns match these filters in this window." />
				)}
				{/* ⚠️ Above the endpoint's 500-row ceiling the table holds a subset, so ordering it
			    would describe the wrong set. Say so rather than rank silently. */}
				{!complete && !isLoading && (
					<p className="mb-2 text-[11px] text-warning">
						This account has {formatNumber(allCampaigns)} campaigns
						and the table can hold 500, so sorting and totals
						describe the 500 largest by spend.
					</p>
				)}
				{!isLoading && !error && sorted.length > 0 && (
					<div>
						{/* ⚠️ Both axes and a capped height, deliberately. `sticky top-0` resolves
						    against the nearest SCROLLING ancestor: with `overflow-x-auto` alone that
						    box never scrolls vertically, so a frozen header has nothing to freeze
						    against and slides away under the page. The table scrolling inside its own
						    height is what makes the header and the first column stay put. */}
						<div
							onScroll={onScroll}
							className="max-h-[70vh] overflow-auto"
						>
							<table
								className="w-full border-collapse"
								style={{ minWidth: 1180 }}
							>
								<thead className="bg-card">
									<tr className="border-b border-border">
										{/* Frozen left AND top, so it needs a higher stack order than either the
										    scrolling headers or the scrolling rows. A fixed width keeps the column
										    from sizing itself to the longest campaign name and squeezing Type. */}
										<th
											className={`${TH} ${STICKY_NAME} ${STICKY_HEAD} ${scrolled.left ? LIFTED_L : ""} z-30 text-center`}
										>
											<HoverHint
												label={ABOUT.Campaign}
												tabIndex={0}
												className="w-full justify-center"
											>
												<span className="decoration-content-subtle/40 decoration-dotted underline-offset-4 hover:decoration-content-subtle hover:underline">
													Campaign
												</span>
											</HoverHint>
										</th>
										<SortHead
											label="Type"
											hint={ABOUT["Type"]}
											sortKey="type"
											sort={sort}
											order={order}
											onSort={onSort}
										/>
										<SortHead
											label="Status"
											hint={ABOUT["Status"]}
											sortKey="status"
											sort={sort}
											order={order}
											onSort={onSort}
										/>
										<SortHead
											label="Ad spend"
											hint={ABOUT["Ad spend"]}
											sortKey="spend"
											sort={sort}
											order={order}
											onSort={onSort}
										/>
										<SortHead
											label="Ad sales"
											hint={ABOUT["Ad sales"]}
											sortKey="sales"
											sort={sort}
											order={order}
											onSort={onSort}
										/>
										<SortHead
											label="ROAS"
											hint={ABOUT["ROAS"]}
											sortKey="roas"
											sort={sort}
											order={order}
											onSort={onSort}
										/>
										<SortHead
											label="ACoS"
											hint={ABOUT["ACoS"]}
											sortKey="acos"
											sort={sort}
											order={order}
											onSort={onSort}
										/>
										{!instamartOnly && (
											<SortHead
												label="AOV"
												hint={ABOUT["AOV"]}
												sortKey="aov"
												sort={sort}
												order={order}
												onSort={onSort}
											/>
										)}
										<SortHead
											label="Impressions"
											hint={ABOUT["Impressions"]}
											sortKey="impressions"
											sort={sort}
											order={order}
											onSort={onSort}
										/>
										<SortHead
											label="Add to cart"
											hint={ABOUT["Add to cart"]}
											sortKey="atc"
											sort={sort}
											order={order}
											onSort={onSort}
										/>
										{!instamartOnly && (
											<SortHead
												label="Units"
												hint={ABOUT["Units"]}
												sortKey="units"
												sort={sort}
												order={order}
												onSort={onSort}
											/>
										)}
										<SortHead
											label="CPM"
											hint={ABOUT["CPM"]}
											sortKey="cpm"
											sort={sort}
											order={order}
											onSort={onSort}
										/>
										<SortHead
											label="BU 7d"
											hint={ABOUT["BU 7d"]}
											sortKey="bu"
											sort={sort}
											order={order}
											onSort={onSort}
										/>
									</tr>
								</thead>
								<tbody>
									{rows.map((c) => {
										const acos = c.ad_sales
											? (c.budget_consumed / c.ad_sales) *
												100
											: null;
										const aov = c.quantities_sold
											? c.ad_sales / c.quantities_sold
											: null;
										const cpm = c.impressions
											? (c.budget_consumed /
													c.impressions) *
												1000
											: null;
										// Seven days of utilisation, or seven blanks where the campaign did
										// not run at all in that week.
										const buDays =
											buByCampaign.get(c.campaign_id) ??
											blankDays;
										return (
											<tr
												key={c.campaign_id}
												className="group border-b border-border/60 last:border-0 hover:bg-muted"
											>
												<NameCell
													name={c.name}
													scrolled={scrolled.left}
													onOpen={() =>
														onOpenCampaign(
															c.campaign_id,
														)
													}
												/>
												<td
													className={`${TD} text-content-muted`}
												>
													{enumLabel(c.type)}
												</td>
												<td className={TD}>
													<CampaignStatusBadge
														status={c.status}
													/>
												</td>
												<td className={NUM}>
													{formatCurrency(
														c.budget_consumed,
													)}
												</td>
												<td className={NUM}>
													{formatCurrency(c.ad_sales)}
												</td>
												<td className={NUM}>
													{formatRoas(c.roas)}
												</td>
												<td className={NUM}>
													{pctText(acos)}
												</td>
												{!instamartOnly && (
													<td className={NUM}>
														{aov == null
															? "—"
															: formatCurrency(aov)}
													</td>
												)}
												<td className={NUM}>
													{formatNumber(
														c.impressions,
													)}
												</td>
												<td className={NUM}>
													{formatNumber(c.atc)}
												</td>
												{!instamartOnly && (
													<td className={NUM}>
														{formatNumber(
															c.quantities_sold,
														)}
													</td>
												)}
												<td className={NUM}>
													{cpm == null
														? "—"
														: formatCurrency(cpm)}
												</td>
												<td
													className={`${TD} text-right`}
												>
													{buDays.length ? (
														<BuDots
															days={buDays}
															campaignName={
																c.name
															}
															onShow={buTip.show}
															onHide={buTip.hide}
															onClick={() =>
																setBuFor(c)
															}
														/>
													) : (
														<span className="text-content-subtle">
															—
														</span>
													)}
												</td>
											</tr>
										);
									})}
								</tbody>
							</table>
						</div>

						{/* ⚠️ All four are load-bearing: `limit` sizes the range, `pages` both labels
					    "Page X of Y" and disables Next at the end, and the callback is `onChange`.
					    Dropping limit/onChange gave "NaN–NaN of 89" with dead buttons; dropping
					    pages gave "Page 4 of nothing" and a Next that never stopped. */}
						<Pagination
							page={page}
							pages={Math.max(
								1,
								Math.ceil(sorted.length / LIMIT),
							)}
							total={sorted.length}
							limit={LIMIT}
							onChange={setPage}
						/>
					</div>
				)}

				<BuTooltip tip={buTip.tip} />
				<BuDetailDrawer
					open={buFor != null}
					campaign={buFor}
					onClose={() => setBuFor(null)}
				/>
			</Card>
		</div>
	);
};
