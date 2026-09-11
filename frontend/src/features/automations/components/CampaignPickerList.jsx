import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { useCampaigns, useTableSort } from "../hooks";
import { CampaignStateToggle } from "./CampaignStateToggle";
import { Loading } from "../../../components/feedback/Loading";
import { formatCurrency, formatNumber } from "../../../lib/format";

const TH =
	"whitespace-nowrap px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-content-subtle";
const TD = "whitespace-nowrap px-3 py-2 text-sm text-content";
const NUM = `${TD} text-right tabular-nums`;

// The identity columns (radio + campaign name) are FROZEN: they stay put while the metrics
// scroll sideways, so a number is never orphaned from the campaign it belongs to.
//
// Two things make that read correctly rather than as overlapping text:
//   1. every frozen cell paints its own opaque background (the row's, repeated) — a
//      transparent sticky cell lets the scrolling columns slide visibly underneath it;
//   2. once the body is actually scrolled, the frozen block casts a shadow to its right,
//      so it reads as sitting ABOVE the metrics rather than merging into them. The shadow
//      appears only when scrolled, exactly as in the design — at rest the table is flat.
// ⚠️ The 40px sits on the CONTENT, not the cell. `table-layout: auto` ignores a width set on
// a `td`, so the column would take its content width instead, while STICKY_NAME below pins
// the next column at a fixed 40px. The two numbers have to agree or the frozen name overlaps
// the column beside it.
const STICKY_PICK = "sticky left-0 z-10 overflow-hidden";
const PICK_INNER = "block w-4";
// ⚠️ Frozen while the row scrolls under it: it has to clip, and its fill has to be
// opaque, or the scrolling columns read through and over it.
const STICKY_NAME = "sticky left-10 z-10 overflow-hidden";
// The controls ride the RIGHT edge for the same reason the name rides the left: the thing
// you act on must stay reachable however far the metrics are scrolled.
const STICKY_CTRL = "sticky right-0 z-10 border-l border-border";
const EDGE = "border-r border-border transition-shadow";
const EDGE_LIFTED = "shadow-[6px_0_10px_-6px_rgba(0,0,0,0.35)]";

const formatRoas = (v) => (v == null ? "—" : `${v.toFixed(2)}x`);

/** A column heading that sorts on click. The arrow is always drawn, so a sortable column
 *  looks sortable before it is touched, and it marks the direction once it is. */
const SortHead = ({ label, sortKey, sort, order, onSort, className = "" }) => {
	const on = sort === sortKey;
	return (
		<th className={`${TH} bg-card ${className}`}>
			<button
				type="button"
				onClick={() => onSort(sortKey)}
				aria-sort={
					on
						? order === "asc"
							? "ascending"
							: "descending"
						: undefined
				}
				className={`inline-flex cursor-pointer items-center gap-1 uppercase transition-colors hover:text-content ${on ? "text-content" : ""}`}
			>
				{label}
				{on ? (
					order === "asc" ? (
						<ArrowUp size={11} className="text-brand" />
					) : (
						<ArrowDown size={11} className="text-brand" />
					)
				) : (
					<ChevronsUpDown
						size={11}
						className="text-content-subtle/50"
					/>
				)}
			</button>
		</th>
	);
};

/**
 * Step 1's campaign picker — the performance table, so the choice is made with the
 * campaign's actual numbers in view rather than from its name.
 *
 * SINGLE-select on purpose: a budget schedule carries one `campaign_id` and a bid
 * rule targets one campaign's keyword, so radios are the honest control. Checkboxes
 * would invite picking five campaigns and then quietly creating one.
 *
 * Columns are everything `/ads/campaigns` actually returns, plus the two that fall
 * out of it by arithmetic (AOV, CPM). The design also asks for a direct/indirect
 * sales split, Reach and New Users Acquired; no endpoint returns those, so they are
 * left out rather than drawn as empty columns. Wide, so it scrolls SIDEWAYS only —
 * see the note on the wrapper about why it must not scroll vertically too.
 */

export const CampaignPickerList = ({
	selectedId,
	onSelect,
	onActivate,
	label = "Choose a campaign",
}) => {
	const { data: campaigns, isLoading } = useCampaigns();
	const [search, setSearch] = useState("");
	const [scrolled, setScrolled] = useState(false);
	const edge = `${EDGE} ${scrolled ? EDGE_LIFTED : ""}`;

	const rows = useMemo(() => {
		const q = search.trim().toLowerCase();
		const list = campaigns ?? [];
		if (!q) return list;
		return list.filter(
			(c) =>
				// ID is still searchable even though it has no column of its own.
				(c.name ?? "").toLowerCase().includes(q) ||
				String(c.campaign_id).includes(q),
		);
	}, [campaigns, search]);

	/** Every column, including the two that fall out of the others by arithmetic. */
	const ACCESSORS = {
		name: (c) => c.name ?? "",
		type: (c) => c.type ?? "",
		status: (c) => c.status ?? "",
		spend: (c) => c.budget_consumed,
		sales: (c) => c.ad_sales,
		roas: (c) => c.roas,
		aov: (c) => (c.quantities_sold ? c.ad_sales / c.quantities_sold : null),
		impressions: (c) => c.impressions,
		atc: (c) => c.atc,
		units: (c) => c.quantities_sold,
		cpm: (c) =>
			c.impressions ? (c.budget_consumed / c.impressions) * 1000 : null,
	};
	const { sorted, sort, order, onSort } = useTableSort(
		rows,
		ACCESSORS,
		"spend",
	);

	if (isLoading) return <Loading label="Loading campaigns…" />;

	return (
		<div className="flex flex-col gap-2">
			{/* The field's own label sits on this line, so the search costs no vertical space
			    of its own. The count and window label that used to be here were facts nobody
			    came for. */}
			<div className="flex items-center justify-between gap-3">
				<span className="text-xs font-medium text-content">
					{label}
				</span>
				<input
					type="search"
					placeholder="Search by campaign name or campaign ID"
					value={search}
					onChange={(e) => setSearch(e.target.value)}
					className="w-72 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-content transition-colors focus:border-content focus:outline-none"
				/>
			</div>

			{/* Capped height with its own scrollbar. Seventy campaigns listed in full pushed
			    the rest of the step below the fold, so choosing one meant scrolling past all
			    of them to reach the fields that follow. Roughly twenty rows fit.
			    The header stays put while the rows move. */}
			<div
				onScroll={(e) => setScrolled(e.currentTarget.scrollLeft > 0)}
				className="max-h-[22rem] overflow-auto rounded-md border border-border"
			>
				<table
					className="w-full border-collapse"
					style={{ minWidth: 980 }}
				>
					{/* ⚠️ `bg-card` on EVERY header cell. A background set on a <thead> is not
					    painted, so with it only on the two frozen cells the rows scrolled
					    visibly through the rest of the header. */}
					<thead className="sticky top-0 z-20">
						<tr className="border-b border-border">
							<th
								className={`${TH} ${STICKY_PICK} bg-card`}
								aria-label="Selected"
							>
								<span className={PICK_INNER} />
							</th>
							<SortHead
								label="Campaign Name"
								sortKey="name"
								sort={sort}
								order={order}
								onSort={onSort}
								className={`${STICKY_NAME} ${edge}`}
							/>
							<SortHead
								label="Type"
								sortKey="type"
								sort={sort}
								order={order}
								onSort={onSort}
							/>
							<SortHead
								label="Status"
								sortKey="status"
								sort={sort}
								order={order}
								onSort={onSort}
							/>
							<SortHead
								label="Ad Spend"
								sortKey="spend"
								sort={sort}
								order={order}
								onSort={onSort}
								className="text-right"
							/>
							<SortHead
								label="Ad Sales"
								sortKey="sales"
								sort={sort}
								order={order}
								onSort={onSort}
								className="text-right"
							/>
							<SortHead
								label="ROAS"
								sortKey="roas"
								sort={sort}
								order={order}
								onSort={onSort}
								className="text-right"
							/>
							<SortHead
								label="AOV"
								sortKey="aov"
								sort={sort}
								order={order}
								onSort={onSort}
								className="text-right"
							/>
							<SortHead
								label="Impressions"
								sortKey="impressions"
								sort={sort}
								order={order}
								onSort={onSort}
								className="text-right"
							/>
							<SortHead
								label="Add to cart"
								sortKey="atc"
								sort={sort}
								order={order}
								onSort={onSort}
								className="text-right"
							/>
							<SortHead
								label="Units"
								sortKey="units"
								sort={sort}
								order={order}
								onSort={onSort}
								className="text-right"
							/>
							<SortHead
								label="Avg CPM"
								sortKey="cpm"
								sort={sort}
								order={order}
								onSort={onSort}
								className="text-right"
							/>
							<th
								className={`${TH} ${STICKY_CTRL} bg-card text-center`}
							>
								Controls
							</th>
						</tr>
					</thead>
					<tbody>
						{rows.length === 0 && (
							<tr>
								<td
									colSpan={12}
									className="p-3 text-sm text-content-subtle"
								>
									No campaigns match.
								</td>
							</tr>
						)}
						{sorted.map((c) => {
							const selected = selectedId === c.campaign_id;
							// Both derived rather than stored: AOV is sales per unit sold, CPM is
							// spend per thousand impressions. Guarded — a campaign with no
							// impressions or no units would divide by zero.
							const aov = c.quantities_sold
								? c.ad_sales / c.quantities_sold
								: null;
							const cpm = c.impressions
								? (c.budget_consumed / c.impressions) * 1000
								: null;
							// Repeated on the frozen cells so they stay opaque over the scrolling
							// columns and still follow the row's selected/hover state.
							const cellBg = selected
								? "bg-muted"
								: "bg-card group-hover:bg-muted";
							return (
								<tr
									key={c.campaign_id}
									role="radio"
									tabIndex={0}
									aria-checked={selected}
									aria-label={c.name}
									onClick={() => onSelect(c)}
									onKeyDown={(e) => {
										if (
											e.key === "Enter" ||
											e.key === " "
										) {
											e.preventDefault();
											onSelect(c);
										}
									}}
									className={`group cursor-pointer border-b border-border/60 last:border-0 ${
										selected
											? "bg-muted shadow-[inset_3px_0_0_0_var(--color-brand)]"
											: "hover:bg-muted"
									}`}
								>
									{/* ⚠️ A radio that is VISIBLE WHEN EMPTY. A tick that only appears
									    once chosen is invisible in the state where it matters: an
									    unselected row shows a blank cell, so nothing invites the click,
									    and a search narrowed to a single row reads as already chosen
									    when it is not. The empty ring is the affordance. */}
									<td
										className={`${TD} ${STICKY_PICK} ${cellBg}`}
									>
										<span
											aria-hidden="true"
											className={`${PICK_INNER} flex h-4 w-4 items-center justify-center rounded-full border-2 transition-colors ${
												selected
													? "border-brand"
													: "border-content-subtle group-hover:border-content"
											}`}
										>
											{selected && (
												<span className="h-2 w-2 rounded-full bg-brand" />
											)}
										</span>
									</td>
									{/* No ID column. It costs a column of width and is only ever needed to
									    disambiguate two similarly-named campaigns. The tooltip carries it,
									    alongside the full name for when this cell truncates. */}
									<td
										className={`${TD} ${STICKY_NAME} ${edge} ${cellBg} max-w-[15rem] truncate font-medium`}
										title={`${c.name} · ID ${c.campaign_id}`}
									>
										{c.name}
									</td>
									<td className={`${TD} text-content-muted`}>
										{c.type}
									</td>
									<td className={TD}>
										<span
											className={`rounded-full px-2 py-0.5 text-xs font-medium ${
												c.status === "ACTIVE"
													? "bg-success-soft text-success"
													: "bg-muted text-content-muted"
											}`}
										>
											{c.status}
										</span>
									</td>
									<td className={NUM}>
										{formatCurrency(c.budget_consumed)}
									</td>
									<td className={NUM}>
										{formatCurrency(c.ad_sales)}
									</td>
									<td className={NUM}>
										{formatRoas(c.roas)}
									</td>
									<td className={NUM}>
										{aov == null
											? "—"
											: formatCurrency(aov)}
									</td>
									<td className={NUM}>
										{formatNumber(c.impressions)}
									</td>
									<td className={NUM}>
										{formatNumber(c.atc)}
									</td>
									<td className={NUM}>
										{formatNumber(c.quantities_sold)}
									</td>
									<td className={NUM}>
										{cpm == null
											? "—"
											: formatCurrency(cpm)}
									</td>
									<td
										className={`${TD} ${STICKY_CTRL} ${cellBg} text-center`}
									>
										<CampaignStateToggle
											name={c.name}
											status={c.status}
											onActivate={(next) =>
												onActivate?.(c, next)
											}
										/>
									</td>
								</tr>
							);
						})}
					</tbody>
				</table>
			</div>
		</div>
	);
};
