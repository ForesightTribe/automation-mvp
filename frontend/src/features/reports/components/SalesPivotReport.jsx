import { Fragment, useEffect, useRef, useState } from "react";
import {
	ChevronDown,
	ChevronLeft,
	ChevronRight,
	ChevronUp,
} from "lucide-react";
import { useSalesPivot } from "../hooks";
import { formatNumber } from "../../../lib/format";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";

/**
 * Sales-by-SKU pivot — the client's flagship view. SKU rows grouped by
 * marketplace → category (Cold Drinks & Juices, Munchies, Sweet Tooth, … as
 * tagged on the sales rows) over the globally-selected window, with a subtotal
 * row per category and a Grand Total row per marketplace. Category groups
 * collapse so the report can be read at category level alone.
 *
 * Two view modes driven by toggles:
 *   - Daily: one column per day in the whole range, weekend (Fri–Sun) columns
 *     tinted.
 *   - Weekly: only **complete Mon–Sun weeks** inside the range, each split into
 *     Mon–Thu and Fri–Sun. The client trades very differently on those two
 *     halves, so they are never blended: each half gets its own column, its own
 *     figure, and its own week-over-week delta against the same half of the prior
 *     week. Every weekly number is an **average per day**, not a sum — Mon–Thu is
 *     4 days and Fri–Sun 3, so only per-day figures are comparable. Partial weeks
 *     at the edges are dropped. The two views answer different questions (totals
 *     vs typical day) and are not meant to reconcile.
 * Metric toggle picks revenue (mrp_value) vs units (qty_sold). All numbers come
 * from `blinkit_seller_sales` via the reports/sales-pivot endpoint (Blinkit-only
 * today; other marketplaces arrive as their own blocks once scraped). A platform
 * block only exists when that marketplace has sales in the window, so its
 * presence is the status — hence no status chip on the header row.
 */

/** Toggle options — exported so ReportsPage can render the controls. */
export const METRICS = [
	{ value: "value", label: "Revenue" },
	{ value: "units", label: "Units" },
];
export const GRANULARITY = [
	{ value: "daily", label: "Daily" },
	{ value: "weekly", label: "Weekly" },
];

const WEEKDAY = "Mon–Thu";
const WEEKEND = "Fri–Sun";
/** The table's one tinted surface: weekend columns, category headers and
 *  subtotal rows all share it. */
const TINT = "bg-[#f0ede8]";
/** Same tint, but painted on the CELLS — a row-level background sits behind its
 *  cells and squares off their rounded corners. */
const TINT_CELLS = "[&>td]:bg-[#f0ede8]";
/** Rounds a full-width band row at both ends, so it reads as a band rather
 *  than a full-bleed stripe. */
const ROUNDED =
	"[&>td:first-child]:rounded-l-md [&>td:last-child]:rounded-r-md";
/**
 * An empty row used as vertical space above a band. A <tr> can't take margin,
 * and faking it with a transparent border forces `bg-clip-padding`, which then
 * deforms the band's corner radius (the padding box's radius is reduced by the
 * border width on that side only). A spacer row has no such interaction.
 */
const BandGap = ({ colSpan }) => (
	<tr aria-hidden="true">
		<td colSpan={colSpan} className="h-2.5 p-0" />
	</tr>
);

/**
 * Overflow cue. Instead of a scrollbar or overlaid arrows, the pinned SKU
 * column casts a shadow onto whatever is scrolling beneath it — so the shadow
 * only exists while content is hidden to its left, and it never covers data.
 */
const EDGE_L = "shadow-[8px_0_8px_-6px_rgba(0,0,0,0.14)]";

/** Tint carried by every Fri–Sun column, matching the daily view's weekend tint. */
const WEEKEND_BG = "bg-[#f0ede873]";

/** "2026-07-01" -> "01-07". */
const dayLabel = (iso) => {
	const [, m, d] = iso.split("-");
	return `${d}-${m}`;
};

/**
 * Weekly cells are per-day averages, so they carry decimals where daily cells
 * never do. Revenue averages run to six figures and read as noise at 2dp, while a
 * units average of 2.4/day would be destroyed by rounding to whole numbers — so
 * keep one decimal only for small values and round the large ones.
 */
const avgNumber = (v) =>
	v === null || v === undefined
		? "—"
		: formatNumber(
				Math.abs(v) < 100 ? Math.round(v * 10) / 10 : Math.round(v),
			);

/** Excel-like tinted delta cell from a growth fraction (null -> em dash). */
const DeltaCell = ({ delta }) => {
	if (delta === null || delta === undefined)
		return (
			<td className="px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-right text-content-subtle">
				—
			</td>
		);
	const up = delta >= 0;
	return (
		<td
			className={`px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-right text-xs font-medium tabular-nums ${
				up
					? "bg-success-soft text-success"
					: "bg-danger-soft text-danger"
			}`}
		>
			{delta > 0 ? "+" : ""}
			{(delta * 100).toFixed(0)}%
		</td>
	);
};

/**
 * `metric` and `granularity` are owned by ReportsPage so its toggle row can sit
 * beside the report switcher, as one control group. This component renders the
 * table only.
 */
export const SalesPivotReport = ({ metric, granularity }) => {
	const { data, isLoading, error, refetch } = useSalesPivot(metric);

	return (
		<div className="flex flex-col gap-4">
			{isLoading && <Loading label="Loading sales report…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading && !error && data && (
				<PivotTable data={data} granularity={granularity} />
			)}
		</div>
	);
};

const Notice = ({ children }) => (
	<div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-content-muted shadow-[0_2px_8px_rgba(0,0,0,0.10)]">
		{children}
	</div>
);

/**
 * Width of the visible scroll area. Category bands are sized to THIS rather than
 * to the table, so both of their rounded ends stay on screen while the dates
 * scroll underneath — a band as wide as the table has its right corner off in
 * the overflow where nothing can show it.
 */
const useScrollport = () => {
	const ref = useRef(null);
	const [width, setWidth] = useState(0);
	const [edges, setEdges] = useState({ left: false, right: false });

	// One handler for both observers: width drives the category bands, and the
	// two edge flags drive the scroll affordances.
	const measure = () => {
		const el = ref.current;
		if (!el) return;
		setWidth(el.clientWidth);
		const left = el.scrollLeft > 1;
		const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
		// Bail unless a flag actually flipped: setEdges always makes a new object,
		// so an unconditional call re-renders on every scroll event.
		setEdges((prev) =>
			prev.left === left && prev.right === right ? prev : { left, right },
		);
	};

	useEffect(() => {
		const el = ref.current;
		if (!el) return;
		measure();
		// Observe the CONTENT as well as the scrollport. The port's own box never
		// changes when the table inside it grows wider, so watching only the port
		// leaves `scrollWidth` stuck at its first (pre-layout) value and the
		// overflow flags never turn on.
		const ro = new ResizeObserver(measure);
		ro.observe(el);
		if (el.firstElementChild) ro.observe(el.firstElementChild);
		el.addEventListener("scroll", measure, { passive: true });
		return () => {
			ro.disconnect();
			el.removeEventListener("scroll", measure);
		};
	}, []);

	const page = (dir) =>
		ref.current?.scrollBy({
			left: dir * ref.current.clientWidth * 0.8,
			behavior: "smooth",
		});

	return { ref, width, edges, page };
};

/**
 * A small floating chevron marking a direction the table can still scroll.
 * Deliberately tiny and translucent: it is an indicator first and a control
 * second, so it reads as "there is more this way" without covering figures.
 */
const ScrollNub = ({ dir, onClick }) => (
	// The card is the whole table and is far taller than the viewport, so
	// `top-1/2` on the button would sit at the TABLE's midpoint — usually well
	// below the fold. Instead a full-height rail spans the card and the button
	// STICKS to the middle of the viewport inside it, staying in view however
	// far down the table you are.
	<div
		className={`pointer-events-none absolute inset-y-0 z-40 w-9 ${
			dir === "left" ? "left-0" : "right-0"
		}`}
	>
		<button
			type="button"
			onClick={onClick}
			aria-label={
				dir === "left" ? "Scroll dates left" : "Scroll dates right"
			}
			className={`pointer-events-auto sticky top-[calc(50vh-14px)] grid h-7 w-7 place-items-center rounded-full border border-border bg-card text-content-muted opacity-0 shadow-[0_2px_8px_rgba(0,0,0,0.10)] transition-opacity duration-150 group-hover/table:opacity-95 hover:border-brand hover:text-brand focus-visible:opacity-100 ${
				dir === "left" ? "ml-1" : "ml-auto mr-1"
			}`}
		>
			{dir === "left" ? (
				<ChevronLeft size={14} strokeWidth={2} />
			) : (
				<ChevronRight size={14} strokeWidth={2} />
			)}
		</button>
	</div>
);

const PivotTable = ({ data, granularity }) => {
	const daily = granularity === "daily";
	const { days, weeks, platforms } = data;
	const { ref: portRef, width: portWidth, edges, page } = useScrollport();

	if (!platforms.length)
		return <Notice>No sales in the selected window.</Notice>;

	// The weekly axis only holds whole Mon–Sun weeks, so a short or misaligned
	// range legitimately has nothing to roll up. Say so rather than render an
	// empty grid — the daily view still works.
	if (!daily && !weeks.length)
		return (
			<Notice>
				<p className="font-medium text-content">
					No complete Mon–Sun week in the selected range.
				</p>
				<p className="mt-1">
					The weekly view only counts full Monday-to-Sunday weeks.
					Widen the date range, or switch to the Daily view.
				</p>
			</Notice>
		);

	// Column count for the header colSpans: label + data columns + totals + deltas.
	const colCount = daily
		? 1 + days.length + 1
		: 1 + weeks.length * 2 + 3 + Math.max(0, weeks.length - 1) * 2;

	return (
		<div className="flex flex-col gap-2">
			{!daily && (
				<p className="text-xs text-content-muted">
					Weekly figures are{" "}
					<strong className="font-medium">
						average sales per day
					</strong>
					, not totals — Mon–Thu averaged over 4 days, Fri–Sun over 3,
					so the two are directly comparable. Only complete
					Monday–Sunday weeks are counted ({weeks[0].start} →{" "}
					{weeks[weeks.length - 1].end}).
				</p>
			)}
			{/* Padding sits on the OUTER, non-scrolling element and the scrollport
			    is the inner div. With padding on the scroller itself, that strip
			    lies outside the sticky column's pin point and scrolled-past cells
			    show through it. */}
			<div className="group/table relative rounded-xl border border-border bg-card p-2 shadow-[0_2px_8px_rgba(0,0,0,0.10)] lg:p-3 2xl:p-4">
				{/* Scrolls, but the bar is hidden — same treatment as the sidebar rail. */}
				<div
					ref={portRef}
					className="overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
				>
					<table className="w-full border-separate border-spacing-0 text-xs lg:text-[13px] 2xl:text-sm">
						{daily ? (
							<DailyHead days={days} />
						) : (
							<WeeklyHead weeks={weeks} />
						)}
						<tbody>
							{platforms.map((p) => (
								<PlatformBlock
									key={p.platform}
									platform={p}
									days={days}
									weeks={weeks}
									daily={daily}
									colCount={colCount}
									showPlatform={platforms.length > 1}
									portWidth={portWidth}
									edges={edges}
								/>
							))}
						</tbody>
					</table>
				</div>

				{/* Only for a direction that actually has more columns, and only
				    while the pointer is over the table — an arrow that is always
				    there stops reading as "there is more this way". */}
				{edges.left && (
					<ScrollNub dir="left" onClick={() => page(-1)} />
				)}
				{edges.right && (
					<ScrollNub dir="right" onClick={() => page(1)} />
				)}
			</div>
		</div>
	);
};

const HEAD_ROW =
	"bg-card text-content-subtle [&>th]:border-b [&>th]:border-border";
/** `whitespace-nowrap`: without it a column whose data is narrower than its
 *  own date label (e.g. a day of "0") shrinks and wraps the header. */
const HEAD_CELL =
	"px-1.5 py-1.5 lg:px-3 lg:py-2.5 2xl:px-4 2xl:py-3 text-right font-medium whitespace-nowrap";

const DailyHead = ({ days }) => (
	<thead>
		<tr className={HEAD_ROW}>
			<th className="sticky left-0 z-10 bg-card px-1.5 py-1.5 lg:px-3 lg:py-2.5 2xl:px-4 2xl:py-3 text-left font-medium">
				SKU
			</th>
			{days.map((d) => (
				<th
					key={d.date}
					title={
						d.weekend ? "Weekend (Fri–Sun)" : "Weekday (Mon–Thu)"
					}
					className={`${HEAD_CELL} ${d.weekend ? WEEKEND_BG : ""}`}
				>
					{dayLabel(d.date)}
				</th>
			))}
			<th className={`${HEAD_CELL} sticky right-0 z-20 bg-card`}>
				Total
			</th>
		</tr>
	</thead>
);

/**
 * Two-tier header: week (or week-pair) on top, the Mon–Thu / Fri–Sun split
 * beneath it. The split is the point of this view, so it gets its own labelled
 * row rather than being folded into the week label.
 */
const WeeklyHead = ({ weeks }) => {
	const pairs = weeks.slice(1);
	return (
		<thead>
			<tr className={HEAD_ROW}>
				<th
					rowSpan={2}
					className="sticky left-0 z-10 bg-card px-1.5 py-1.5 lg:px-3 lg:py-2.5 2xl:px-4 2xl:py-3 text-left font-medium"
				>
					SKU
				</th>
				{weeks.map((w) => (
					<th
						key={w.label}
						colSpan={2}
						title={`${w.start} – ${w.end}`}
						className="border-l border-border px-2 py-2 text-center font-medium"
					>
						{w.label}
					</th>
				))}
				<th
					colSpan={3}
					title="Average per day across every full week in the range"
					className="border-l border-border px-2 py-2 text-center font-medium"
				>
					Avg / day
				</th>
				{pairs.map((w, i) => (
					<th
						key={w.label}
						colSpan={2}
						className="border-l border-border px-2 py-2 text-center font-medium"
					>
						{weeks[i].label}→{w.label}
					</th>
				))}
			</tr>
			<tr className={`${HEAD_ROW} text-xs`}>
				{weeks.map((w) => (
					<Fragment key={w.label}>
						<th className={`${HEAD_CELL} border-l border-border`}>
							{WEEKDAY}
						</th>
						<th className={`${HEAD_CELL} ${WEEKEND_BG}`}>
							{WEEKEND}
						</th>
					</Fragment>
				))}
				<th className={`${HEAD_CELL} border-l border-border`}>
					{WEEKDAY}
				</th>
				<th className={`${HEAD_CELL} ${WEEKEND_BG}`}>{WEEKEND}</th>
				<th
					className={HEAD_CELL}
					title="All 7 days — weighted across 4 weekdays and 3 weekend days, so not the sum of the two columns to its left"
				>
					All 7
				</th>
				{pairs.map((w) => (
					<Fragment key={w.label}>
						<th className={`${HEAD_CELL} border-l border-border`}>
							{WEEKDAY}
						</th>
						<th className={`${HEAD_CELL} ${WEEKEND_BG}`}>
							{WEEKEND}
						</th>
					</Fragment>
				))}
			</tr>
		</thead>
	);
};

/**
 * The value columns of one row, for either mode. `row` is a SKU, a category or a
 * platform — they all carry cells/total (daily) and weekday/weekend/week_total
 * (weekly), so the three row types render through the same code.
 */
const ValueCells = ({
	row,
	days,
	daily,
	muted,
	inverse,
	cellBg = "bg-card",
}) => {
	const tone = muted
		? "text-content-subtle group-hover:text-content-muted"
		: "";
	// The Total cell always inherits, so whatever the ROW sets applies to it too
	// (subtotal rows are #646160, Grand Total is white, SKU rows inherit black).
	// The light weekend tint would paint over the inverse fill, so skip it there.
	const total = "text-inherit";
	const weekend = (i) => (!inverse && days[i].weekend ? WEEKEND_BG : "");
	if (daily)
		return (
			<>
				{row.cells.map((v, i) => (
					<td
						key={i}
						className={`px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-right tabular-nums ${tone} ${weekend(i)}`}
					>
						{formatNumber(v)}
					</td>
				))}
				{/* Pinned right, mirroring the sticky SKU column — the dates scroll
				    BETWEEN the two. Needs its own opaque background or the columns
				    passing underneath show through it. */}
				<td
					className={`sticky right-0 z-10 px-1.5 py-2 text-right tabular-nums lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 ${cellBg} ${total}`}
				>
					{formatNumber(row.total)}
				</td>
			</>
		);

	return (
		<>
			{row.weekday.cells.map((v, i) => (
				<Fragment key={i}>
					<td
						className={`border-l border-border px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-right tabular-nums ${tone}`}
					>
						{avgNumber(v)}
					</td>
					<td
						className={`px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-right tabular-nums ${tone} ${WEEKEND_BG}`}
					>
						{avgNumber(row.weekend.cells[i])}
					</td>
				</Fragment>
			))}
			<td className="border-l border-border px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-right tabular-nums text-inherit">
				{avgNumber(row.weekday.total)}
			</td>
			<td
				className={`px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-right tabular-nums text-inherit ${WEEKEND_BG}`}
			>
				{avgNumber(row.weekend.total)}
			</td>
			<td className="px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-right tabular-nums text-inherit">
				{avgNumber(row.week_total)}
			</td>
			{/* Deltas compare like with like — this week's Mon–Thu against last
			    week's Mon–Thu, and the same for Fri–Sun. */}
			{row.weekday.deltas.slice(1).map((d, i) => (
				<Fragment key={i}>
					<DeltaCell delta={d} />
					<DeltaCell delta={row.weekend.deltas[i + 1]} />
				</Fragment>
			))}
		</>
	);
};

const PlatformBlock = ({
	platform,
	days,
	weeks,
	daily,
	colCount,
	showPlatform,
	portWidth,
	edges,
}) => {
	// Categories collapsed by name — expanded by default, so the report opens
	// looking exactly as it did before categories existed.
	const [collapsed, setCollapsed] = useState(() => new Set());
	const toggle = (name) =>
		setCollapsed((prev) => {
			const next = new Set(prev);
			next.has(name) ? next.delete(name) : next.add(name);
			return next;
		});

	return (
		<>
			{/* The marketplace name only earns a row when there is more than one
			    block to tell apart — with a single marketplace it is noise above
			    the first category. */}
			{showPlatform && (
				<tr className={`${TINT_CELLS} ${ROUNDED}`}>
					<td
						colSpan={colCount}
						className="sticky left-0 px-1.5 py-1.5 lg:px-3 lg:py-2.5 2xl:px-4 2xl:py-3 text-left font-display text-sm font-semibold text-content"
					>
						{platform.platform}
					</td>
				</tr>
			)}
			{platform.categories.map((cat) => {
				const isCollapsed = collapsed.has(cat.name);
				// Collapsed, the heading IS the subtotal — the numbers move onto it
				// and the separate "Total - …" row would just repeat them. Expanded,
				// the heading is a label only and the totals close the group.
				const heading = (
					<button
						type="button"
						onClick={() => toggle(cat.name)}
						className="flex items-center gap-1.5 text-left"
					>
						{cat.name}
						<span className="font-normal text-content-subtle">
							({cat.skus.length})
						</span>
						{collapsed.has(cat.name) ? (
							<ChevronDown
								size={16}
								strokeWidth={1.5}
								aria-hidden="true"
								className="ml-1 text-content-subtle"
							/>
						) : (
							<ChevronUp
								size={16}
								strokeWidth={1.5}
								aria-hidden="true"
								className="ml-1 text-content-subtle"
							/>
						)}
					</button>
				);

				return (
					<Fragment key={cat.name}>
						<BandGap colSpan={colCount} />
						{isCollapsed ? (
							<TotalsRow
								row={cat}
								days={days}
								daily={daily}
								className={`${TINT_CELLS} ${ROUNDED} text-content`}
								cellBg=""
								label={heading}
							/>
						) : (
							<tr>
								{/* The cell spans the table, but the visible bar inside it
								    is pinned and sized to the SCROLLPORT — so its two
								    rounded ends are always on screen. */}
								<td colSpan={colCount} className="p-0">
									<div
										style={{
											width: portWidth || undefined,
										}}
										className="sticky left-0 rounded-md bg-[#f0ede8] px-1.5 py-1 text-left font-medium text-content lg:px-3 lg:py-1.5 2xl:px-4 2xl:py-2"
									>
										{heading}
									</div>
								</td>
							</tr>
						)}
						{!isCollapsed &&
							cat.skus.map((sku) => (
								<tr
									key={sku.item_id}
									className="group hover:bg-[#f9f7f4] [&>td]:border-b [&>td]:border-border/60"
								>
									<td
										className={`sticky left-0 z-10 max-w-40 truncate bg-card py-2.5 pr-2 pl-1.5 text-left text-content-muted group-hover:bg-[#f9f7f4] lg:max-w-52 lg:py-3 lg:pr-3 lg:pl-3 2xl:max-w-60 2xl:py-4 2xl:pr-4 2xl:pl-4 ${edges.left ? EDGE_L : ""}`}
									>
										{sku.name}
									</td>
									<ValueCells
										row={sku}
										days={days}
										daily={daily}
										muted
										cellBg="bg-card group-hover:bg-[#f9f7f4]"
									/>
								</tr>
							))}
						{!isCollapsed && (
							<TotalsRow
								row={cat}
								days={days}
								daily={daily}
								className={`${TINT_CELLS} ${ROUNDED} text-content-muted`}
								cellBg={TINT}
								label={`Total - ${cat.name}`}
							/>
						)}
					</Fragment>
				);
			})}
			{/* Grand Total closes the block on the inverse fill, so it reads as
			    the end of the report rather than one more subtotal. */}
			<BandGap colSpan={colCount} />
			<TotalsRow
				row={platform}
				days={days}
				daily={daily}
				inverse
				className={`text-on-inverse ${ROUNDED} [&>td]:bg-inverse`}
				cellBg="bg-inverse"
				label="Grand Total"
			/>
		</>
	);
};

/**
 * A bold summary row — used for both the per-category subtotal and the
 * marketplace Grand Total, which share the exact column shape of a SKU row.
 */
const TotalsRow = ({ row, days, daily, className, cellBg, label, inverse }) => (
	<tr className={`font-semibold ${className}`}>
		<td
			className={`sticky left-0 z-10 px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-left ${cellBg}`}
		>
			{label}
		</td>
		<ValueCells
			row={row}
			days={days}
			daily={daily}
			inverse={inverse}
			cellBg={cellBg}
		/>
	</tr>
);
