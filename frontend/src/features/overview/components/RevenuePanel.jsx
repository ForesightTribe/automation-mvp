import { useMemo, useState } from "react";
import {
	useTrends,
	useOverview,
	useMarketplaceTrends,
	useMarketplaceBreakdown,
} from "../hooks";
import { ChannelSplit } from "./ChannelSplit";
import { EChart } from "../../../components/charts/EChart";
import { trajectoryOption } from "../../../components/charts/options";
import { Loading } from "../../../components/feedback/Loading";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCurrency } from "../../../lib/format";
import { useDateRange } from "../../../context/DateRangeContext";
import { previousRangeLabel } from "../../../lib/dates";
import { markColor } from "../../../components/ui/MarketplaceMark";

/**
 * Revenue over the window the user picked, with what it cost beneath it.
 *
 * This follows the date picker, unlike the figures above it, which always read
 * the latest complete day. The heading says which window it is showing so the
 * two are not mistaken for each other.
 */
const Figure = ({
	label,
	value,
	delta,
	hint,
	unit = "percent",
	size,
	prevLabel,
}) => {
	const missing = delta === null || delta === undefined;
	// `pp` deltas arrive already in points; percent deltas are fractions.
	const pct = missing ? null : unit === "pp" ? delta : delta * 100;
	const flat = pct !== null && Math.round(pct) === 0;
	const tone = flat
		? "text-content-muted"
		: pct > 0
			? "text-success"
			: "text-danger";

	return (
		<div className="flex flex-col gap-0.5">
			<p className="text-[11px] font-semibold tracking-wide text-content-subtle uppercase">
				{label}
			</p>
			<p
				className={`font-display font-bold text-content tabular-nums ${
					size === "lead" ? "text-3xl" : "text-xl"
				}`}
			>
				{value}
			</p>
			<p className="text-xs text-content-muted">
				{missing ? (
					<span className="text-content-subtle">{hint}</span>
				) : (
					<>
						<span className={`font-medium ${tone}`}>
							{pct > 0 ? "▲" : "▼"}{" "}
							{unit === "pp"
								? `${Math.abs(pct).toFixed(1)}pp`
								: `${Math.abs(pct).toFixed(0)}%`}
						</span>{" "}
						{prevLabel ? (
							<span
								title={prevLabel}
								className="cursor-help underline decoration-dotted underline-offset-2"
							>
								{hint}
							</span>
						) : (
							hint
						)}
					</>
				)}
			</p>
		</div>
	);
};

export const RevenuePanel = () => {
	const { data: trends, isLoading } = useTrends();
	const { data: summary } = useOverview();
	const { data: channels } = useMarketplaceTrends();
	const { data: breakdown } = useMarketplaceBreakdown();
	// The channel a reader is pointing at in the table beneath the figures.
	const [focus, setFocus] = useState(null);

	const { range } = useDateRange();
	const rows = trends ?? [];

	// Organic is revenue less what ads are credited with, so it is derived here
	// rather than read from a field that does not exist per day.
	const OVERLAYS = {
		ad: {
			name: "Ad revenue",
			color: "#16a34a",
			of: (r) => r.ad_sales,
		},
		organic: {
			name: "Organic revenue",
			color: "#0d9488",
			of: (r) =>
				r.revenue != null && r.ad_sales != null
					? Math.max(0, r.revenue - r.ad_sales)
					: null,
		},
	};

	// Below two channels the split is the total redrawn, so only the headline
	// series is kept.
	const lines =
		(channels ?? []).length > 1
			? channels.map((m) => ({
					name: m.name,
					color: markColor(m),
					data: rows.map(
						(r) =>
							m.points.find((p) => p.date === r.date)?.revenue ??
							null,
					),
				}))
			: [];

	const option = useMemo(() => {
		return trajectoryOption(rows, [], {
			key: "revenue",
			color: "#0284c7",
			split: lines,
			legend: false,
			focus,
			kind: lines.length > 1 ? "line" : "bar",
			breakdown: [
				...Object.values(OVERLAYS).map((o) => ({
					name: o.name,
					color: o.color,
					data: rows.map(o.of),
				})),
				{
					// A ratio, so it is reported in the tooltip but never drawn:
					// a second y-scale would let the lines cross at points that
					// mean nothing.
					name: "RoAS",
					color: "#4f46e5",
					data: rows.map((r) =>
						r.ad_spend ? r.ad_sales / r.ad_spend : null,
					),
					format: (v) => (v == null ? "—" : `${v.toFixed(2)}×`),
				},
			],
		});
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [rows, channels, focus]);
	const hasData = rows.some((r) => r.revenue != null);

	const revenue = summary?.revenue?.value;

	return (
		<section className="flex flex-col">
			{/* The total on the left with its breakdown beneath, the shape of the
			    period on the right — the same split as the block above. */}
			<div className="grid grid-cols-1 gap-6 rounded-xl border border-border bg-card p-6 lg:grid-cols-12">
				<div className="flex flex-col gap-5 lg:col-span-4">
					<Figure
						label="Revenue"
						value={formatCurrency(revenue)}
						delta={summary?.revenue?.delta_pct}
						size="lead"
						prevLabel={
							summary?.revenue?.prev == null
								? `No revenue recorded in ${previousRangeLabel(range)}`
								: `${formatCurrency(summary.revenue.prev)} over ${previousRangeLabel(range)}`
						}
					/>
					<ChannelSplit
						rows={(breakdown ?? []).filter(
							(m) =>
								m.connected &&
								m.revenue?.value != null &&
								(channels ?? []).some((c) => c.slug === m.slug),
						)}
						focus={focus}
						onFocus={setFocus}
					/>
				</div>

				<div className="lg:col-span-8">
					{isLoading && <Loading label="Loading revenue…" />}
					{!isLoading &&
						(hasData ? (
							<EChart option={option} height={240} />
						) : (
							<EmptyState message="No revenue in this period." />
						))}
				</div>
			</div>
		</section>
	);
};
