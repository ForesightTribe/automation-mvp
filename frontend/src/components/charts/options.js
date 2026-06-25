/**
 * ECharts `option` builders so every chart shares the same look (gradient area
 * fills, formatted axes/tooltips, consistent spacing). Components stay thin —
 * they fetch data and call a builder. Nulls are left as-is so charts show honest
 * gaps on days with no data.
 */
import { formatCompactCurrency, formatDate } from "../../lib/format";

// Token-ish palette (ECharts needs concrete hex; mirrors index.css).
const PRIMARY = "#4f46e5";
const SUCCESS = "#16a34a";
const INFO = "#0284c7";

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
