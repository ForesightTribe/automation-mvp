import { useState } from "react";
import { useSalesPivot } from "../hooks";
import { formatNumber } from "../../../lib/format";
import { ViewToggle } from "../../../components/ui/ViewToggle";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";

/**
 * Sales-by-SKU pivot — the client's flagship view. SKU rows grouped by
 * marketplace over the globally-selected window, with a Grand Total row.
 *
 * Two view modes driven by toggles:
 *   - Daily: one column per day in the range, weekend (Fri–Sun) columns tinted.
 *   - Weekly: calendar-week rollups + week-over-week deltas (Excel-style
 *     red/green), which is what the client scans for trend.
 * Metric toggle picks revenue (mrp_value) vs units (qty_sold). All numbers come
 * from `blinkit_seller_sales` via the reports/sales-pivot endpoint (Blinkit-only
 * today; other marketplaces arrive as their own blocks once scraped).
 */

const METRICS = [
	{ value: "value", label: "Revenue" },
	{ value: "units", label: "Units" },
];
const GRANULARITY = [
	{ value: "daily", label: "Daily" },
	{ value: "weekly", label: "Weekly" },
];

/** "2026-07-01" -> "01-07". */
const dayLabel = (iso) => {
	const [, m, d] = iso.split("-");
	return `${d}-${m}`;
};

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

const PivotTable = ({ data, granularity }) => {
	const daily = granularity === "daily";
	const { days, weeks, platforms } = data;

	if (!platforms.length)
		return (
			<div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-content-muted">
				No sales in the selected window.
			</div>
		);

	// Column count for the platform header colSpan.
	const colCount = daily
		? 1 + days.length + 1
		: 1 + weeks.length + 1 + Math.max(0, weeks.length - 1);

	return (
		<div className="overflow-x-auto rounded-xl border border-border bg-card">
			<table className="w-full border-collapse text-sm">
				<thead>
					<tr className="border-b border-border bg-muted/60 text-content-subtle">
						<th className="sticky left-0 z-10 bg-muted/60 px-3 py-2 text-left font-medium">
							SKU
						</th>
						{daily
							? days.map((d) => (
									<th
										key={d.date}
										title={d.weekend ? "Weekend (Fri–Sun)" : "Weekday"}
										className={`px-2 py-2 text-right font-medium ${
											d.weekend ? "bg-info-soft/40" : ""
										}`}
									>
										{dayLabel(d.date)}
									</th>
								))
							: weeks.map((w) => (
									<th
										key={w.label}
										title={`${w.start} – ${w.end}`}
										className="px-2 py-2 text-right font-medium"
									>
										{w.label}
									</th>
								))}
						<th className="px-3 py-2 text-right font-medium">Total</th>
						{!daily &&
							weeks.slice(1).map((w, i) => (
								<th
									key={w.label}
									className="px-2 py-2 text-right font-medium"
								>
									{weeks[i].label}→{w.label}
								</th>
							))}
					</tr>
				</thead>
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
	);
};

const PlatformBlock = ({ platform, days, weeks, daily, colCount }) => {
	return (
		<>
			<tr className="border-b border-border bg-primary-soft/70">
				<td
					colSpan={colCount}
					className="sticky left-0 px-3 py-1.5 text-left font-display text-sm font-semibold text-content"
				>
					{platform.platform}
					{platform.live ? (
						<span className="ml-2 rounded bg-success-soft px-1.5 py-0.5 text-xs font-medium text-success">
							data available
						</span>
					) : (
						<span className="ml-2 rounded bg-warning-soft px-1.5 py-0.5 text-xs font-medium text-warning">
							needs scraper
						</span>
					)}
				</td>
			</tr>
			{platform.skus.map((sku) => (
				<tr
					key={sku.item_id}
					className="border-b border-border/60 last:border-0 hover:bg-muted/40"
				>
					<td className="sticky left-0 z-10 max-w-60 truncate bg-card px-3 py-1.5 text-left text-content">
						{sku.name}
					</td>
					{daily
						? sku.cells.map((v, i) => (
								<td
									key={i}
									className={`px-2 py-1.5 text-right tabular-nums text-content-muted ${
										days[i].weekend ? "bg-info-soft/40" : ""
									}`}
								>
									{formatNumber(v)}
								</td>
							))
						: sku.weeks.map((v, i) => (
								<td
									key={i}
									className="px-2 py-1.5 text-right tabular-nums text-content-muted"
								>
									{formatNumber(v)}
								</td>
							))}
					<td className="px-3 py-1.5 text-right font-semibold tabular-nums text-content">
						{formatNumber(sku.total)}
					</td>
					{!daily &&
						sku.week_deltas
							.slice(1)
							.map((d, i) => <DeltaCell key={i} delta={d} />)}
				</tr>
			))}
			{/* Grand Total row */}
			<tr className="border-b-2 border-border bg-muted/70 font-semibold text-content">
				<td className="sticky left-0 z-10 bg-muted/70 px-3 py-1.5 text-left">
					Grand Total
				</td>
				{daily
					? platform.day_totals.map((v, i) => (
							<td
								key={i}
								className={`px-2 py-1.5 text-right tabular-nums ${
									days[i].weekend ? "bg-info-soft/40" : ""
								}`}
							>
								{formatNumber(v)}
							</td>
						))
					: platform.week_totals.map((v, i) => (
							<td
								key={i}
								className="px-2 py-1.5 text-right tabular-nums"
							>
								{formatNumber(v)}
							</td>
						))}
				<td className="px-3 py-1.5 text-right tabular-nums">
					{formatNumber(platform.total)}
				</td>
				{!daily &&
					platform.week_deltas
						.slice(1)
						.map((d, i) => <DeltaCell key={i} delta={d} />)}
			</tr>
		</>
	);
};
