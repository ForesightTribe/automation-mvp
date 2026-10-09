import { Fragment, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronDown, ChevronRight } from "lucide-react";
import {
	useAllCampaigns,
	useBreakdowns,
	useDailyBudgetUtilisation,
	useKeywordInsights,
	useSov,
	useZeptoSov,
} from "../../hooks";
import { Card } from "../../../../components/ui/Card";
import { Pagination } from "../../../../components/ui/Pagination";
import { Select } from "../../../../components/ui/Select";
import { ViewToggle } from "../../../../components/ui/ViewToggle";
import { ChartTableSwitch } from "../../../../components/ui/ChartTableSwitch";
import { ChannelChips } from "../../../../components/ui/ChannelChips";
import { ExportButton } from "../../../../components/ui/ExportButton";
import { Loading } from "../../../../components/feedback/Loading";
import { ErrorState } from "../../../../components/feedback/ErrorState";
import { EmptyState } from "../../../../components/feedback/EmptyState";
import { useDateRange } from "../../../../context/DateRangeContext";
import { useMarketplaces } from "../../../../context/MarketplaceContext";
import { downloadCsv, exportName } from "../../../../lib/exportTable";
import { marketplaceName } from "../../../../lib/marketplace";
import { formatDate, formatNumber } from "../../../../lib/format";
import {
	LIFTED_L,
	MarketplaceTag,
	SectionExport,
	SortHead,
	STICKY_NAME,
	TD,
	enumLabel,
} from "../insightsTable";
import { BuDetailDrawer } from "../BuDetailDrawer";
import { BuTooltip, useBuTooltip } from "../BuDots";
import { CampaignDrawer } from "../CampaignDrawer";
import { KeywordDrawer } from "../KeywordDrawer";
import { BreakdownDrawer } from "./BreakdownDrawer";
import { EarnChart } from "./EarnChart";
import {
	DEFAULT_COLUMNS,
	TOTAL_KEYS,
	availableColumns,
	columnsFor,
} from "./explorerColumns";
import { ColumnsPicker } from "./ColumnsPicker";
import {
	COVER,
	DIMS,
	DIM_LABEL,
	NOUN,
	breakdownRows,
	campaignRows,
	figures,
	keywordRows,
} from "./explorerModel";

const LIMIT = 20;
const BREAKDOWN_DIMS = new Set(["product"]);
const COMBINE = [
	{ value: "combined", label: "Combined" },
	{ value: "split", label: "Split by marketplace" },
];
// Campaign states, in the order they matter. Each marketplace's own status words are mapped
// onto these by the API (`CampaignRow.state`), so one filter covers every marketplace.
const STATES = [
	["running", "Running"],
	["paused", "Paused"],
	["held", "On hold"],
	["ended", "Ended"],
	["draft", "Draft"],
];
const norm = (s) =>
	String(s ?? "")
		.trim()
		.toLowerCase();

/**
 * What a marketplace's keyword rows cover. Zepto's and Instamart's follow the picker;
 * Blinkit's are an 8-day total it reports, picked on or before the picker's end, so they are
 * named with their own dates (BLINKIT-NOTES B6).
 */
const PeriodNote = ({ periods, rangeTo }) => {
	const blinkit = periods.find((p) => p.platform === "blinkit");
	// Only while Blinkit is read from its 8-day snapshot — per-day rows follow the picker (B6).
	if (!blinkit?.snapshot) return null;
	return (
		<p className="mb-3 text-xs text-content-subtle">
			Blinkit reports keywords as an 8-day total, so its rows don&apos;t
			follow the selected dates:{" "}
			<span className="font-medium text-content-muted">
				{blinkit.end
					? `${formatDate(blinkit.start)} to ${formatDate(blinkit.end)}`
					: `no Blinkit report on or before ${formatDate(rangeTo)}`}
			</span>
			.
		</p>
	);
};

/**
 * Performance explorer — campaigns, keywords, products, categories and cities in ONE table,
 * across every marketplace (2026-10-08, from the Insights lab; replaces the Campaign insights,
 * Keyword insights, Breakdowns and Instamart asset cards).
 *
 * - **Group by** switches what a row is. The chips above the table name which marketplaces in
 *   view report that grouping and which do not, so no table belongs to one marketplace.
 * - **Columns** picks which figures the table shows (remembered in this browser, with a reset);
 *   the order is fixed.
 * - **Combined** adds the same keyword, product or category across marketplaces; a row opens
 *   to one line per marketplace. **Split** lists each marketplace's row on its own.
 * - **Chart** shows where the spend earned (RoAS bands) and the biggest spenders.
 * - Clicking a row opens its detail panel. Campaign rows keep the budget-utilisation dots and
 *   their drawer, the state / type filters, and the `?sort=&order=&status=` links the
 *   Overview's ad insights open the page with.
 *
 * Sorting, searching and paging happen here over the whole set: the rows are all in hand, so
 * every column sorts honestly, derived ones included.
 */
export const PerformanceExplorer = () => {
	const [params] = useSearchParams();
	const [dim, setDim] = useState(() =>
		DIMS.some((d) => d.value === params.get("group"))
			? params.get("group")
			: "campaign",
	);
	const [shown, setShown] = useState(loadColumns);
	const pickColumns = (next) => {
		setShown(next);
		saveColumns(next);
	};
	const [combine, setCombine] = useState("combined");
	const [view, setView] = useState("table");
	const [query, setQuery] = useState("");
	const [sort, setSort] = useState(() => params.get("sort") || "spend");
	const [order, setOrder] = useState(() =>
		params.get("order") === "asc" ? "asc" : "desc",
	);
	const [state, setState] = useState(() =>
		STATES.some(([v]) => v === params.get("status"))
			? params.get("status")
			: "",
	);
	const [type, setType] = useState("");
	const [page, setPage] = useState(1);
	const [open, setOpen] = useState(() => new Set());
	const [detail, setDetail] = useState(null);
	const [buFor, setBuFor] = useState(null);
	const [scrolled, setScrolled] = useState(false);
	const buTip = useBuTooltip();

	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	// null = every channel. Set by the channel chips above the table.
	const [channel, setChannel] = useState(null);
	const reporting = selected.filter((m) => COVER[dim].includes(m));
	const silent = selected.filter((m) => !COVER[dim].includes(m));
	const canCombine = dim !== "campaign" && reporting.length > 1;
	const combined = canCombine && combine === "combined";
	const multi = reporting.length > 1;

	// Only the current grouping's data is asked for. The campaign list is always loaded: it
	// names campaigns in the keyword drawer and it is already shared with other cards.
	const camp = useAllCampaigns();
	const bu = useDailyBudgetUtilisation({
		days: 7,
		enabled: dim === "campaign",
	});
	const kw = useKeywordInsights({ enabled: dim === "keyword" });
	const bd = useBreakdowns({
		dimension: BREAKDOWN_DIMS.has(dim) ? dim : "product",
		enabled: BREAKDOWN_DIMS.has(dim),
	});
	const { data: sovRows } = useSov();
	const { data: zeptoSovRows } = useZeptoSov();

	const source = dim === "campaign" ? camp : dim === "keyword" ? kw : bd;
	const isLoading = source.isLoading;
	const error = source.error ?? null;

	useEffect(() => {
		setPage(1);
	}, [dim, combine, query, sort, order, state, type, range, selected]);

	// Every row for the grouping, before filters.
	const allRows = useMemo(() => {
		if (dim === "campaign") {
			const buByKey = new Map(
				(bu.campaigns ?? []).map((c) => [c.key, c.days]),
			);
			const zeptoSov = new Map(
				(zeptoSovRows ?? []).map((r) => [r.campaign_id, r.sov]),
			);
			return campaignRows(camp.items ?? [], { buByKey, zeptoSov });
		}
		if (dim === "keyword") {
			const blinkitSov = new Map(
				(sovRows ?? []).map((r) => [norm(r.keyword), r.sov]),
			);
			return keywordRows(kw.data?.items ?? [], {
				combine: combined,
				blinkitSov,
			});
		}
		return breakdownRows(bd.data ?? [], { combine: combined });
	}, [
		dim,
		camp.items,
		bu.campaigns,
		zeptoSovRows,
		kw.data,
		sovRows,
		bd.data,
		combined,
	]);

	// Campaign types on the account, for the filter, counted under the state filter.
	const typeOptions = useMemo(() => {
		if (dim !== "campaign") return [];
		const tally = {};
		for (const r of allRows) {
			if (!r.type || (state && r.state !== state)) continue;
			tally[r.type] = (tally[r.type] ?? 0) + 1;
		}
		return Object.entries(tally).sort((a, b) => b[1] - a[1]);
	}, [dim, allRows, state]);
	const stateCounts = useMemo(() => {
		const out = {};
		for (const r of allRows)
			if (r.state) out[r.state] = (out[r.state] ?? 0) + 1;
		return out;
	}, [allRows]);

	const cols = columnsFor(dim, shown);
	const rows = useMemo(() => {
		const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
		let out = allRows.filter((r) => {
			// A row belongs to a channel if that channel contributed to it; in
			// Combined mode one row can span several.
			if (channel && !(r.platforms ?? []).includes(channel)) return false;
			if (dim === "campaign") {
				if (state && r.state !== state) return false;
				if (type && r.type !== type) return false;
			}
			if (!terms.length) return true;
			const hay =
				`${r.name} ${r.campaign?.campaign_id ?? ""}`.toLowerCase();
			return terms.every((t) => hay.includes(t));
		});
		const col = cols.find((c) => c.key === sort);
		const pick =
			sort === "name" ? (r) => r.name : (col?.value ?? ((r) => r.spend));
		const dir = order === "asc" ? 1 : -1;
		out = [...out].sort((a, b) => {
			// Multi-channel rows first while combined — Blinkit outspends the
			// rest, so spend alone buries every other channel. The chosen sort
			// still orders within each group.
			if (combined) {
				const am = (a.platforms?.length ?? 1) > 1 ? 0 : 1;
				const bm = (b.platforms?.length ?? 1) > 1 ? 0 : 1;
				if (am !== bm) return am - bm;
			}
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
		return out;
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [allRows, query, state, type, sort, order, dim, shown, channel, combined]);

	const totals = useMemo(
		() =>
			figures(
				rows.flatMap((r) =>
					(r.campaign ? [r] : r.members.map((m) => m)).map(toLeaf),
				),
			),
		[rows],
	);
	const pages = Math.max(1, Math.ceil(rows.length / LIMIT));
	const visible = rows.slice((page - 1) * LIMIT, page * LIMIT);

	const onSort = (key) => {
		if (key === sort) setOrder((o) => (o === "desc" ? "asc" : "desc"));
		else {
			setSort(key);
			setOrder(key === "name" ? "asc" : "desc");
		}
	};
	const changeDim = (d) => {
		setDim(d);
		setOpen(new Set());
		setQuery("");
		setDetail(null);
		if (!columnsFor(d, shown).some((c) => c.key === sort)) setSort("spend");
	};
	const toggleOpen = (key) =>
		setOpen((s) => {
			const n = new Set(s);
			if (n.has(key)) n.delete(key);
			else n.add(key);
			return n;
		});

	const onExport = () =>
		downloadCsv(exportName(`ads-by-${dim}`, range), [
			{
				title: `Performance by ${DIM_LABEL[dim].toLowerCase()}, ${range.from} to ${range.to}`,
				columns: [
					{ header: DIM_LABEL[dim], value: (r) => r.name },
					{
						header: "Marketplace",
						value: (r) =>
							r.platforms.map(marketplaceName).join(" + "),
					},
					...(dim === "campaign"
						? [
								{
									header: "Campaign ID",
									value: (r) => r.campaign.campaign_id,
								},
								{
									header: "Type",
									value: (r) => enumLabel(r.type),
								},
							]
						: []),
					...cols.map((c) => ({
						header: c.label,
						value: (r) => {
							if (c.csv) return c.csv(r);
							const v = c.value(r);
							return v == null
								? ""
								: typeof v === "number"
									? +v.toFixed(2)
									: v;
						},
					})),
				],
				rows,
			},
		]);

	const ctx = { buTip, onBu: setBuFor };

	const nameCell = (r, isKid = false) => {
		const hasKids = !isKid && r.kids?.length > 1;
		const isOpen = open.has(r.key);
		const sub =
			r.sub ??
			(r.match_types?.length
				? r.match_types.map(enumLabel).join(", ")
				: null);
		return (
			<td
				className={`${TD} ${STICKY_NAME} ${scrolled ? LIFTED_L : ""} group-hover:bg-muted ${isKid ? "bg-surface" : ""}`}
			>
				<div
					className={`flex w-72 items-center gap-2 ${isKid ? "pl-7" : ""}`}
				>
					{!isKid && (
						<button
							type="button"
							aria-label={
								isOpen
									? "Hide each marketplace"
									: "Show each marketplace"
							}
							aria-expanded={isOpen}
							onClick={(e) => {
								e.stopPropagation();
								toggleOpen(r.key);
							}}
							className={`flex h-5 w-5 shrink-0 items-center justify-center rounded text-content-subtle hover:bg-muted hover:text-content ${hasKids ? "" : "invisible"}`}
						>
							{isOpen ? (
								<ChevronDown size={14} />
							) : (
								<ChevronRight size={14} />
							)}
						</button>
					)}
					{(multi || isKid) && (
						<span className="flex shrink-0 gap-0.5">
							{r.platforms.map((m) => (
								<MarketplaceTag key={m} slug={m} compact />
							))}
						</span>
					)}
					{r.image && !isKid && (
						<img
							src={r.image}
							alt=""
							loading="lazy"
							className="h-7 w-7 shrink-0 rounded object-cover"
						/>
					)}
					<div className="min-w-0">
						<div
							className={`truncate font-medium ${isKid ? "text-content-muted" : "text-content group-hover:text-brand group-hover:underline"}`}
							title={r.name}
						>
							{isKid ? marketplaceName(r.platforms[0]) : r.name}
						</div>
						{sub && !isKid && (
							<div className="truncate text-xs text-content-subtle">
								{sub}
							</div>
						)}
					</div>
				</div>
			</td>
		);
	};

	return (
		<div>
			<SectionExport>
				<ExportButton disabled={!rows.length} onExport={onExport} />
			</SectionExport>
			<Card
				title="Performance Explorer"
				actions={
					<ViewToggle
						options={DIMS}
						value={dim}
						onChange={changeDim}
					/>
				}
			>
				{/* The shared channel picker, so this control is the same one
				    the trend and share-of-voice cards use. Channels that report
				    nothing for this dimension are listed after it, greyed. */}
				<div className="mb-3 flex flex-wrap items-center gap-1.5 text-xs text-content-muted">
					{reporting.length > 1 && (
						<ChannelChips
							slugs={reporting}
							value={channel}
							onSelect={setChannel}
							allLabel="All channels"
						/>
					)}
					{silent.map((m) => (
						<span
							key={m}
							title={`${marketplaceName(m)} doesn't report ad performance by ${dim}`}
							className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-border bg-muted py-0.5 pr-2.5 pl-1 text-content-subtle"
						>
							<span className="opacity-50">
								<MarketplaceTag slug={m} compact />
							</span>
							{marketplaceName(m)} · not reported
						</span>
					))}
				</div>

				<div className="mb-3 flex flex-wrap items-center gap-2">
					{canCombine && (
						<ViewToggle
							options={COMBINE}
							value={combine}
							onChange={setCombine}
						/>
					)}
					<span className="flex-1" />
					{dim === "campaign" && (
						<>
							<Select
								ariaLabel="Filter by campaign type"
								value={type}
								onChange={setType}
								options={[
									[
										"",
										"All types",
										formatNumber(
											typeOptions.reduce(
												(n, [, v]) => n + v,
												0,
											),
										),
									],
									...typeOptions.map(([v, n]) => [
										v,
										enumLabel(v),
										formatNumber(n),
									]),
								]}
							/>
							<Select
								ariaLabel="Filter by status"
								value={state}
								onChange={setState}
								options={[
									[
										"",
										"All statuses",
										formatNumber(allRows.length),
									],
									...STATES.map(([v, label]) => [
										v,
										label,
										formatNumber(stateCounts[v] ?? 0),
									]),
								]}
							/>
						</>
					)}
					{/* Columns only shape the table; the chart view has its own fixed figures. */}
					{view === "table" && (
						<ColumnsPicker
							columns={availableColumns(dim)}
							shown={shown}
							onChange={pickColumns}
							onReset={() => pickColumns(DEFAULT_COLUMNS)}
						/>
					)}
					<input
						type="search"
						value={query}
						onChange={(e) => setQuery(e.target.value)}
						placeholder={`Search ${NOUN[dim]}`}
						aria-label={`Search ${NOUN[dim]}`}
						className="w-44 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-content transition-colors focus:border-brand focus:outline-none"
					/>
					{/* Right-aligned, so it sits directly under the
					    Campaign / Keyword / Product toggle in the card header
					    rather than among the controls that change the data. */}
					<ChartTableSwitch value={view} onChange={setView} />
				</div>

				{dim === "keyword" && (
					<PeriodNote
						periods={kw.data?.periods ?? []}
						rangeTo={range.to}
					/>
				)}

				{!reporting.length ? (
					<EmptyState
						message={`None of the selected marketplaces report ad performance by ${dim}.`}
					/>
				) : (
					<>
						{isLoading && (
							<Loading label={`Loading ${NOUN[dim]}…`} />
						)}
						{error && (
							<ErrorState
								message={error.message}
								onRetry={source.refetch}
							/>
						)}
						{!isLoading && !error && rows.length === 0 && (
							<EmptyState
								message={`No ${NOUN[dim]} match these filters in this window.`}
							/>
						)}
						{!isLoading &&
							!error &&
							rows.length > 0 &&
							view === "chart" && (
								<EarnChart
									rows={rows}
									dim={dim}
									multi={multi}
									onOpen={setDetail}
								/>
							)}
						{!isLoading &&
							!error &&
							rows.length > 0 &&
							view === "table" && (
								<>
									<div
										onScroll={(e) =>
											setScrolled(
												e.currentTarget.scrollLeft > 0,
											)
										}
										className="max-h-[70vh] overflow-auto rounded-lg border border-border"
									>
										<table className="w-full min-w-240 border-collapse">
											<thead className="bg-card">
												<tr className="border-b border-border">
													<SortHead
														label={DIM_LABEL[dim]}
														sortKey="name"
														sort={sort}
														order={order}
														onSort={onSort}
														className={`${STICKY_NAME} z-30 ${scrolled ? LIFTED_L : ""}`}
													/>
													{cols.map((c) => (
														<SortHead
															key={c.key}
															label={c.label}
															hint={c.hint}
															sortKey={c.key}
															sort={sort}
															order={order}
															onSort={onSort}
														/>
													))}
												</tr>
											</thead>
											<tbody>
												<tr className="border-b border-border bg-surface font-semibold">
													<td
														className={`${TD} ${STICKY_NAME} bg-surface`}
													>
														All{" "}
														{formatNumber(
															rows.length,
														)}{" "}
														{NOUN[dim]}
													</td>
													{cols.map((c) => (
														<td
															key={c.key}
															className={`${TD} bg-surface text-right tabular-nums`}
														>
															{TOTAL_KEYS.has(
																c.key,
															)
																? c.render(
																		{
																			...totals,
																			platforms:
																				reporting,
																		},
																		ctx,
																	)
																: ""}
														</td>
													))}
												</tr>
												{visible.map((r) => (
													<Fragment key={r.key}>
														<tr
															tabIndex={0}
															onClick={() =>
																setDetail(r)
															}
															onKeyDown={(e) => {
																if (
																	e.key ===
																	"Enter"
																)
																	setDetail(
																		r,
																	);
															}}
															className={`group cursor-pointer border-b border-border/60 hover:bg-muted ${detail?.key === r.key ? "bg-brand-soft/30" : ""}`}
														>
															{nameCell(r)}
															{cols.map((c) => (
																<td
																	key={c.key}
																	className={`${TD} ${c.align === "left" ? "text-left" : "text-right"} tabular-nums`}
																>
																	{c.render(
																		r,
																		ctx,
																	)}
																</td>
															))}
														</tr>
														{open.has(r.key) &&
															r.kids?.map((k) => (
																<tr
																	key={k.key}
																	className="group border-b border-border/60 bg-surface text-[13px]"
																>
																	{nameCell(
																		k,
																		true,
																	)}
																	{cols.map(
																		(c) => (
																			<td
																				key={
																					c.key
																				}
																				className={`${TD} ${c.align === "left" ? "text-left" : "text-right"} tabular-nums`}
																			>
																				{c.render(
																					k,
																					ctx,
																				)}
																			</td>
																		),
																	)}
																</tr>
															))}
													</Fragment>
												))}
											</tbody>
										</table>
									</div>
									{/* The RoAS colours are explained on the RoAS header's hover. */}
									<div className="mt-1">
										<Pagination
											page={page}
											pages={pages}
											total={rows.length}
											limit={LIMIT}
											onChange={setPage}
										/>
									</div>
								</>
							)}
					</>
				)}

				<BuTooltip tip={buTip.tip} />
				<BuDetailDrawer
					open={buFor != null}
					campaign={buFor}
					onClose={() => setBuFor(null)}
				/>
				<CampaignDrawer
					open={detail != null && dim === "campaign"}
					campaign={detail?.campaign}
					onClose={() => setDetail(null)}
				/>
				<KeywordDrawer
					open={detail != null && dim === "keyword"}
					row={dim === "keyword" ? detail : null}
					periods={kw.data?.periods ?? []}
					onClose={() => setDetail(null)}
				/>
				<BreakdownDrawer
					open={detail != null && BREAKDOWN_DIMS.has(dim)}
					row={BREAKDOWN_DIMS.has(dim) ? detail : null}
					dim={dim}
					onClose={() => setDetail(null)}
				/>
			</Card>
		</div>
	);
};

/** A row's figure set as a leaf, for the totals row: campaigns are their own leaf; other
 * groupings total their raw members, so a combined row is not counted twice. */
const toLeaf = (r) =>
	r.campaign
		? {
				spend: r.spend,
				sales: r.sales,
				impressions: r.impressions,
				clicks: r.clicks,
				atc: r.atc,
				orders: r.orders,
			}
		: {
				spend: r.spend,
				sales: r.sales,
				impressions: r.impressions,
				clicks: r.clicks ?? null,
				atc: r.atc ?? null,
				orders: r.orders ?? r.units_sold ?? null,
				cpm: r.cpm ?? null,
			};

/** The viewer's picked columns, remembered in this browser only (a convenience, never state
 * anyone else relies on). Storage can be unavailable or stale, so it falls back to the defaults
 * and drops keys that no longer exist. */
const COLUMNS_KEY = "foresight.insights.explorerColumns";
function loadColumns() {
	try {
		const saved = JSON.parse(localStorage.getItem(COLUMNS_KEY));
		const known = new Set(
			availableColumns("campaign")
				.concat(availableColumns("keyword"))
				.map((c) => c.key),
		);
		if (Array.isArray(saved)) {
			const kept = saved.filter((k) => known.has(k));
			if (kept.length) return kept;
		}
	} catch {
		// fall through to the defaults
	}
	return DEFAULT_COLUMNS;
}
function saveColumns(keys) {
	try {
		localStorage.setItem(COLUMNS_KEY, JSON.stringify(keys));
	} catch {
		// not remembered this time; the table still shows the choice
	}
}
