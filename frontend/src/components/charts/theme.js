import * as echarts from "echarts/core";

/**
 * ECharts theme mirroring the index.css design tokens (kept in sync by hand —
 * ECharts needs concrete values, it can't read CSS variables). Registered once;
 * <EChart> inits every chart with it so colours/typography match the app.
 */
export const CHART_THEME = "foresight";

// Series palette — brand first, then the status hues, then a couple of extras.
const PALETTE = [
	"#4f46e5", // primary (indigo)
	"#0284c7", // info (sky)
	"#16a34a", // success (green)
	"#d97706", // warning (amber)
	"#dc2626", // danger (red)
	"#7c3aed", // violet
	"#0d9488", // teal
];

const CONTENT = "#000000";
const CONTENT_MUTED = "#646160";
const BORDER = "#e0ddd8";

echarts.registerTheme(CHART_THEME, {
	color: PALETTE,
	textStyle: {
		fontFamily:
			'"Inter", ui-sans-serif, system-ui, -apple-system, sans-serif',
		color: CONTENT_MUTED,
	},
	title: { textStyle: { color: CONTENT } },
	legend: { textStyle: { color: CONTENT_MUTED } },
	grid: {
		borderColor: BORDER,
		left: 8,
		right: 16,
		bottom: 8,
		top: 24,
		containLabel: true,
	},
	categoryAxis: {
		axisLine: { lineStyle: { color: BORDER } },
		axisTick: { show: false },
		axisLabel: { color: CONTENT_MUTED },
		splitLine: { show: false },
	},
	valueAxis: {
		axisLine: { show: false },
		axisTick: { show: false },
		axisLabel: { color: CONTENT_MUTED },
		splitLine: { lineStyle: { color: BORDER } },
	},
	tooltip: {
		backgroundColor: "#ffffff",
		borderColor: BORDER,
		textStyle: { color: CONTENT },
	},
});
