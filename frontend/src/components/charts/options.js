/**
 * ECharts `option` builders so every chart shares the same look (gradient area
 * fills, formatted axes/tooltips, consistent spacing). Components stay thin —
 * they fetch data and call a builder. Nulls are left as-is so charts show honest
 * gaps on days with no data.
 */
import {
	formatCompactCurrency,
	formatDate,
	formatNumber,
} from "../../lib/format";

// Token-ish palette (ECharts needs concrete hex; mirrors index.css).
const PRIMARY = "#4f46e5";
const SUCCESS = "#16a34a";
const INFO = "#0284c7";
const WARNING = "#d97706";

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

/** Vertical fade fill from a hex color (appends alpha). */
const fade = (hex) => ({
	type: "linear",
	x: 0,
	y: 0,
	x2: 0,
	y2: 1,
	colorStops: [
		{ offset: 0, color: `${hex}33` },
		{ offset: 1, color: `${hex}00` },
	],
});

const areaSeries = (name, data, color, yAxisIndex = 0) => ({
	name,
	type: "line",
	data,
	yAxisIndex,
	smooth: true,
	showSymbol: false,
	lineStyle: { width: 2, color },
	itemStyle: { color },
	areaStyle: { color: fade(color) },
});

const baseGrid = { left: 8, right: 8, top: 24, bottom: 28, containLabel: true };

/** Ad Spend vs Ad Revenue — two gradient areas on a shared ₹ axis. */
export const spendRevenueOption = (rows) => ({
	tooltip: {
		trigger: "axis",
		valueFormatter: (v) => formatCompactCurrency(v),
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
			PRIMARY,
		),
		areaSeries(
			"Ad Revenue",
			rows.map((r) => r.ad_sales),
			SUCCESS,
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
			PRIMARY,
		),
		areaSeries(
			"Ad Revenue",
			rows.map((r) => r.ad_sales),
			SUCCESS,
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
		tooltip: { trigger: "axis" },
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
		valueFormatter: (v) => formatCompactCurrency(v),
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
	const color = money ? INFO : WARNING;
	const valueOf = (r) =>
		metric === "revenue" ? r.revenue : (r.units_sold ?? r.units);
	return {
		tooltip: { trigger: "axis", valueFormatter: (v) => fmt(v) },
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
	// ECharts category axis draws bottom-up, so reverse to put the largest on top.
	const rows = [...items].reverse();
	return {
		tooltip: { trigger: "axis", valueFormatter: (v) => fmt(v) },
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
		valueFormatter: (v) => formatCompactCurrency(v),
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
		valueFormatter: (v) => (v == null ? "—" : formatCompactCurrency(v)),
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
export const stackedBarOption = (bars, series, { otherName = "Other" } = {}) => {
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
		series: [areaSeries("Share of Voice", rows.map((r) => r.avg_sov), PRIMARY)],
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
		series: [areaSeries("Availability", rows.map((r) => r.availability_pct), SUCCESS)],
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
			(p.data?.sov != null ? ` · SoV ${Number(p.data.sov).toFixed(1)}%` : ""),
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
			emphasis: { itemStyle: { shadowBlur: 6, shadowColor: "#0f172a55" } },
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
	const data = rows.map((r) => r[key]);
	return {
		tooltip: { trigger: "axis", valueFormatter: fmt },
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
	return {
		tooltip: { trigger: "axis", valueFormatter: fmt },
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
		series: [areaSeries(meta.label, rows.map((r) => r[metric]), meta.color)],
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
