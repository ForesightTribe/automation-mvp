import { Fragment, useState } from "react";
import { useSalesPivot } from "../hooks";
import { formatNumber } from "../../../lib/format";
import { ViewToggle } from "../../../components/ui/ViewToggle";
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

const METRICS = [
	{ value: "value", label: "Revenue" },
	{ value: "units", label: "Units" },
];
const GRANULARITY = [
	{ value: "daily", label: "Daily" },
	{ value: "weekly", label: "Weekly" },
];

const WEEKDAY = "Mon–Thu";
const WEEKEND = "Fri–Sun";
/** Tint carried by every Fri–Sun column, matching the daily view's weekend tint. */
const WEEKEND_BG = "bg-info-soft/40";

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
		return <td className="px-2 py-1.5 text-right text-content-subtle">—</td>;
	const up = delta >= 0;
	return (
		<td
			className={`px-2 py-1.5 text-right text-xs font-medium tabular-nums ${
				up ? "bg-success-soft text-success" : "bg-danger-soft text-danger"
			}`}
		>
			{delta > 0 ? "+" : ""}
			{(delta * 100).toFixed(0)}%
		</td>
	);
};

export const SalesPivotReport = () => {
	const [metric, setMetric] = useState("value");
	const [granularity, setGranularity] = useState("daily");
	const { data, isLoading, error, refetch } = useSalesPivot(metric);

	return (
		<div className="flex flex-col gap-4">
			<div className="flex flex-wrap items-center justify-end gap-2">
				<ViewToggle options={METRICS} value={metric} onChange={setMetric} />
				<ViewToggle
					options={GRANULARITY}
					value={granularity}
					onChange={setGranularity}
				/>
			</div>

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
			<div className="overflow-x-auto rounded-xl border border-border bg-card">
				<table className="w-full border-collapse text-sm">
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
							/>
						))}
					</tbody>
				</table>
			</div>
		</div>
	);
};

const HEAD_ROW = "border-b border-border bg-muted/60 text-content-subtle";
const HEAD_CELL = "px-2 py-2 text-right font-medium";

const DailyHead = ({ days }) => (
	<thead>
		<tr className={HEAD_ROW}>
			<th className="sticky left-0 z-10 bg-muted/60 px-3 py-2 text-left font-medium">
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
			<th className="px-3 py-2 text-right font-medium">Total</th>
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
					className="sticky left-0 z-10 bg-muted/60 px-3 py-2 text-left font-medium"
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
const ValueCells = ({ row, days, daily, muted }) => {
	const tone = muted ? "text-content-muted" : "";
	if (daily)
		return (
			<>
				{row.cells.map((v, i) => (
					<td
						key={i}
						className={`px-2 py-1.5 text-right tabular-nums ${tone} ${
							days[i].weekend ? WEEKEND_BG : ""
						}`}
					>
						{formatNumber(v)}
					</td>
				))}
				<td className="px-3 py-1.5 text-right font-semibold tabular-nums text-content">
					{formatNumber(row.total)}
				</td>
			</>
		);

	return (
		<>
			{row.weekday.cells.map((v, i) => (
				<Fragment key={i}>
					<td
						className={`border-l border-border px-2 py-1.5 text-right tabular-nums ${tone}`}
					>
						{avgNumber(v)}
					</td>
					<td
						className={`px-2 py-1.5 text-right tabular-nums ${tone} ${WEEKEND_BG}`}
					>
						{avgNumber(row.weekend.cells[i])}
					</td>
				</Fragment>
			))}
			<td className="border-l border-border px-2 py-1.5 text-right font-semibold tabular-nums text-content">
				{avgNumber(row.weekday.total)}
			</td>
			<td
				className={`px-2 py-1.5 text-right font-semibold tabular-nums text-content ${WEEKEND_BG}`}
			>
				{avgNumber(row.weekend.total)}
			</td>
			<td className="px-3 py-1.5 text-right font-semibold tabular-nums text-content">
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

const PlatformBlock = ({ platform, days, weeks, daily, colCount }) => {
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
			<tr className="border-b border-border bg-primary-soft/70">
				<td
					colSpan={colCount}
					className="sticky left-0 px-3 py-1.5 text-left font-display text-sm font-semibold text-content"
				>
					{platform.platform}
				</td>
			</tr>
			{platform.categories.map((cat) => (
				<Fragment key={cat.name}>
					{/* Category heading — a label only; its numbers live on the
					    subtotal row that closes the group, Excel-pivot style. */}
					<tr className="border-b border-border/60 bg-muted/30">
						<td
							colSpan={colCount}
							className="sticky left-0 px-3 py-1.5 text-left font-medium text-content"
						>
							<button
								type="button"
								onClick={() => toggle(cat.name)}
								className="flex items-center gap-1.5 text-left"
							>
								<span className="text-xs text-content-subtle">
									{collapsed.has(cat.name) ? "▸" : "▾"}
								</span>
								{cat.name}
								<span className="font-normal text-content-subtle">
									({cat.skus.length})
								</span>
							</button>
						</td>
					</tr>
					{!collapsed.has(cat.name) &&
						cat.skus.map((sku) => (
							<tr
								key={sku.item_id}
								className="border-b border-border/60 hover:bg-muted/40"
							>
								<td className="sticky left-0 z-10 max-w-60 truncate bg-card py-1.5 pl-7 pr-3 text-left text-content">
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
						className="border-b border-border bg-muted/40 text-content"
						cellBg="bg-muted/40"
						label={`Total — ${cat.name}`}
					/>
				</Fragment>
			))}
			<TotalsRow
				row={platform}
				days={days}
				daily={daily}
				className="border-b-2 border-border bg-muted/70 text-content"
				cellBg="bg-muted/70"
				label="Grand Total"
			/>
		</>
	);
};

/**
 * A bold summary row — used for both the per-category subtotal and the
 * marketplace Grand Total, which share the exact column shape of a SKU row.
 */
const TotalsRow = ({ row, days, daily, className, cellBg, label }) => (
	<tr className={`font-semibold ${className}`}>
		<td className={`sticky left-0 z-10 px-3 py-1.5 text-left ${cellBg}`}>
			{label}
		</td>
		<ValueCells row={row} days={days} daily={daily} />
	</tr>
);
