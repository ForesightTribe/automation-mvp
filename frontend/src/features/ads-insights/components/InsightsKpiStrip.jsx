import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { Card } from "../../../components/ui/Card";
import { DeltaBadge } from "../../../components/ui/DeltaBadge";
import { Sparkline } from "../../../components/charts/Sparkline";
import { InfoTooltip } from "../../../components/ui/InfoTooltip";
import { EChart } from "../../../components/charts/EChart";
import { miniCompareOption, twoBarOption, SERIES } from "../chartOptions";
import { usePreviousPerformance, usePreviousRange } from "../hooks";
import {
	formatCurrency,
	formatDate,
	formatNumber,
	formatPercent,
} from "../../../lib/format";

const formatRoas = (v) => (v == null ? "—" : `${v.toFixed(2)}x`);

/**
 * What each number means, in the terms of this account rather than a textbook. Every one
 * says where it comes from, because "revenue" from an ad platform is attributed revenue,
 * not the shop's own total, and that distinction is the usual source of an argument.
 */
const ABOUT = {
	"Ad Spend":
		"What the marketplace billed for these ads in the window — each marketplace's own figure, from its ads scrape, so the most recent day keeps moving until that day's scrape lands.",
	"Ad Revenue":
		"Sales the marketplace ATTRIBUTES to these ads within its own attribution window. It is not the brand's total sales, and it will not tie out to the sales report.",
	RoAS: "Ad revenue divided by ad spend. 4x means four rupees of attributed sales for every rupee billed. It inherits the marketplace's attribution, so treat it as a comparison between campaigns rather than a profit figure.",
	ACoS: "Ad spend as a percentage of ad revenue, the inverse of RoAS. Lower is better: 25% ACoS is the same statement as 4x RoAS.",
	Impressions:
		"How many times an ad was shown. It counts placements, not people, so one shopper scrolling a category can produce several.",
	"Add-to-carts":
		"Adds to cart the marketplace attributes to these ads. A cart is not an order, so this sits above units sold and the gap between them is abandonment.",
	"Units sold":
		"Units the marketplace attributes to these ads. Multiple units of one SKU in a single order each count.",
	"Active campaigns":
		"Campaigns that delivered at least once in this window. A campaign that exists but never served does not appear here.",
};

/**
 * How many tiles sit on one row, mirroring `grid-cols-2 lg:grid-cols-4`.
 *
 * Read from the same 1024px breakpoint Tailwind uses rather than measured off the DOM: the
 * grid is the source of truth for the layout, and matching its breakpoint keeps "the row"
 * meaning the same thing to the reader and to this component.
 */
const LG = "(min-width: 1024px)";

const useGridColumns = () => {
	const [cols, setCols] = useState(() =>
		typeof window !== "undefined" && window.matchMedia(LG).matches ? 4 : 2,
	);
	useEffect(() => {
		const mq = window.matchMedia(LG);
		const on = () => setCols(mq.matches ? 4 : 2);
		on();
		mq.addEventListener("change", on);
		return () => mq.removeEventListener("change", on);
	}, []);
	return cols;
};

/** min / max / mean of a daily series, with the days they fell on. */
const shape = (rows, pick) => {
	const points = rows
		.map((r) => ({ date: r.date, v: pick(r) }))
		.filter((p) => p.v != null && !Number.isNaN(p.v));
	if (!points.length) return null;
	const sorted = [...points].sort((a, b) => a.v - b.v);
	const sum = points.reduce((s, p) => s + p.v, 0);
	return {
		low: sorted[0],
		high: sorted[sorted.length - 1],
		mean: sum / points.length,
	};
};

const Tile = ({ tile, rows, prevRows, prevRange, open, onToggle }) => {
	const stats = tile.pick ? shape(rows, tile.pick) : null;
	const fmt = tile.format ?? ((v) => formatNumber(v));

	// A daily line where the metric HAS a daily series; two bars where it does not.
	//
	// ⚠️ Memoised. EChart re-applies its `option` whenever the object identity changes, and a
	// freshly built one every render meant `setOption` fired several times in the first
	// frames, each call restarting the draw-in until one of them snapped to the end. The
	// chart was finishing in ~120ms instead of animating. Now the option changes only when
	// the data does, so the animation runs once, uninterrupted.
	const chart = useMemo(
		() =>
			tile.pick
				? miniCompareOption(
						rows.map(tile.pick),
						(prevRows ?? []).map(tile.pick),
						{
							color: tile.sparkColor ?? SERIES[0],
							format: fmt,
						},
					)
				: twoBarOption(tile.raw, tile.prev, {
						color: tile.sparkColor ?? SERIES[0],
						format: fmt,
					}),
		// eslint-disable-next-line react-hooks/exhaustive-deps
		[tile.label, rows, prevRows, tile.raw, tile.prev],
	);

	return (
		<Card>
			<div className="flex items-start justify-between gap-2">
				<p className="flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
					{tile.label}
					<InfoTooltip label={ABOUT[tile.label]} />
				</p>
				<DeltaBadge
					delta={tile.delta}
					goodWhenDown={tile.goodWhenDown}
				/>
			</div>

			<p className="mt-2 font-display text-2xl font-semibold tracking-tight text-content tabular-nums">
				{tile.value}
			</p>

			{/* A sparkline only where a daily series actually exists (ACoS included, since it is
			    derivable per day). Two period totals are not a trend, so the metrics without one
			    stay bare here and show their comparison bars under Show comparison instead. The row
			    keeps its height either way, so a grid of tiles reads as one band rather than a
			    ragged edge. */}
			<div className="mt-2 flex h-8 items-end">
				{tile.pick ? (
					<Sparkline
						values={rows.map(tile.pick)}
						color={tile.sparkColor ?? SERIES[0]}
					/>
				) : null}
			</div>

			{/* The detail is a disclosure, not a permanent block: eight tiles each carrying five
			    extra numbers would bury the headline they exist to state. */}
			<button
				type="button"
				aria-expanded={open}
				onClick={onToggle}
				className="mt-4 flex items-center gap-1 text-xs font-medium text-content-muted transition-colors hover:text-brand"
			>
				{open ? "Hide comparison" : "Show comparison"}
				{open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
			</button>

			{open && (
				<div className="mt-2 border-t border-border pt-2">
					{/* The comparison as a CHART first: the shape of the two periods is the thing
					    worth seeing, and the numbers underneath say exactly what it shows. */}
					<EChart option={chart} height={120} />
					{/* Only the daily lines need a key. The two-bar comparison labels its own axis
					    ("Previous" / "This period"), so a caption under it just restated the chart. */}
					{tile.pick && (
						<p className="mt-1 text-[11px] text-content-subtle">
							Solid is this window, dashed is {prevRange.from} to{" "}
							{prevRange.to}.
						</p>
					)}
					<dl className="mt-2 space-y-1 text-xs">
						<div className="flex justify-between gap-3">
							<dt className="text-content-muted">
								Previous period
							</dt>
							<dd className="tabular-nums text-content">
								{tile.prev == null
									? "no prior data"
									: fmt(tile.prev)}
							</dd>
						</div>
						{tile.prev != null && tile.raw != null && (
							<div className="flex justify-between gap-3">
								<dt className="text-content-muted">Change</dt>
								<dd className="tabular-nums text-content">
									{tile.raw - tile.prev >= 0 ? "+" : "−"}
									{fmt(Math.abs(tile.raw - tile.prev))}
								</dd>
							</div>
						)}
						{stats && (
							<>
								<div className="flex justify-between gap-3">
									<dt className="text-content-muted">
										Daily average
									</dt>
									<dd className="tabular-nums text-content">
										{fmt(stats.mean)}
									</dd>
								</div>
								<div className="flex justify-between gap-3">
									<dt className="text-content-muted">
										Best day
									</dt>
									<dd className="tabular-nums text-content">
										{fmt(stats.high.v)}{" "}
										<span className="text-content-subtle">
											{formatDate(stats.high.date)}
										</span>
									</dd>
								</div>
								<div className="flex justify-between gap-3">
									<dt className="text-content-muted">
										Quietest day
									</dt>
									<dd className="tabular-nums text-content">
										{fmt(stats.low.v)}{" "}
										<span className="text-content-subtle">
											{formatDate(stats.low.date)}
										</span>
									</dd>
								</div>
							</>
						)}
					</dl>
				</div>
			)}
		</Card>
	);
};

/**
 * The headline strip. Each metric explains itself through an info icon and opens to its
 * previous-period value and the shape of its daily series.
 *
 * ACoS is lower-is-better, so its badge colours are inverted; nothing else here is judged.
 */
export const InsightsKpiStrip = ({ summary, performance = [] }) => {
	// The previous window is one request shared by every tile, made the first time any tile
	// is opened rather than on page load.
	const [wantPrev, setWantPrev] = useState(false);
	// Comparisons open a ROW at a time, not a tile: the point of opening one is to read it
	// against its neighbours, and a single tile expanding on its own leaves the three beside
	// it as a row of empty space. `null` means every row is closed.
	const [openRow, setOpenRow] = useState(null);
	const cols = useGridColumns();
	const { data: prev } = usePreviousPerformance(wantPrev);
	const prevRange = usePreviousRange();

	const m = (key) => summary?.[key] ?? {};
	const series = (fn) => performance.map(fn);

	const tiles = [
		{
			label: "Ad Spend",
			value: formatCurrency(m("ad_spend").value),
			raw: m("ad_spend").value,
			prev: m("ad_spend").prev,
			delta: m("ad_spend").delta_pct,
			series: series((r) => r.budget_consumed),
			pick: (r) => r.budget_consumed,
			format: formatCurrency,
			sparkColor: SERIES[0],
		},
		{
			label: "Ad Revenue",
			value: formatCurrency(m("ad_sales").value),
			raw: m("ad_sales").value,
			prev: m("ad_sales").prev,
			delta: m("ad_sales").delta_pct,
			series: series((r) => r.ad_sales),
			pick: (r) => r.ad_sales,
			format: formatCurrency,
			sparkColor: SERIES[1],
		},
		{
			label: "RoAS",
			value: formatRoas(m("roas").value),
			raw: m("roas").value,
			prev: m("roas").prev,
			delta: m("roas").delta_pct,
			series: series((r) => r.roas),
			pick: (r) => r.roas,
			format: formatRoas,
			sparkColor: SERIES[2],
		},
		{
			label: "ACoS",
			value: formatPercent(m("acos").value),
			raw: m("acos").value,
			prev: m("acos").prev,
			delta: m("acos").delta_pct,
			format: formatPercent,
			goodWhenDown: true,
			// Not a stored column: ACoS is spend ÷ revenue for the day, so the daily series
			// exists even though the endpoint does not carry it. Null on a day with no
			// revenue, because dividing by zero is not "0% ACoS". Kept as a FRACTION to match
			// what the endpoint returns for the headline, since both run through formatPercent.
			pick: (r) => (r.ad_sales ? r.budget_consumed / r.ad_sales : null),
			sparkColor: SERIES[4],
		},
		{
			label: "Impressions",
			value: formatNumber(m("impressions").value),
			raw: m("impressions").value,
			prev: m("impressions").prev,
			delta: m("impressions").delta_pct,
			series: series((r) => r.impressions),
			pick: (r) => r.impressions,
			sparkColor: SERIES[3],
		},
		{
			label: "Add-to-carts",
			value: formatNumber(m("atc").value),
			raw: m("atc").value,
			prev: m("atc").prev,
			delta: m("atc").delta_pct,
		},
		{
			label: "Units sold",
			value: formatNumber(m("units_sold").value),
			raw: m("units_sold").value,
			prev: m("units_sold").prev,
			delta: m("units_sold").delta_pct,
		},
		{
			label: "Active campaigns",
			value: formatNumber(m("active_campaigns").value),
			raw: m("active_campaigns").value,
			prev: m("active_campaigns").prev,
			delta: m("active_campaigns").delta_pct,
		},
	];

	return (
		<div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
			{tiles.map((t, i) => {
				const row = Math.floor(i / cols);
				return (
					<Tile
						key={t.label}
						tile={t}
						rows={performance}
						prevRows={prev ?? []}
						prevRange={prevRange}
						open={openRow === row}
						onToggle={() => {
							setOpenRow((r) => (r === row ? null : row));
							setWantPrev(true);
						}}
					/>
				);
			})}
		</div>
	);
};
