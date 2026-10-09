/**
 * ECharts `option` builders so every chart shares the same look (gradient area
 * fills, formatted axes/tooltips, consistent spacing). Components stay thin —
 * they fetch data and call a builder. Nulls are left as-is so charts show honest
 * gaps on days with no data.
 */
import {
	formatCompactCurrency,
	formatCurrency,
	formatDate,
	formatDayLabel,
	formatNumber,
} from "../../lib/format";

// Token-ish palette (ECharts needs concrete hex; mirrors index.css).
const PRIMARY = "#4f46e5";
const SUCCESS = "#16a34a";
const INFO = "#0284c7";
const WARNING = "#d97706";
// Foresight red. Used to mark where the reader is, never to signal a problem.
const BRAND = "#f42a34";

// Ad spend against ad revenue. Deliberately not the channel palette's yellow,
// orange or violet — those name a marketplace everywhere else on the page.
const AD_SPEND = "#D9468B";
const AD_SPEND_FILL = "#FDE7F3";
const AD_REVENUE = "#0F9FB5";
const AD_REVENUE_FILL = "#E5F5F8";

// Category-trend / heatmap series palette (mirrors theme.js PALETTE).
const SERIES_PALETTE = [
	"#4f46e5",
	"#0284c7",
	"#16a34a",
	"#d97706",
	"#dc2626",
	"#7c3aed",
	"#0d9488",
];

/** A bar fill that lifts toward its top, in the colour it is given. A flat
 *  slab of one hue reads as a block; the gradient gives it depth without
 *  bringing in a second colour. */
const barFill = (color) => ({
	type: "linear",
	x: 0,
	y: 0,
	x2: 0,
	y2: 1,
	colorStops: [
		{ offset: 0, color },
		{ offset: 1, color: `${color}b0` },
	],
});

/** Vertical fade fill from a hex color (appends alpha). */
const fade = (hex) => ({
	type: "linear",
	x: 0,
	y: 0,
	x2: 0,
	y2: 1,
	colorStops: [
		{ offset: 0, color: `${hex}59` },
		{ offset: 1, color: `${hex}05` },
	],
});

/** `fill` sets a flat tint under the line; without one the area fades from the
 *  line's own colour. */
const areaSeries = (name, data, color, { yAxisIndex = 0, fill, z } = {}) => ({
	name,
	type: "line",
	data,
	yAxisIndex,
	z,
	smooth: true,
	showSymbol: false,
	lineStyle: { width: 2.5, color },
	itemStyle: { color },
	areaStyle: { color: fill ?? fade(color) },
});

const baseGrid = { left: 8, right: 8, top: 24, bottom: 28, containLabel: true };

/** Ad Spend vs Ad Revenue — two gradient areas on a shared ₹ axis. */
export const spendRevenueOption = (rows) => ({
	tooltip: {
		trigger: "axis",
		valueFormatter: (v) => formatCurrency(v),
	},
	legend: { data: ["Ad Spend", "Ad Revenue"], bottom: 0 },
	grid: baseGrid,
	xAxis: {
		type: "category",
		boundaryGap: false,
		data: rows.map((r) => formatDate(r.date)),
	},
	yAxis: {
		type: "value",
		axisLabel: { formatter: (v) => formatCompactCurrency(v) },
	},
	series: [
		areaSeries(
			"Ad Spend",
			rows.map((r) => r.ad_spend),
			AD_SPEND,
			{ fill: AD_SPEND_FILL, z: 3 },
		),
		areaSeries(
			"Ad Revenue",
			rows.map((r) => r.ad_sales),
			AD_REVENUE,
			{ fill: AD_REVENUE_FILL, z: 2 },
		),
	],
});

/**
 * Ads page spend-vs-revenue trend: ad spend + ad revenue as gradient areas on a ₹
 * axis, with an optional RoAS line on a secondary axis (toggled in the card).
 * `rows` are `ads/performance` points (budget_consumed, ad_sales, roas).
 */
export const adTrendOption = (rows, { showRoas = false } = {}) => {
	const series = [
		areaSeries(
			"Ad Spend",
			rows.map((r) => r.budget_consumed),
			AD_SPEND,
			{ fill: AD_SPEND_FILL, z: 3 },
		),
		areaSeries(
			"Ad Revenue",
			rows.map((r) => r.ad_sales),
			AD_REVENUE,
			{ fill: AD_REVENUE_FILL, z: 2 },
		),
	];
	if (showRoas) {
		series.push({
			name: "RoAS",
			type: "line",
			yAxisIndex: 1,
			data: rows.map((r) => r.roas),
			smooth: true,
			showSymbol: false,
			lineStyle: { width: 2, color: WARNING },
			itemStyle: { color: WARNING },
		});
	}
	return {
		tooltip: {
			trigger: "axis",
			// RoAS rides in the tooltip whether or not it is drawn: it is a
			// ratio, and a second y-scale would let it cross the money lines at
			// points that mean nothing.
			formatter: (params) => {
				const p = Array.isArray(params) ? params : [params];
				if (!p.length) return "";
				const idx = p[0].dataIndex;
				const line = (dot, name, text) =>
					`<div style="display:flex;align-items:center;gap:6px;margin-top:3px">
						<span style="width:7px;height:7px;border-radius:50%;background:${dot}"></span>
						<span style="flex:1;color:#646160">${name}</span>
						<span style="font-weight:600">${text}</span>
					</div>`;
				const roas = rows[idx]?.roas;
				return (
					`<div style="font-weight:600;margin-bottom:2px">${p[0].axisValue}</div>` +
					p
						.filter((q) => q.seriesName !== "RoAS")
						.map((q) =>
							line(
								q.color,
								q.seriesName,
								q.value == null ? "—" : formatCurrency(q.value),
							),
						)
						.join("") +
					line(
						WARNING,
						"RoAS",
						roas == null ? "—" : `${roas.toFixed(2)}×`,
					)
				);
			},
		},
		legend: {
			data: showRoas
				? ["Ad Spend", "Ad Revenue", "RoAS"]
				: ["Ad Spend", "Ad Revenue"],
			bottom: 0,
		},
		grid: baseGrid,
		xAxis: {
			type: "category",
			boundaryGap: false,
			data: rows.map((r) => formatDate(r.date)),
		},
		yAxis: [
			{
				type: "value",
				axisLabel: { formatter: (v) => formatCompactCurrency(v) },
			},
			{
				type: "value",
				show: showRoas,
				axisLabel: { formatter: (v) => `${v.toFixed(1)}x` },
				splitLine: { show: false },
			},
		],
		series,
	};
};

/** Total store revenue per day (bars). */
export const revenueOption = (rows) => ({
	tooltip: {
		trigger: "axis",
		valueFormatter: (v) => formatCurrency(v),
	},
	grid: baseGrid,
	xAxis: {
		type: "category",
		data: rows.map((r) => formatDate(r.date)),
	},
	yAxis: {
		type: "value",
		axisLabel: { formatter: (v) => formatCompactCurrency(v) },
	},
	series: [
		{
			name: "Total Revenue",
			type: "bar",
			data: rows.map((r) => r.revenue),
			itemStyle: { color: INFO, borderRadius: [3, 3, 0, 0] },
		},
	],
});

/**
 * Single daily metric as bars — `metric` is "revenue" (₹) or "units". One clean
 * series on one axis; the Revenue/Units switch lives in the card header, and the
 * table view shows both columns together.
 */
export const dailyMetricOption = (rows, { metric = "revenue" } = {}) => {
	const money = metric === "revenue";
	const fmt = money ? formatCompactCurrency : formatNumber;
	// Tooltips show the exact figure; axis labels stay compact, since a
	// grouped number per gridline overflows the axis gutter.
	const tipFmt = money ? formatCurrency : formatNumber;
	const color = money ? INFO : WARNING;
	const valueOf = (r) =>
		metric === "revenue" ? r.revenue : (r.units_sold ?? r.units);
	return {
		tooltip: { trigger: "axis", valueFormatter: (v) => tipFmt(v) },
		grid: baseGrid,
		xAxis: {
			type: "category",
			data: rows.map((r) => formatDate(r.date)),
		},
		yAxis: { type: "value", axisLabel: { formatter: (v) => fmt(v) } },
		series: [
			{
				name: money ? "Revenue" : "Units",
				type: "bar",
				data: rows.map(valueOf),
				itemStyle: { color, borderRadius: [3, 3, 0, 0] },
			},
		],
	};
};

/**
 * Per-day units sold (bars, left axis) against frontend stock-on-hand (line,
 * right axis) for a single SKU — surfaces the sell-through vs. stock story, so a
 * stockout that flattened sales is visible at a glance. `rows` = [{ date,
 * units_sold, frontend_qty }]; nulls stay gaps.
 */
export const salesStockOption = (rows) => ({
	tooltip: { trigger: "axis" },
	legend: { data: ["Units sold", "Frontend stock"], bottom: 0 },
	grid: { ...baseGrid, bottom: 28 },
	xAxis: {
		type: "category",
		data: rows.map((r) => formatDate(r.date)),
	},
	yAxis: [
		{
			type: "value",
			axisLabel: { formatter: (v) => formatNumber(v) },
		},
		{
			type: "value",
			axisLabel: { formatter: (v) => formatNumber(v) },
			splitLine: { show: false },
		},
	],
	series: [
		{
			name: "Units sold",
			type: "bar",
			data: rows.map((r) => r.units_sold),
			itemStyle: { color: WARNING, borderRadius: [3, 3, 0, 0] },
		},
		{
			name: "Frontend stock",
			type: "line",
			yAxisIndex: 1,
			data: rows.map((r) => r.frontend_qty),
			smooth: true,
			showSymbol: false,
			lineStyle: { width: 2, color: INFO },
			itemStyle: { color: INFO },
		},
	],
});

/**
 * Horizontal ranked bars (top SKUs, top cities). `items` = [{ label, value }],
 * ordered best-first; rendered top-to-bottom. `money` picks the ₹ vs plain number
 * formatter.
 */
export const rankedBarOption = (
	items,
	{ color = PRIMARY, money = true } = {},
) => {
	const fmt = money ? formatCompactCurrency : formatNumber;
	// Tooltips show the exact figure; axis labels stay compact, since a
	// grouped number per gridline overflows the axis gutter.
	const tipFmt = money ? formatCurrency : formatNumber;
	// ECharts category axis draws bottom-up, so reverse to put the largest on top.
	const rows = [...items].reverse();
	return {
		tooltip: { trigger: "axis", valueFormatter: (v) => tipFmt(v) },
		grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
		xAxis: { type: "value", axisLabel: { formatter: (v) => fmt(v) } },
		yAxis: {
			type: "category",
			data: rows.map((r) => r.label),
			axisLabel: { width: 140, overflow: "truncate" },
		},
		series: [
			{
				type: "bar",
				data: rows.map((r) => r.value),
				itemStyle: { color, borderRadius: [0, 3, 3, 0] },
			},
		],
	};
};

/** Revenue-share donut. `items` = [{ name, value }]. */
export const donutOption = (items) => ({
	tooltip: {
		trigger: "item",
		valueFormatter: (v) => formatCurrency(v),
	},
	legend: { bottom: 0, type: "scroll" },
	series: [
		{
			type: "pie",
			radius: ["45%", "70%"],
			center: ["50%", "45%"],
			avoidLabelOverlap: true,
			itemStyle: { borderColor: "#ffffff", borderWidth: 2 },
			label: { show: false },
			data: items.map((it) => ({ name: it.name, value: it.value })),
		},
	],
});

/**
 * Stacked-area category trend. `dates` = x labels; `series` = [{ name, data[] }]
 * already aligned to `dates` (null on gap days).
 */
export const categoryTrendOption = (dates, series) => ({
	tooltip: {
		trigger: "axis",
		valueFormatter: (v) => (v == null ? "—" : formatCurrency(v)),
	},
	legend: { bottom: 0, type: "scroll" },
	grid: { ...baseGrid, bottom: 28 },
	xAxis: {
		type: "category",
		boundaryGap: false,
		data: dates.map((d) => formatDate(d)),
	},
	yAxis: {
		type: "value",
		axisLabel: { formatter: (v) => formatCompactCurrency(v) },
	},
	series: series.map((s, i) => {
		const color = SERIES_PALETTE[i % SERIES_PALETTE.length];
		return {
			name: s.name,
			type: "line",
			stack: "total",
			data: s.data,
			smooth: true,
			showSymbol: false,
			lineStyle: { width: 1.5, color },
			itemStyle: { color },
			areaStyle: { color: fade(color) },
		};
	}),
});

/** The fold-in bucket for everything past the palette — always the neutral hue. */
const OTHER_COLOR = "#94a3b8";

/**
 * Horizontal stacked bars — bar length is a total, segments split it by a second
 * dimension. `bars` = the category-axis labels (largest first); `series` =
 * [{ name, data[] }] aligned to `bars`. The "Other" series (if present) always
 * takes the neutral hue, so real entities keep a stable palette slot. Segments are
 * separated by a 2px surface gap; the tooltip lists the split plus the bar total.
 */
export const stackedBarOption = (
	bars,
	series,
	{ otherName = "Other" } = {},
) => {
	// ECharts draws the category axis bottom-up, so reverse to put the largest on top.
	const labels = [...bars].reverse();
	let hue = 0;
	return {
		tooltip: {
			trigger: "axis",
			axisPointer: { type: "shadow" },
			formatter: (points) => {
				const total = points.reduce((s, p) => s + (p.value || 0), 0);
				const lines = points
					.filter((p) => p.value)
					.sort((a, b) => b.value - a.value)
					.map(
						(p) =>
							`${p.marker} ${p.seriesName}<span style="float:right;margin-left:16px">${formatCompactCurrency(p.value)}</span>`,
					);
				return [
					`<strong>${points[0].axisValue}</strong>`,
					...lines,
					`Total<span style="float:right;margin-left:16px"><strong>${formatCompactCurrency(total)}</strong></span>`,
				].join("<br/>");
			},
		},
		legend: { bottom: 0, type: "scroll" },
		grid: { left: 8, right: 24, top: 8, bottom: 32, containLabel: true },
		xAxis: {
			type: "value",
			axisLabel: { formatter: (v) => formatCompactCurrency(v) },
		},
		yAxis: {
			type: "category",
			data: labels,
			axisLabel: { width: 140, overflow: "truncate" },
		},
		series: series.map((s) => {
			const color =
				s.name === otherName
					? OTHER_COLOR
					: SERIES_PALETTE[hue++ % SERIES_PALETTE.length];
			return {
				name: s.name,
				type: "bar",
				stack: "total",
				data: [...s.data].reverse(),
				itemStyle: {
					color,
					borderColor: "#ffffff",
					borderWidth: 2,
				},
			};
		}),
	};
};

/**
 * Share-of-voice trend — one gradient area (single series, so no legend; the card
 * title names it). `rows` are `competition/share-of-voice` points; `avg_sov` is a
 * 0–100 percent number (not a fraction).
 */
export const sovTrendOption = (rows) => {
	const pct = (v) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);
	return {
		tooltip: { trigger: "axis", valueFormatter: pct },
		grid: baseGrid,
		xAxis: {
			type: "category",
			boundaryGap: false,
			data: rows.map((r) => formatDate(r.date)),
		},
		yAxis: {
			type: "value",
			axisLabel: { formatter: (v) => `${v}%` },
		},
		series: [
			areaSeries(
				"Share of Voice",
				rows.map((r) => r.avg_sov),
				PRIMARY,
			),
		],
	};
};

/**
 * Weekly on-shelf availability % trend — one gradient area on a 0–100 axis. `rows`
 * are `inventory/availability-history` points (`week`, `availability_pct`).
 */
export const availabilityTrendOption = (rows) => {
	const pct = (v) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);
	return {
		tooltip: { trigger: "axis", valueFormatter: pct },
		grid: baseGrid,
		xAxis: {
			type: "category",
			boundaryGap: false,
			data: rows.map((r) => formatDate(r.week)),
		},
		yAxis: {
			type: "value",
			max: 100,
			axisLabel: { formatter: (v) => `${v}%` },
		},
		series: [
			areaSeries(
				"Availability",
				rows.map((r) => r.availability_pct),
				SUCCESS,
			),
		],
	};
};

/**
 * Rank heatmap — keywords (x) × cities (y), colour = own-brand rank (sequential;
 * lower rank is better, so darker = weaker, drawing the eye to weak spots). No
 * per-cell numbers (the Table view carries exact ranks); tooltip shows rank + SoV.
 * `data` = [{ value: [xIdx, yIdx, rank], sov }]; `maxRank` caps the scale.
 */
export const rankHeatmapOption = (keywords, cities, data, maxRank) => ({
	tooltip: {
		position: "top",
		formatter: (p) =>
			`${cities[p.value[1]]} · ${keywords[p.value[0]]}<br/>Rank #${p.value[2]}` +
			(p.data?.sov != null
				? ` · SoV ${Number(p.data.sov).toFixed(1)}%`
				: ""),
	},
	grid: { left: 8, right: 16, top: 8, bottom: 48, containLabel: true },
	xAxis: {
		type: "category",
		data: keywords,
		axisLabel: { interval: 0, rotate: 30 },
		splitArea: { show: true },
	},
	yAxis: {
		type: "category",
		data: cities,
		axisLabel: { width: 110, overflow: "truncate" },
		splitArea: { show: true },
	},
	visualMap: {
		min: 1,
		max: maxRank || 12,
		calculable: true,
		orient: "horizontal",
		left: "center",
		bottom: 8,
		text: ["weaker", "stronger"],
		inRange: { color: ["#eef2ff", "#4f46e5"] },
		formatter: (v) => `#${Math.round(v)}`,
	},
	series: [
		{
			type: "heatmap",
			data,
			label: { show: false },
			emphasis: {
				itemStyle: { shadowBlur: 6, shadowColor: "#00000055" },
			},
		},
	],
});

/** "2026-06" -> "Jun 26". */
const monthLabel = (ym) =>
	new Date(`${ym}-01T00:00:00`).toLocaleString("en-IN", {
		month: "short",
		year: "2-digit",
	});

/**
 * Month-on-month series for the Operations row. `kind` picks the formatter:
 * "percent" (0–100, capped axis) or "currency" (₹). `type` is "line" (gradient
 * area) or "bar".
 */
export const monthlySeriesOption = (
	rows,
	{ key, label, color, type = "line", kind = "currency" },
) => {
	const fmt =
		kind === "percent"
			? (v) => `${Math.round(v)}%`
			: (v) => formatCompactCurrency(v);
	// Tooltip shows the exact figure; `fmt` stays compact for the axis labels.
	const tipFmt =
		kind === "percent"
			? (v) => `${Math.round(v)}%`
			: (v) => formatCurrency(v);
	const data = rows.map((r) => r[key]);
	return {
		tooltip: { trigger: "axis", valueFormatter: tipFmt },
		grid: baseGrid,
		xAxis: {
			type: "category",
			boundaryGap: type === "bar",
			data: rows.map((r) => monthLabel(r.month)),
		},
		yAxis: {
			type: "value",
			axisLabel: { formatter: fmt },
			...(kind === "percent" ? { max: 100 } : {}),
		},
		series: [
			type === "bar"
				? {
						name: label,
						type: "bar",
						data,
						itemStyle: { color, borderRadius: [3, 3, 0, 0] },
					}
				: areaSeries(label, data, color),
		],
	};
};

const DANGER = "#dc2626";

/** Percent value (0–100) formatter for scorecard axes/tooltips. */
const pctFmt = (v) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);

const SCORECARD_TREND_META = {
	fill_rate: { label: "Fill rate", percent: true, color: SUCCESS },
	weighted_fill_rate_percent: {
		label: "Weighted fill rate",
		percent: true,
		color: INFO,
	},
	potential_loss: { label: "Potential loss", percent: false, color: DANGER },
	total_gmv: { label: "Total GMV", percent: false, color: PRIMARY },
};

/**
 * Scorecard week-over-week trend (single gradient area). `rows` are
 * `scorecard/trend` points (from_date + overall metrics); `metric` picks the
 * series — percent metrics (fill rate) use a 0–100 axis, the rest a ₹ axis.
 */
export const scorecardTrendOption = (rows, { metric = "fill_rate" } = {}) => {
	const meta = SCORECARD_TREND_META[metric] ?? SCORECARD_TREND_META.fill_rate;
	const fmt = meta.percent ? pctFmt : (v) => formatCompactCurrency(v);
	const tipFmt = meta.percent ? pctFmt : (v) => formatCurrency(v);
	return {
		tooltip: { trigger: "axis", valueFormatter: tipFmt },
		grid: baseGrid,
		xAxis: {
			type: "category",
			boundaryGap: false,
			data: rows.map((r) => formatDate(r.from_date)),
		},
		yAxis: {
			type: "value",
			axisLabel: { formatter: fmt },
			...(meta.percent ? { max: 100 } : {}),
		},
		series: [
			areaSeries(
				meta.label,
				rows.map((r) => r[metric]),
				meta.color,
			),
		],
	};
};

/**
 * Per-category fill rate as horizontal bars (best-first). `items` =
 * [{ label, value }] where value is a 0–100 fill-rate percent.
 */
export const categoryFillOption = (items) => {
	const rows = [...items].reverse(); // ECharts draws category axis bottom-up
	return {
		tooltip: { trigger: "axis", valueFormatter: pctFmt },
		grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
		xAxis: {
			type: "value",
			max: 100,
			axisLabel: { formatter: (v) => `${v}%` },
		},
		yAxis: {
			type: "category",
			data: rows.map((r) => r.label),
			axisLabel: { width: 140, overflow: "truncate" },
		},
		series: [
			{
				type: "bar",
				data: rows.map((r) => r.value),
				itemStyle: { color: SUCCESS, borderRadius: [0, 3, 3, 0] },
			},
		],
	};
};

/** Minimal sparkline for KPI tiles — no axes, no tooltip, just the trend. */
export const sparklineOption = (values, color = PRIMARY) => ({
	grid: { left: 0, right: 0, top: 2, bottom: 2 },
	xAxis: {
		type: "category",
		show: false,
		boundaryGap: false,
		data: values.map((_, i) => i),
	},
	yAxis: { type: "value", show: false, scale: true },
	tooltip: { show: false },
	series: [
		{
			type: "line",
			data: values,
			smooth: true,
			showSymbol: false,
			lineStyle: { width: 1.5, color },
			areaStyle: { color: fade(color) },
		},
	],
});

/**
 * A KPI's trajectory with the context needed to read it: the previous
 * equal-length period as a faint line behind, the best and worst days marked,
 * and the latest value labelled on the point rather than in a legend.
 *
 * No target line — this product has no revenue target, and drawing one would
 * invent the very thing the numbers are being measured against.
 */
export const trajectoryOption = (
	rows,
	previous = [],
	{
		key = "revenue",
		color = INFO,
		format,
		overlay,
		kind = "line",
		breakdown,
		split = [],
		legend = true,
		focus,
	} = {},
) => {
	// Bars carry best and worst in the bar's own colour; lines use markers.

	const isBar = kind === "bar";
	const stacked = isBar && split.length > 0;
	const lined = !isBar && split.length > 0;
	// Pointing at one channel pushes the rest back rather than hiding them: the
	// line being followed still has the others to be read against.
	const DIM = 0.15;
	const dim = (name) => (focus && focus !== name ? DIM : 1);
	const fmt = format ?? formatCompactCurrency;
	const values = rows.map((r) => r[key]);
	const real = values.map((v, i) => [i, v]).filter(([, v]) => v != null);
	const lastIndex = real.length ? real[real.length - 1][0] : -1;
	const best = real.length
		? real.reduce((a, b) => (b[1] > a[1] ? b : a))
		: null;
	const worst = real.length
		? real.reduce((a, b) => (b[1] < a[1] ? b : a))
		: null;

	const mark = (point, dotColor, size = 8) => ({
		coord: point,
		symbolSize: size,
		itemStyle: {
			color: dotColor,
			borderColor: "#ffffff",
			borderWidth: 1.5,
		},
	});
	const marks = [];
	if (best) marks.push(mark(best, SUCCESS));
	// Worst day in amber, not red: the reported day is marked in BRAND red just
	// below, and two near-identical reds on one line would read as one signal.
	if (worst && worst[0] !== best?.[0]) marks.push(mark(worst, WARNING));
	// The day the headline refers to, in the brand colour — this marks WHERE YOU
	// ARE on the line, which is identity, not a business state. Drawn last and
	// larger so it sits above the context markers.
	const dayPoint = real.length ? real[real.length - 1] : null;
	if (dayPoint) marks.push(mark(dayPoint, BRAND, 11));

	return {
		grid: {
			left: 12,
			right: 68,
			top: 20,
			bottom: split.length > 0 && legend ? 30 : 12,
			containLabel: true,
		},
		legend:
			split.length > 0 && legend
				? {
						bottom: 0,
						icon: "circle",
						itemWidth: 8,
						itemHeight: 8,
						textStyle: { color: "#646160", fontSize: 11 },
						data: split.map((b) => b.name),
					}
				: undefined,
		xAxis: {
			type: "category",
			boundaryGap: isBar,
			data: rows.map((r) => formatDayLabel(r.date)),
			axisTick: { show: false },
			axisLine: { lineStyle: { color: "#e0ddd8" } },
			axisLabel: {
				color: "#646160",
				fontSize: 10,
				hideOverlap: true,
				margin: 12,
				// With boundaryGap off the first point sits ON the axis, so a
				// centred label spills left across the y-axis figures. Anchor
				// the end labels inside the plot instead.
				alignMinLabel: "left",
				alignMaxLabel: "right",
			},
		},
		yAxis: {
			type: "value",
			// A bar's length IS its value, so its axis has to start at zero. It
			// also keeps the scale still when a second measure is drawn.
			scale: !isBar,
			splitNumber: 3,
			axisLabel: {
				color: "#646160",
				fontSize: 10,
				margin: 14,
				formatter: (v) => fmt(v),
			},
			splitLine: { lineStyle: { color: "#e0ddd8", type: [3, 3] } },
		},
		tooltip: {
			trigger: "axis",
			backgroundColor: "#ffffff",
			borderColor: "#e0ddd8",
			borderWidth: 1,
			textStyle: { color: "#000000", fontSize: 11 },
			// Exact rupees on hover; the axis keeps its short form so gridline
			// labels do not eat the plot.
			valueFormatter: (v) =>
				v == null ? "—" : format ? fmt(v) : formatCurrency(v),
			// With a breakdown the day's total is shown with its parts under it,
			// whatever is drawn — so the split is one hover away rather than
			// something the reader has to go and point at in the list first.
			formatter: breakdown
				? (params) => {
						const p0 = Array.isArray(params) ? params[0] : params;
						if (!p0) return "";
						const i = p0.dataIndex;
						const money = (v) =>
							v == null
								? "—"
								: format
									? fmt(v)
									: formatCurrency(v);
						const line = (dot, name, v, fmtOne) =>
							`<div style="display:flex;align-items:center;gap:6px;margin-top:3px">
								<span style="width:7px;height:7px;border-radius:50%;background:${dot}"></span>
								<span style="flex:1;color:#646160">${name}</span>
								<span style="font-weight:600">${fmtOne ? fmtOne(v) : money(v)}</span>
							</div>`;
						const total = values[i];
						return (
							`<div style="font-weight:600;margin-bottom:2px">${p0.axisValue}</div>` +
							line(color, "Revenue", total) +
							split
								.map((b) => line(b.color, b.name, b.data[i]))
								.join("") +
							breakdown
								.map((b) =>
									line(b.color, b.name, b.data[i], b.format),
								)
								.join("")
						);
					}
				: undefined,
		},
		series: [
			// The measure split by channel, stacked so the column's height is
			// still the day's total and each band is read as its share of it.
			...(stacked
				? split.map((b, idx) => ({
						name: b.name,
						type: "bar",
						stack: "channels",
						data: b.data,
						barMaxWidth: 18,
						itemStyle: {
							color: barFill(b.color),
							opacity: dim(b.name),
							borderRadius:
								idx === split.length - 1 ? [3, 3, 0, 0] : 0,
						},
						// Solid on hover, so the band being read lifts out of
						// the column.
						emphasis: { itemStyle: { color: b.color } },
						z: focus === b.name ? 4 : 2,
					}))
				: []),
			// On a line chart the same split is a line each, so the channels are
			// compared against one another rather than read as shares of a column.
			...(lined
				? split.map((b) => ({
						name: b.name,
						type: "line",
						data: b.data,
						smooth: true,
						showSymbol: false,
						connectNulls: false,
						lineStyle: {
							width: focus === b.name ? 2.5 : 1.5,
							color: b.color,
							opacity: dim(b.name),
						},
						itemStyle: { color: b.color, opacity: dim(b.name) },
						z: focus === b.name ? 4 : 2,
					}))
				: []),
			// An optional second measure, shown while the reader points at it in
			// the breakdown — so the figure and its shape over time are the same
			// gesture rather than two separate lookups.
			// Ad and organic revenue are PARTS of the revenue drawn here, so on
			// bars they split the bar rather than floating over it: the column's
			// total height never changes, and the share is read directly.
			...(overlay && isBar && !stacked
				? [
						{
							name: overlay.name,
							type: "bar",
							stack: "total",
							data: overlay.data,
							barMaxWidth: 18,
							itemStyle: { color: overlay.color },
							z: 3,
						},
						{
							name: "Rest of revenue",
							type: "bar",
							stack: "total",
							data: values.map((v, i) => {
								const part = overlay.data[i];
								return v == null || part == null
									? null
									: Math.max(0, v - part);
							}),
							barMaxWidth: 18,
							itemStyle: {
								color,
								opacity: 0.25,
								borderRadius: [3, 3, 0, 0],
							},
							z: 3,
						},
					]
				: []),
			...(overlay && (!isBar || stacked)
				? [
						{
							name: overlay.name,
							type: "line",
							data: overlay.data,
							smooth: true,
							showSymbol: false,
							lineStyle: { width: 2, color: overlay.color },
							itemStyle: { color: overlay.color },
							z: 3,
						},
					]
				: []),
			{
				name: "Previous period",
				type: "line",
				data: previous.map((r) => r[key]),
				smooth: true,
				showSymbol: false,
				lineStyle: {
					width: 1.5,
					color: "#c8c5c2",
					opacity: focus ? DIM : 1,
				},
				itemStyle: { color: "#c8c5c2", opacity: focus ? DIM : 1 },
				z: 1,
			},
			{
				name: "This period",
				type: isBar ? "bar" : "line",
				// Renders nothing while the split is drawn — that pair carries the
				// total. The axis value label still comes from here.
				silent: Boolean(isBar && (overlay || stacked)),
				// Stacked with the split, so the empty series claims no slot of
				// its own in the category band.
				...(isBar && (overlay || stacked)
					? { stack: stacked ? "channels" : "total" }
					: {}),
				data:
					isBar && (overlay || stacked)
						? []
						: isBar
							? values.map((v, i) => ({
									value: v,
									itemStyle: {
										color: barFill(
											i === best?.[0]
												? SUCCESS
												: i === worst?.[0]
													? WARNING
													: color,
										),
										opacity: overlay ? 0.3 : 1,
										borderRadius: [3, 3, 0, 0],
									},
								}))
							: values,
				barMaxWidth: 18,
				smooth: true,
				showSymbol: false,
				// Steps back while a second measure is drawn over it, so the
				// line being pointed at is the one that reads.
				lineStyle: {
					width: 2.5,
					color,
					opacity: focus ? DIM : overlay ? 0.3 : 1,
				},
				itemStyle: {
					color,
					opacity: focus ? DIM : overlay ? 0.3 : 1,
				},
				z: 2,
				// The best/worst/today markers belong to the total, so they come
				// off while a single channel is being followed.
				markPoint:
					isBar || focus
						? undefined
						: {
								symbol: "circle",
								symbolSize: 8,
								label: { show: false },
								data: marks,
							},
				markLine:
					lastIndex >= 0
						? {
								symbol: "none",
								silent: true,
								lineStyle: { width: 0 },
								label: {
									position: "end",
									color: "#000000",
									fontSize: 11,
									fontWeight: 600,
									formatter: () => fmt(values[lastIndex]),
								},
								data: [{ yAxis: values[lastIndex] }],
							}
						: undefined,
			},
		],
	};
};
