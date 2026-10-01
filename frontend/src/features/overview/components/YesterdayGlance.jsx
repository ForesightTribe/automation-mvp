import { useEffect } from "react";
import { Info } from "lucide-react";
import { HoverHint } from "../../../components/ui/HoverHint";
import { ChannelTiles, useChannelRows } from "./ChannelTiles";
import { ChannelShareBar } from "./ChannelShareBar";
import { HeadlineKpi } from "./HeadlineKpi";
import { DayCampaigns } from "./DayCampaigns";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { useReleaseSecondary } from "../priority";
import { Loading } from "../../../components/feedback/Loading";
import {
	formatCurrency,
	formatDayLabel as dayLabel,
} from "../../../lib/format";

/**
 * How the latest complete day went: the total for the day beside what each
 * channel contributed to it, then every campaign that ran.
 *
 * Nothing here follows the date picker, deliberately — "how did yesterday go"
 * must not change because someone left the range on 90 days.
 *
 * Where more than one marketplace sells, the channels get the tiles and the
 * total carries the split. Where only one does, the split would repeat the
 * total, so the tiles hold the measures behind it instead.
 */

export const pctChange = (now, before) =>
	now == null || !before ? null : ((now - before) / before) * 100;

/** RoAS is derived, so it is added to each row rather than read from one. */
export const withRoas = (rows) =>
	rows.map((r) => ({
		...r,
		roas: r.ad_spend ? r.ad_sales / r.ad_spend : null,
	}));

/** One change line: the move, and the day it is measured against. */
const Move = ({ change, label, hint, unit = "percent" }) => {
	const missing = change === null || change === undefined;
	const flat = !missing && Math.round(change * 10) === 0;
	const tone = flat
		? "text-content-muted"
		: change > 0
			? "text-success"
			: "text-danger";
	const shown = missing
		? null
		: unit === "pp"
			? `${change > 0 ? "▲" : "▼"} ${Math.abs(change).toFixed(1)}pp`
			: `${change > 0 ? "▲" : "▼"} ${Math.abs(change).toFixed(0)}%`;

	return (
		<span
			title={hint}
			className={`flex items-baseline gap-1.5 text-xs tabular-nums ${
				hint ? "cursor-help" : ""
			}`}
		>
			{shown ? (
				<span className={`font-medium ${tone}`}>{shown}</span>
			) : (
				<span className="text-content-subtle">—</span>
			)}
			<span className="text-content-subtle">{label}</span>
		</span>
	);
};

/** A qualifying measure as a tile: label, value, then each change beneath. */
const Small = ({ label, value, moves = [] }) => (
	<div className="flex flex-col gap-1 rounded-xl bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_16px_-4px_rgba(0,0,0,0.14)] ring-1 ring-black/[0.03] px-4 py-3.5">
		<span className="text-[11px] font-semibold tracking-wide text-content-subtle uppercase">
			{label}
		</span>
		<span className="font-display text-xl leading-tight font-bold text-content tabular-nums">
			{value}
		</span>
		{moves.map((m) => (
			<Move key={m.label} {...m} />
		))}
	</div>
);

// Two or three channels beside the total, so the row divides evenly rather than
// leaving a tile stranded on its own line.
// The total answers a wider question than any one channel, so it takes two
// of the row's columns.
const COLUMNS = {
	4: "lg:grid-cols-4",
	5: "lg:grid-cols-5",
	6: "lg:grid-cols-6",
};

export const YesterdayGlance = ({ rows = [] }) => {
	const days = withRoas(rows);
	const sold = days.filter((r) => r.revenue != null);
	const latest = sold[sold.length - 1];

	const i = days.findIndex((r) => r.date === latest?.date);
	const prior = i > 0 ? days[i - 1] : null;
	const sameWeekday = i >= 7 ? days[i - 7] : null;

	const { rows: channels, settled } = useChannelRows(
		latest?.date,
		sameWeekday?.date,
	);

	// The panels below hold until this block is served, so it does not queue
	// behind reads that take tens of seconds and answer a slower question.
	const release = useReleaseSecondary();
	useEffect(() => {
		if (settled) release();
	}, [settled, release]);
	const perChannel = channels.length > 1;

	if (!latest) return <EmptyState message="No sales data yet." />;
	// Holding here rather than drawing the single-channel layout first and
	// swapping it for the channels a moment later.
	if (!settled) return <Loading label="Loading yesterday…" />;

	const hasAds = latest.ad_spend != null || latest.ad_sales != null;

	// The same baseline as every tile, so the total and the channels beside it
	// are never measured against different days.
	const moves = (of, fmt) =>
		[[sameWeekday, "same day last week"]]
			.filter(([day]) => day)
			.map(([day, what]) => ({
				label: `vs ${dayLabel(day.date)}`,
				change: pctChange(of(latest), of(day)),
				hint:
					of(day) == null
						? `No figure for the ${what}`
						: `${what.charAt(0).toUpperCase() + what.slice(1)}, ${dayLabel(day.date)}: ${fmt(of(day))}`,
			}));

	const organic = (r) =>
		r?.revenue != null && r?.ad_sales != null
			? Math.max(0, r.revenue - r.ad_sales)
			: null;

	return (
		<section className="flex flex-col gap-5 rounded-xl border border-border bg-card p-6">
			<div className="flex flex-col gap-0.5">
				<h2 className="flex items-center gap-1.5 font-display text-lg font-semibold text-content">
					Yesterday at a glance
					{/* Which day this is, and why it ignores the date
						    picker. */}
					<HoverHint
						placement="bottom"
						width={250}
						label={`Figures are for ${dayLabel(latest.date)}, the latest day with complete sales. Changes are against the same day last week. This block does not follow the date range.`}
					>
						<button
							type="button"
							aria-label="Which day these figures cover"
							className="rounded text-content-subtle transition-colors hover:text-content"
						>
							<Info size={13} aria-hidden />
						</button>
					</HoverHint>
				</h2>
				<p className="text-xs text-content-muted">
					Performance across all selected channels
				</p>
			</div>

			{perChannel ? (
				/* The channels take the tiles and the total carries the split
				   between them. */
				<div
					className={`grid grid-cols-1 items-stretch gap-3 sm:grid-cols-2 ${
						COLUMNS[2 + channels.length] ?? "lg:grid-cols-5"
					}`}
				>
					<div className="flex flex-col justify-between gap-3 rounded-xl bg-surface px-5 py-4 shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_16px_-4px_rgba(0,0,0,0.14)] ring-1 ring-black/[0.03] sm:col-span-2">
						<div className="flex flex-col gap-1">
							<p className="text-sm font-semibold text-content-muted">
								Total revenue
							</p>
							<p
								title={
									prior?.revenue == null
										? undefined
										: `Previous day: ${formatCurrency(prior.revenue)}`
								}
								className="font-display text-3xl leading-tight font-bold text-content tabular-nums"
							>
								{formatCurrency(latest.revenue)}
							</p>
							{/* The baseline day stays on hover: the bar below
							    is what the tile has to say about the split. */}
							{moves((r) => r?.revenue, formatCurrency).map(
								(m) => (
									<Move key={m.label} {...m} label="" />
								),
							)}
						</div>
						<ChannelShareBar rows={channels} />
					</div>

					<ChannelTiles
						day={latest.date}
						baseline={sameWeekday?.date}
					/>
				</div>
			) : (
				/* One channel: no split to draw, so the headline takes the
				   lead and the measures behind it spread across the width. */
				<div className="grid grid-cols-1 items-center gap-x-8 gap-y-6 lg:grid-cols-5">
					<div className="lg:col-span-2">
						<HeadlineKpi
							label="Total revenue"
							value={formatCurrency(latest.revenue)}
							valueTitle={
								prior?.revenue == null
									? undefined
									: `Previous day: ${formatCurrency(prior.revenue)}`
							}
							comparisons={moves(
								(r) => r?.revenue,
								formatCurrency,
							).map((m) => ({
								label: m.label,
								value: m.change,
								hint: m.hint,
							}))}
						/>
					</div>

					{!hasAds ? (
						<div className="flex items-center rounded-xl bg-surface px-4 py-4 text-sm text-warning shadow-[0_1px_2px_rgba(0,0,0,0.05),0_6px_16px_-4px_rgba(0,0,0,0.14)] ring-1 ring-black/[0.03] lg:col-span-3">
							Ad data not populated yet for yesterday.
						</div>
					) : (
						<div className="grid grid-cols-2 gap-2 lg:col-span-3 lg:grid-cols-4">
							<Small
								label="Organic revenue"
								value={formatCurrency(organic(latest))}
								moves={moves(organic, formatCurrency)}
							/>
							<Small
								label="Ad spend"
								value={formatCurrency(latest.ad_spend)}
								moves={moves(
									(r) => r?.ad_spend,
									formatCurrency,
								)}
							/>
							<Small
								label="Ad revenue"
								value={formatCurrency(latest.ad_sales)}
								moves={moves(
									(r) => r?.ad_sales,
									formatCurrency,
								)}
							/>
							<Small
								label="RoAS"
								value={
									latest.roas
										? `${latest.roas.toFixed(2)}×`
										: "—"
								}
								moves={moves(
									(r) => r?.roas,
									(v) => `${v.toFixed(2)}×`,
								)}
							/>
						</div>
					)}
				</div>
			)}

			<DayCampaigns day={latest.date} />
		</section>
	);
};
