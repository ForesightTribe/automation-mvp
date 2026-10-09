import { useMemo, useState } from "react";
import { ViewToggle } from "../../../components/ui/ViewToggle";
import { useAllKeywordMetrics, useCampaignNames, useCampaigns } from "../hooks";
import { Loading } from "../../../components/feedback/Loading";
import { Button } from "../../../components/ui/Button";
import { formatCurrency, formatNumber } from "../../../lib/format";
import { useAutomationMarketplace } from "../../../context/MarketplaceContext";
import { useDateRange } from "../../../context/DateRangeContext";
import { bidUnit } from "../../../lib/marketplaces";

const TH =
	"whitespace-nowrap px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-content-subtle";
const TD = "whitespace-nowrap px-3 py-2 text-sm text-content";
const NUM = `${TD} text-right tabular-nums`;
const NUM_H = `${TH} text-right`;

// Frozen identity column — see CampaignPickerList for why each sticky cell paints its own
// background and why the shadow only appears once the body is actually scrolled.
const STICKY_PICK = "sticky left-0 z-10 w-10 overflow-hidden";
// ⚠️ Frozen while the row scrolls under it: it has to clip, and its fill has to be
// opaque, or the scrolling columns read through and over it.
const STICKY_NAME = "sticky left-10 z-10 overflow-hidden";
const EDGE = "border-r border-border transition-shadow";
const EDGE_LIFTED = "shadow-[6px_0_10px_-6px_rgba(0,0,0,0.35)]";

const BY_KEYWORD = "keyword";
const BY_CAMPAIGN = "campaign";

const ratio = (num, den) => (den ? num / den : null);
const fmtRoas = (v) => (v == null ? "—" : `${v.toFixed(2)}x`);

// Active campaigns first, then by spend. The account reuses names ("Soda KW [Bengaluru]"
// is two current campaigns, both stopped, beside an active one in another city), so the
// one a rule should usually go on has to be the one at the top.
const byActiveThenSpend = (a, b) =>
	(b.status === "ACTIVE") - (a.status === "ACTIVE") ||
	b.metrics.spend - a.metrics.spend;

// Catalogue mode has no spend to rank by, so active first and then alphabetical.
const byActiveThenName = (a, b) =>
	(b.status === "ACTIVE") - (a.status === "ACTIVE") ||
	a.label.localeCompare(b.label);

/** Status + ID under a campaign's name. The name alone cannot tell two same-named
 *  campaigns apart, and a bid rule binds to exactly one of them. */
const CampaignTag = ({ id, status }) => (
	<span className="inline-flex items-center gap-1.5 text-[11px] text-content-subtle">
		{status && (
			<span
				className={`rounded-full px-1.5 py-px font-medium ${
					status === "ACTIVE"
						? "bg-success-soft text-success"
						: "bg-muted text-content-muted"
				}`}
			>
				{status}
			</span>
		)}
		ID {id}
	</span>
);

/** Sum a group of (campaign, keyword) rows into one line. ROAS and CPM are recomputed
 *  from the totals rather than averaged — averaging ratios weights a ₹10 keyword the
 *  same as a ₹10,000 one. */
const aggregate = (rows) => {
	const t = rows.reduce(
		(a, r) => ({
			impressions: a.impressions + (r.impressions ?? 0),
			spend: a.spend + (r.budget_consumed ?? 0),
			direct_sales: a.direct_sales + (r.direct_sales ?? 0),
			indirect_sales: a.indirect_sales + (r.indirect_sales ?? 0),
			direct_atc: a.direct_atc + (r.direct_atc ?? 0),
			indirect_atc: a.indirect_atc + (r.indirect_atc ?? 0),
			new_users: a.new_users + (r.new_users_acquired ?? 0),
		}),
		{
			impressions: 0,
			spend: 0,
			direct_sales: 0,
			indirect_sales: 0,
			direct_atc: 0,
			indirect_atc: 0,
			new_users: 0,
		},
	);
	const positions = rows
		.map((r) => r.most_viewed_position)
		.filter((p) => p != null);
	return {
		...t,
		total_sales: t.direct_sales + t.indirect_sales,
		direct_roas: ratio(t.direct_sales, t.spend),
		total_roas: ratio(t.direct_sales + t.indirect_sales, t.spend),
		cpm: t.impressions ? (t.spend / t.impressions) * 1000 : null,
		// Best rank held anywhere in the group — the optimistic end, since that is the
		// position a bid rule would be defending.
		position: positions.length ? Math.min(...positions) : null,
	};
};

const MetricHeaders = () => (
	<>
		<th className={NUM_H}>Direct Sales</th>
		<th className={NUM_H}>Total Sales</th>
		<th className={NUM_H}>Indirect Sales</th>
		<th className={NUM_H}>Ad Spend</th>
		<th className={NUM_H}>Direct ROAS</th>
		<th className={NUM_H}>Total ROAS</th>
		<th className={NUM_H}>Impressions</th>
		<th className={NUM_H}>Avg CPM</th>
		<th className={NUM_H}>Position</th>
		<th className={NUM_H}>Direct ATC</th>
		<th className={NUM_H}>Indirect ATC</th>
		<th className={NUM_H}>New Users</th>
	</>
);

const MetricCells = ({ m }) => (
	<>
		<td className={NUM}>{formatCurrency(m.direct_sales)}</td>
		<td className={NUM}>{formatCurrency(m.total_sales)}</td>
		<td className={NUM}>{formatCurrency(m.indirect_sales)}</td>
		<td className={NUM}>{formatCurrency(m.spend)}</td>
		<td className={NUM}>{fmtRoas(m.direct_roas)}</td>
		<td className={NUM}>{fmtRoas(m.total_roas)}</td>
		<td className={NUM}>{formatNumber(m.impressions)}</td>
		<td className={NUM}>{m.cpm == null ? "—" : formatCurrency(m.cpm)}</td>
		<td className={NUM}>{m.position == null ? "—" : `#${m.position}`}</td>
		<td className={NUM}>{formatNumber(m.direct_atc)}</td>
		<td className={NUM}>{formatNumber(m.indirect_atc)}</td>
		<td className={NUM}>{formatNumber(m.new_users)}</td>
	</>
);

/**
 * Catalogue mode — the rows come from the marketplace's campaign catalogue (Zepto): which
 * match types are bid, the live bid and the marketplace's floor. On Zepto each row also
 * carries its keyword performance over the navbar's dates (P43, from the per-campaign
 * keyword report), summed here — ratios rebuilt from the sums, never averaged. `m` here is
 * `catalogSummary(rows)`, not `aggregate(rows)`.
 */
const catalogSummary = (rows) => {
	const bids = rows.map((r) => r.bid).filter((v) => v != null);
	const floors = rows.map((r) => r.min_bid).filter((v) => v != null);
	const range = (v) =>
		!v.length
			? null
			: Math.min(...v) === Math.max(...v)
				? formatCurrency(Math.min(...v))
				: `${formatCurrency(Math.min(...v))}–${formatCurrency(Math.max(...v))}`;
	const sum = (k) => rows.reduce((a, r) => a + (r[k] ?? 0), 0);
	const spend = sum("budget_consumed");
	const sales = sum("total_sales");
	const impressions = sum("impressions");
	const clicks = sum("clicks");
	return {
		matchTypes: [...new Set(rows.map((r) => r.match_type))]
			.sort()
			.join(" · "),
		bid: range(bids),
		floor: range(floors),
		spend,
		sales,
		orders: sum("orders"),
		direct_orders: sum("direct_orders"),
		indirect_orders: sum("indirect_orders"),
		impressions,
		clicks,
		atc: sum("atc"),
		roas: ratio(sales, spend),
		ctr: impressions ? (clicks / impressions) * 100 : null,
		cpc: ratio(spend, clicks),
	};
};

// Zepto bids per CLICK, so CPC is the cost column that matters (Blinkit's is CPM). There is
// no direct/indirect SALES split on Zepto — only orders split into the advertised product
// (direct) and the brand's other products (halo) — and no ad position or new-user count.
const PerfHeaders = () => (
	<>
		<th className={NUM_H}>Total Sales</th>
		<th className={NUM_H}>Ad Spend</th>
		<th className={NUM_H}>ROAS</th>
		<th className={NUM_H}>Orders</th>
		<th className={NUM_H}>Direct Orders</th>
		<th className={NUM_H}>Indirect Orders</th>
		<th className={NUM_H}>Impressions</th>
		<th className={NUM_H}>Clicks</th>
		<th className={NUM_H}>CTR</th>
		<th className={NUM_H}>Avg CPC</th>
		<th className={NUM_H}>ATC</th>
	</>
);

const PerfCells = ({ m }) => (
	<>
		<td className={NUM}>{formatCurrency(m.sales)}</td>
		<td className={NUM}>{formatCurrency(m.spend)}</td>
		<td className={NUM}>{fmtRoas(m.roas)}</td>
		<td className={NUM}>{formatNumber(m.orders)}</td>
		<td className={NUM}>{formatNumber(m.direct_orders)}</td>
		<td className={NUM}>{formatNumber(m.indirect_orders)}</td>
		<td className={NUM}>{formatNumber(m.impressions)}</td>
		<td className={NUM}>{formatNumber(m.clicks)}</td>
		<td className={NUM}>{m.ctr == null ? "—" : `${m.ctr.toFixed(2)}%`}</td>
		<td className={NUM}>{m.cpc == null ? "—" : formatCurrency(m.cpc)}</td>
		<td className={NUM}>{formatNumber(m.atc)}</td>
	</>
);

const CatalogHeaders = ({ unit, perf }) => (
	<>
		{perf && <PerfHeaders />}
		<th className={TH}>Match</th>
		<th className={NUM_H}>Current bid ({unit.code})</th>
		<th className={NUM_H}>Min bid ({unit.code})</th>
	</>
);

const CatalogCells = ({ m, perf }) => (
	<>
		{perf && <PerfCells m={m} />}
		<td className={TD}>{m.matchTypes || "—"}</td>
		<td className={NUM}>{m.bid ?? "—"}</td>
		<td className={NUM}>{m.floor ?? "—"}</td>
	</>
);

/**
 * The drill-in: the other axis of whatever row was clicked, over a modal.
 *
 * Single-select: a bid rule targets exactly one (campaign, keyword) pair, so clicking a row
 * IS the choice and the modal closes on it. A separate commit step buys nothing when there
 * is only ever one thing to commit, and it leaves a chosen row sitting there looking done
 * while the dialog waits for a second click.
 *
 * `freeText` turns the search box into an answer of its own: a campaign can be told to bid
 * on a keyword it has never run, and that keyword by definition has no row here to click.
 */
const DrillModal = ({
	title,
	subtitle,
	rows,
	initial,
	freeText,
	onApply,
	onClose,
	catalog = false,
	perf = false,
	unit,
}) => {
	const [search, setSearch] = useState("");
	const [scrolled, setScrolled] = useState(false);
	const edge = `${EDGE} ${scrolled ? EDGE_LIFTED : ""}`;

	const q = search.trim();
	const shown = q
		? rows.filter((r) => r.label.toLowerCase().includes(q.toLowerCase()))
		: rows;
	const offerTyped =
		freeText &&
		q.length > 0 &&
		!shown.some((r) => r.label.toLowerCase() === q.toLowerCase());

	return (
		<div className="fixed inset-0 z-60 flex items-center justify-center bg-black/40 p-6">
			<div className="flex max-h-[85vh] w-full max-w-6xl flex-col rounded-lg border border-border bg-card">
				<header className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-4">
					<h3 className="font-display text-base font-semibold text-content">
						{title} <span className="text-brand">“{subtitle}”</span>
					</h3>
					{/* Singular on purpose: "n selected" is multi-select vocabulary, and a bid rule
					    binds exactly one pair. */}
					<span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-brand">
						choose one
					</span>
					<input
						type="search"
						value={search}
						onChange={(e) => setSearch(e.target.value)}
						placeholder={
							freeText
								? "Search, or type a new keyword"
								: "Search"
						}
						className="ml-auto w-60 rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-content focus:border-brand focus:outline-none"
					/>
				</header>

				{offerTyped && (
					<button
						type="button"
						onClick={() =>
							onApply({ keyword: q, campaign_id: null })
						}
						className="flex items-center gap-2 border-b border-border bg-info-soft px-5 py-2.5 text-left text-sm text-content hover:bg-muted"
					>
						<span className="text-info">+</span>
						Bid on “{q}”, a keyword this campaign has not run yet
					</button>
				)}

				<div
					onScroll={(e) =>
						setScrolled(e.currentTarget.scrollLeft > 0)
					}
					className="flex-1 overflow-auto"
				>
					<table
						className="w-full border-collapse"
						style={{ minWidth: catalog && !perf ? 720 : 1180 }}
					>
						<thead className="bg-card">
							<tr className="border-b border-border">
								<th
									className={`${TH} ${STICKY_PICK} bg-card`}
									aria-label="Selected"
								/>
								<th
									className={`${TH} ${STICKY_NAME} ${edge} bg-card`}
								>
									{title.includes("keyword for")
										? "Keyword"
										: "Campaign"}
								</th>
								{catalog ? (
									<CatalogHeaders unit={unit} perf={perf} />
								) : (
									<MetricHeaders />
								)}
							</tr>
						</thead>
						<tbody>
							{shown.length === 0 && !offerTyped && (
								<tr>
									<td
										colSpan={14}
										className="p-3 text-sm text-content-subtle"
									>
										Nothing matches.
									</td>
								</tr>
							)}
							{shown.map((r) => {
								const on = initial === r.key;
								// A campaign automations may not touch (Zepto Display / auto-bid)
								// stays listed — someone may be looking for it — but cannot be
								// chosen, and says why rather than failing on save.
								const blocked = r.notAutomatable;
								const cellBg = on
									? "bg-muted"
									: blocked
										? "bg-card"
										: "bg-card group-hover:bg-muted";
								return (
									<tr
										key={r.key}
										onClick={() => !blocked && onApply(r)}
										aria-selected={on}
										aria-disabled={Boolean(blocked)}
										title={blocked || undefined}
										className={`group border-b border-border/60 last:border-0 ${
											blocked
												? "cursor-not-allowed opacity-50"
												: on
													? "cursor-pointer bg-muted shadow-[inset_3px_0_0_0_var(--color-brand)]"
													: "cursor-pointer hover:bg-muted"
										}`}
									>
										<td
											className={`${TD} ${STICKY_PICK} ${cellBg} text-brand`}
										>
											{on ? "✓" : ""}
										</td>
										<td
											className={`${TD} ${STICKY_NAME} ${edge} ${cellBg} max-w-[20rem]`}
											title={r.label}
										>
											<div className="truncate font-medium">
												{r.label}
											</div>
											{r.isCampaign && (
												<CampaignTag
													id={r.campaign_id}
													status={r.status}
												/>
											)}
											{blocked && (
												<div className="truncate text-[11px] text-content-subtle">
													{blocked}
												</div>
											)}
										</td>
										{catalog ? (
											<CatalogCells
												m={r.metrics}
												perf={perf}
											/>
										) : (
											<MetricCells m={r.metrics} />
										)}
									</tr>
								);
							})}
						</tbody>
					</table>
				</div>

				<footer className="flex justify-end gap-2 border-t border-border px-5 py-4">
					<Button variant="secondary" size="sm" onClick={onClose}>
						Cancel
					</Button>
				</footer>
			</div>
		</div>
	);
};

/**
 * Choose what to bid on — the same data pivoted two ways, as in the design.
 *
 *   Keyword × Campaigns — one row per keyword, drilling into the campaigns that run it
 *   Campaign × Keywords — one row per campaign, drilling into the keywords it carries
 *
 * Both end at the same place: a bid rule needs exactly ONE (campaign, keyword) pair, so the
 * drill-in is single-select.
 *
 * Every number comes from one `/ads/keywords` response, grouped client-side — switching
 * pivots costs no request. On a marketplace with no keyword performance (Zepto) the rows
 * come from the campaign catalogue instead and the columns are bid, floor and match type. Reach and AOV are the two columns from the design with no source
 * at all, so they are absent rather than blank.
 */
export const KeywordPicker = ({ campaignId, keyword, matchType, onChange }) => {
	const { data: rows, isLoading, isComplete, total } = useAllKeywordMetrics();
	const { marketplace } = useAutomationMarketplace();
	const unit = bidUnit(marketplace);
	// No keyword performance on this marketplace — rows come from the campaign catalogue
	// (see useAllKeywordMetrics), so the columns and the drill-in change with them.
	const catalog = marketplace !== "blinkit";
	// Zepto's catalogue rows carry keyword performance for the navbar's dates (P43); a
	// marketplace whose rows do not keeps the bid/floor-only columns.
	const perf = catalog && (rows ?? []).some((r) => r.budget_consumed != null);
	const { range } = useDateRange();
	const { data: campaigns } = useCampaignNames();
	const { data: selectableCampaigns } = useCampaigns();
	const [view, setView] = useState(BY_KEYWORD);
	const [search, setSearch] = useState("");
	const [drill, setDrill] = useState(null);
	const [scrolled, setScrolled] = useState(false);
	const edge = `${EDGE} ${scrolled ? EDGE_LIFTED : ""}`;

	const nameOf = useMemo(() => {
		const m = new Map(
			(campaigns ?? []).map((c) => [c.campaign_id, c.name]),
		);
		return (id) => m.get(id) ?? `Campaign ${id}`;
	}, [campaigns]);

	// Only campaigns the picker may bind to, with their status. `/ads/campaigns` applies
	// `recent_only`, which hides a stale pre-migration account's dead campaigns. The keyword
	// rows are fetched with the same flag, so this filter is the second line: it keeps both
	// lists agreeing if the two scrapes ever drift apart.
	const statusOf = useMemo(
		() =>
			new Map(
				(selectableCampaigns ?? []).map((c) => [
					c.campaign_id,
					c.status,
				]),
			),
		[selectableCampaigns],
	);
	// Why a campaign cannot carry an automation, from the same `/ads/campaigns` rows (ZC-D3).
	// The catalogue keyword rows carry it too; either source is enough to block the pick.
	const refusalOf = useMemo(
		() =>
			new Map(
				(selectableCampaigns ?? [])
					.filter((c) => c.automatable === false)
					.map((c) => [c.campaign_id, c.not_automatable_reason]),
			),
		[selectableCampaigns],
	);

	const groups = useMemo(() => {
		const by = new Map();
		for (const r of rows ?? []) {
			if (statusOf.size && !statusOf.has(r.campaign_id)) continue;
			const key = view === BY_KEYWORD ? r.target : r.campaign_id;
			if (!by.has(key)) by.set(key, []);
			by.get(key).push(r);
		}
		const q = search.trim().toLowerCase();
		return [...by.entries()]
			.map(([key, members]) => ({
				key,
				label: view === BY_KEYWORD ? String(key) : nameOf(key),
				status: view === BY_CAMPAIGN ? statusOf.get(key) : undefined,
				members,
				metrics: catalog ? catalogSummary(members) : aggregate(members),
			}))
			.filter(
				(g) =>
					!q ||
					g.label.toLowerCase().includes(q) ||
					// Campaign IDs are searchable: the ID is what tells same-named ones apart.
					(view === BY_CAMPAIGN && String(g.key).includes(q)),
			)
			.sort(
				catalog && !perf
					? byActiveThenName
					: view === BY_CAMPAIGN
						? byActiveThenSpend
						: (a, b) => b.metrics.spend - a.metrics.spend,
			);
	}, [rows, view, search, nameOf, statusOf, catalog, perf]);

	if (isLoading) return <Loading label="Loading keywords…" />;

	const selectedKey = view === BY_KEYWORD ? keyword : campaignId;

	/**
	 * Catalogue mode keeps each MATCH TYPE as its own drill row. On Zepto one keyword can be
	 * bid as EXACT, PHRASE and BROAD in the same campaign, each its own bid with its own
	 * floor, and a rule binds exactly one of them — so the match type is part of the choice.
	 */
	const catalogDrillRows = (group) =>
		group.members
			.map((r) => {
				const other = view === BY_KEYWORD ? r.campaign_id : r.target;
				return {
					key: `${other}|${r.match_type}`,
					label: `${view === BY_KEYWORD ? nameOf(other) : other}`,
					campaign_id: r.campaign_id,
					keyword: r.target,
					match_type: r.match_type,
					isCampaign: view === BY_KEYWORD,
					status: statusOf.get(r.campaign_id),
					notAutomatable:
						r.automatable === false
							? r.not_automatable_reason ||
								"Automations cannot run on this campaign."
							: (refusalOf.get(r.campaign_id) ?? null),
					metrics: catalogSummary([r]),
				};
			})
			.sort(
				(a, b) =>
					Boolean(a.notAutomatable) - Boolean(b.notAutomatable) ||
					(perf ? b.metrics.spend - a.metrics.spend : 0) ||
					a.label.localeCompare(b.label) ||
					a.match_type.localeCompare(b.match_type),
			);

	// ONE row per key. `/ads/keywords` merges Blinkit's per-sub-campaign rows server-side
	// now, but still returns one row per MATCH TYPE, so a keyword run as both EXACT and
	// SMART arrives twice. Keying by the keyword alone made those share a key, so selecting
	// one highlighted both and the modal read as multi-select. Merged and summed here.
	const drillRows = (group) => {
		const by = new Map();
		for (const r of group.members) {
			const key = view === BY_KEYWORD ? r.campaign_id : r.target;
			if (!by.has(key)) by.set(key, []);
			by.get(key).push(r);
		}
		return [...by.entries()]
			.map(([key, members]) => ({
				key,
				label: view === BY_KEYWORD ? nameOf(key) : String(key),
				campaign_id: members[0].campaign_id,
				keyword: members[0].target,
				isCampaign: view === BY_KEYWORD,
				status: view === BY_KEYWORD ? statusOf.get(key) : undefined,
				notAutomatable: refusalOf.get(members[0].campaign_id) ?? null,
				metrics: aggregate(members),
			}))
			.sort(
				view === BY_KEYWORD
					? byActiveThenSpend
					: (a, b) => b.metrics.spend - a.metrics.spend,
			);
	};

	return (
		<div className="flex flex-col gap-2">
			<div className="flex flex-wrap items-center justify-between gap-3">
				{/* The shared segmented control, not a local copy: it fills the selected
				    segment and puts white on it, the way every other toggle in the product
				    does. Brand-red text on a grey fill reads as an error instead of as the
				    chosen segment on a form this full of validation copy. */}
				<ViewToggle
					size="lg"
					value={view}
					onChange={setView}
					options={[
						{ value: BY_KEYWORD, label: "Keyword × Campaigns" },
						{ value: BY_CAMPAIGN, label: "Campaign × Keywords" },
					]}
				/>
				{perf && (
					<span className="text-xs text-content-subtle">
						Performance for {range.from} → {range.to} (the dates in
						the navbar)
					</span>
				)}
				{!isComplete && (
					<span className="text-xs text-content-subtle">
						Showing the top {rows.length} of {total} by spend.
						Loading the rest…
					</span>
				)}
				<input
					type="search"
					value={search}
					onChange={(e) => setSearch(e.target.value)}
					placeholder={
						view === BY_KEYWORD
							? "Search by keyword"
							: "Search by campaign"
					}
					className="w-64 rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-content focus:border-brand focus:outline-none"
				/>
			</div>

			<div
				onScroll={(e) => setScrolled(e.currentTarget.scrollLeft > 0)}
				className="overflow-x-auto rounded-md border border-border"
			>
				<table
					className="w-full border-collapse"
					style={{ minWidth: catalog && !perf ? 720 : 1240 }}
				>
					<thead className="bg-card">
						<tr className="border-b border-border">
							<th
								className={`${TH} ${STICKY_PICK} bg-card`}
								aria-label="Selected"
							/>
							<th
								className={`${TH} ${STICKY_NAME} ${edge} bg-card`}
							>
								{view === BY_KEYWORD ? "Keyword" : "Campaign"}
							</th>
							{catalog ? (
								<CatalogHeaders unit={unit} perf={perf} />
							) : (
								<MetricHeaders />
							)}
						</tr>
					</thead>
					<tbody>
						{groups.length === 0 && (
							<tr>
								<td
									colSpan={14}
									className="p-3 text-sm text-content-subtle"
								>
									Nothing matches.
								</td>
							</tr>
						)}
						{groups.map((g) => {
							const on = selectedKey === g.key;
							const cellBg = on
								? "bg-muted"
								: "bg-card group-hover:bg-muted";
							return (
								<tr
									key={g.key}
									onClick={() => setDrill(g)}
									aria-selected={on}
									className={`group cursor-pointer border-b border-border/60 last:border-0 ${
										on
											? "bg-muted shadow-[inset_3px_0_0_0_var(--color-brand)]"
											: "hover:bg-muted"
									}`}
								>
									{/* The row is the control; the tick and highlight say which one is
									    chosen. Clicking opens the other axis for this row. */}
									<td
										className={`${TD} ${STICKY_PICK} ${cellBg} text-brand`}
									>
										{on ? "✓" : ""}
									</td>
									<td
										className={`${TD} ${STICKY_NAME} ${edge} ${cellBg} max-w-[20rem]`}
									>
										<div
											className="truncate font-medium"
											title={g.label}
										>
											{g.label}
										</div>
										<span className="text-[11px] text-content-subtle">
											{/* distinct, for the same duplicate reason as drillRows */}
											{
												new Set(
													g.members.map((r) =>
														view === BY_KEYWORD
															? r.campaign_id
															: r.target,
													),
												).size
											}{" "}
											{view === BY_KEYWORD
												? "campaigns"
												: "keywords"}
										</span>
										{view === BY_CAMPAIGN && (
											<>
												{" · "}
												<CampaignTag
													id={g.key}
													status={g.status}
												/>
											</>
										)}
									</td>
									{catalog ? (
										<CatalogCells
											m={g.metrics}
											perf={perf}
										/>
									) : (
										<MetricCells m={g.metrics} />
									)}
								</tr>
							);
						})}
					</tbody>
				</table>
			</div>

			{drill && (
				<DrillModal
					title={
						view === BY_KEYWORD
							? "Select campaign for keyword:"
							: "Select keyword for campaign:"
					}
					subtitle={drill.label}
					rows={catalog ? catalogDrillRows(drill) : drillRows(drill)}
					catalog={catalog}
					perf={perf}
					unit={unit}
					// Only the keyword direction accepts a typed value; you cannot invent a
					// campaign. Not in catalogue mode: a typed keyword has no match type or
					// floor to carry, and the Zepto adapter bids only on keywords the campaign
					// already has.
					freeText={view === BY_CAMPAIGN && !catalog}
					initial={
						view === BY_KEYWORD
							? drill.key === keyword
								? catalog
									? `${campaignId}|${matchType}`
									: campaignId
								: null
							: drill.key === campaignId
								? catalog
									? `${keyword}|${matchType}`
									: keyword
								: null
					}
					onApply={(row) => {
						// A typed keyword carries no campaign of its own — it belongs to the campaign
						// whose list is open, i.e. this group's key in the Campaign × Keywords view.
						const id =
							row.campaign_id ??
							(view === BY_CAMPAIGN ? drill.key : null);
						onChange({
							campaign_id: id,
							campaign_name: nameOf(id),
							keyword: row.keyword,
							// Catalogue rows name their match type; Blinkit's merged rows do
							// not, and the rule then keeps the engine's default (EXACT).
							match_type: row.match_type ?? null,
						});
						setDrill(null);
					}}
					onClose={() => setDrill(null)}
				/>
			)}
		</div>
	);
};
