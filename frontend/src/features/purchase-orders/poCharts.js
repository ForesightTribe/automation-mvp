import { formatCompactCurrency } from "../../lib/format";

/** Chart options for the PO comparison: this window against the one before it. */
const INK = "#646160";
const GRID = "#e0ddd8";

const base = {
	animationDuration: 320,
	grid: { left: 4, right: 8, top: 14, bottom: 18, containLabel: true },
	tooltip: {
		trigger: "axis",
		backgroundColor: "#ffffff",
		borderColor: GRID,
		borderWidth: 1,
		textStyle: { color: "#000000", fontSize: 11 },
	},
};

const axisLabel = { color: INK, fontSize: 10 };

/** Two bars: previous against this period. */
export const comparisonBars = (now, before, { color, format } = {}) => {
	const fmt = format ?? formatCompactCurrency;
	return {
		...base,
		color: [color],
		tooltip: {
			...base.tooltip,
			trigger: "item",
			valueFormatter: (v) => (v == null ? "—" : fmt(v)),
		},
		xAxis: {
			type: "category",
			data: ["Previous", "This period"],
			axisLine: { lineStyle: { color: GRID } },
			axisTick: { show: false },
			axisLabel,
		},
		yAxis: {
			type: "value",
			splitLine: { lineStyle: { color: GRID, type: [3, 3] } },
			axisLabel: { ...axisLabel, formatter: (v) => fmt(v) },
		},
		series: [
			{
				type: "bar",
				barWidth: "42%",
				itemStyle: { borderRadius: [4, 4, 0, 0] },
				data: [before ?? 0, now ?? 0],
			},
		],
	};
};
