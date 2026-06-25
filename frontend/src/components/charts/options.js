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
 * Horizontal ranked bars (top SKUs, top cities). `items` = [{ label, value }],
 * ordered best-first; rendered top-to-bottom. `money` picks the ₹ vs plain number
 * formatter.
 */
export const rankedBarOption = (items, { color = PRIMARY, money = true } = {}) => {
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

/**
 * City × category heatmap. `cities` = y labels, `categories` = x labels,
 * `cells` = [[xIdx, yIdx, value]], `max` caps the colour scale.
 */
export const heatmapOption = (cities, categories, cells, max) => ({
	tooltip: {
		position: "top",
		formatter: (p) =>
			`${cities[p.value[1]]} · ${categories[p.value[0]]}<br/>${formatCompactCurrency(
				p.value[2],
			)}`,
	},
	grid: { left: 8, right: 16, top: 8, bottom: 60, containLabel: true },
	xAxis: {
		type: "category",
		data: categories,
		axisLabel: { interval: 0, rotate: 30 },
		splitArea: { show: true },
	},
	yAxis: {
		type: "category",
		data: cities,
		axisLabel: { width: 120, overflow: "truncate" },
		splitArea: { show: true },
	},
	visualMap: {
		min: 0,
		max: max || 1,
		calculable: true,
		orient: "horizontal",
		left: "center",
		bottom: 8,
		inRange: { color: ["#eef2ff", "#4f46e5"] },
		formatter: (v) => formatCompactCurrency(v),
	},
	series: [
		{
			type: "heatmap",
			data: cells,
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
