import { Fragment, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
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
/** Same tint, but painted on the CELLS. A row-level background sits behind its
 *  cells' borders, so BAND_GAP's transparent border would be filled in by it —
 *  the tint has to be on the cells for the gap to show. */
const TINT_CELLS = "[&>td]:bg-[#f0ede8]";
/** Rounds a full-width band row at both ends, so it reads as a band rather
 *  than a full-bleed stripe. */
const ROUNDED =
	"[&>td:first-child]:rounded-l-lg [&>td:last-child]:rounded-r-lg";
/** Clear space above a band row. A <tr> can't take margin, so this is a
 *  transparent top border; `bg-clip-padding` keeps the band's tint out of it,
 *  which is what makes it read as a gap rather than a taller band. */
const BAND_GAP =
	"[&>td]:border-t-[10px] [&>td]:border-transparent [&>td]:bg-clip-padding";

/** Tint carried by every Fri–Sun column, matching the daily view's weekend tint. */
const WEEKEND_BG = "bg-[#faf8f5]";

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
		: formatNumber(Math.abs(v) < 100 ? Math.round(v * 10) / 10 : Math.round(v));

/** Excel-like tinted delta cell from a growth fraction (null -> em dash). */
const DeltaCell = ({ delta }) => {
	if (delta === null || delta === undefined)
		return <td className="px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-right text-content-subtle">—</td>;
	const up = delta >= 0;
	return (
		<td
			className={`px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-right text-xs font-medium tabular-nums ${
				up ? "bg-success-soft text-success" : "bg-danger-soft text-danger"
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
	<div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-content-muted">
		{children}
	</div>
);

const PivotTable = ({ data, granularity }) => {
	const daily = granularity === "daily";
	const { days, weeks, platforms } = data;

	if (!platforms.length) return <Notice>No sales in the selected window.</Notice>;

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
					The weekly view only counts full Monday-to-Sunday weeks. Widen the
					date range, or switch to the Daily view.
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
					Weekly figures are <strong className="font-medium">average sales per
					day</strong>, not totals — Mon–Thu averaged over 4 days, Fri–Sun over
					3, so the two are directly comparable. Only complete Monday–Sunday
					weeks are counted ({weeks[0].start} → {weeks[weeks.length - 1].end}).
				</p>
			)}
			<div className="overflow-x-auto rounded-xl border border-border bg-card p-2 lg:p-3 2xl:p-4">
				<table className="w-full border-separate border-spacing-0 text-xs lg:text-[13px] 2xl:text-sm">
					{daily ? <DailyHead days={days} /> : <WeeklyHead weeks={weeks} />}
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
							/>
						))}
					</tbody>
				</table>
			</div>
		</div>
	);
};

const HEAD_ROW =
	"bg-card text-content-subtle [&>th]:border-b [&>th]:border-border";
const HEAD_CELL = "px-1.5 py-1.5 lg:px-3 lg:py-2.5 2xl:px-4 2xl:py-3 text-right font-medium";

const DailyHead = ({ days }) => (
	<thead>
		<tr className={HEAD_ROW}>
			<th className="sticky left-0 z-10 bg-card px-1.5 py-1.5 lg:px-3 lg:py-2.5 2xl:px-4 2xl:py-3 text-left font-medium">
				SKU
			</th>
			{days.map((d) => (
				<th
					key={d.date}
					title={d.weekend ? "Weekend (Fri–Sun)" : "Weekday (Mon–Thu)"}
					className={`${HEAD_CELL} ${d.weekend ? WEEKEND_BG : ""}`}
				>
					{dayLabel(d.date)}
				</th>
			))}
			<th className="px-1.5 py-1.5 lg:px-3 lg:py-2.5 2xl:px-4 2xl:py-3 text-right font-medium">Total</th>
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
						<th className={`${HEAD_CELL} border-l border-border`}>{WEEKDAY}</th>
						<th className={`${HEAD_CELL} ${WEEKEND_BG}`}>{WEEKEND}</th>
					</Fragment>
				))}
				<th className={`${HEAD_CELL} border-l border-border`}>{WEEKDAY}</th>
				<th className={`${HEAD_CELL} ${WEEKEND_BG}`}>{WEEKEND}</th>
				<th
					className={HEAD_CELL}
					title="All 7 days — weighted across 4 weekdays and 3 weekend days, so not the sum of the two columns to its left"
				>
					All 7
				</th>
				{pairs.map((w) => (
					<Fragment key={w.label}>
						<th className={`${HEAD_CELL} border-l border-border`}>{WEEKDAY}</th>
						<th className={`${HEAD_CELL} ${WEEKEND_BG}`}>{WEEKEND}</th>
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
const ValueCells = ({ row, days, daily, muted, inverse }) => {
	const tone = muted ? "text-content-muted" : "";
	// On the inverse fill the row supplies its own colour, and the light weekend
	// tint would paint over it — so skip both and inherit.
	const total = inverse ? "text-inherit" : "text-content";
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
				<td
					className={`px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-right font-semibold tabular-nums ${total}`}
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
			<td className="border-l border-border px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-right font-semibold tabular-nums text-content">
				{avgNumber(row.weekday.total)}
			</td>
			<td
				className={`px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-right font-semibold tabular-nums text-content ${WEEKEND_BG}`}
			>
				{avgNumber(row.weekend.total)}
			</td>
			<td className="px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-right font-semibold tabular-nums text-content">
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

const PlatformBlock = ({ platform, days, weeks, daily, colCount, showPlatform }) => {
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
				<tr className={`${TINT} ${ROUNDED}`}>
					<td
						colSpan={colCount}
						className="sticky left-0 px-1.5 py-1.5 lg:px-3 lg:py-2.5 2xl:px-4 2xl:py-3 text-left font-display text-sm font-semibold text-content"
					>
						{platform.platform}
					</td>
				</tr>
			)}
			{platform.categories.map((cat) => (
				<Fragment key={cat.name}>
					{/* Category heading — a label only; its numbers live on the
					    subtotal row that closes the group, Excel-pivot style. */}
					<tr className={`${TINT_CELLS} ${ROUNDED} ${BAND_GAP}`}>
						<td
							colSpan={colCount}
							className="sticky left-0 py-1.5 pr-1.5 pl-6 text-left font-medium text-content lg:py-2.5 lg:pr-3 lg:pl-10 2xl:py-3 2xl:pr-4 2xl:pl-12"
						>
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
						</td>
					</tr>
					{!collapsed.has(cat.name) &&
						cat.skus.map((sku) => (
							<tr
								key={sku.item_id}
								className="hover:bg-muted/40 [&>td]:border-b [&>td]:border-border/60"
							>
								<td className="sticky left-0 z-10 max-w-40 truncate lg:max-w-52 2xl:max-w-60 bg-card py-2.5 pr-2 pl-4 lg:py-3 lg:pr-3 lg:pl-5 2xl:py-4 2xl:pr-4 2xl:pl-6 text-left text-content">
									{sku.name}
								</td>
								<ValueCells row={sku} days={days} daily={daily} muted />
							</tr>
						))}
					{/* Category subtotal — shown even when the group is collapsed, so
					    collapsing everything leaves a clean category-level report. */}
					<TotalsRow
						row={cat}
						days={days}
						daily={daily}
						className={`${TINT} ${ROUNDED} text-content`}
						cellBg={TINT}
						label={`Total - ${cat.name}`}
					/>
				</Fragment>
			))}
			{/* Grand Total closes the block on the inverse fill, so it reads as
			    the end of the report rather than one more subtotal. */}
			<TotalsRow
				row={platform}
				days={days}
				daily={daily}
				inverse
				className={`text-on-inverse ${ROUNDED} ${BAND_GAP} [&>td]:bg-inverse`}
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
		<td className={`sticky left-0 z-10 px-1.5 py-2 lg:px-3 lg:py-3 2xl:px-4 2xl:py-4 text-left ${cellBg}`}>
			{label}
		</td>
		<ValueCells row={row} days={days} daily={daily} inverse={inverse} />
	</tr>
);
