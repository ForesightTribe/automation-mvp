import { formatCurrency, formatNumber } from "../../lib/format";
import { BU_BANDS } from "./buBands";

// Budget put to work, and budget left unused.
const BU_GREEN = BU_BANDS[0].hex;
const BU_RED = BU_BANDS[2].hex;

/**
 * Chart options for Insights.
 *
 * The categorical order below is FIXED and was validated, not chosen by eye: every adjacent
 * pair clears the colour-vision separation floor against the cream surface (worst pair
 * ΔE 15.0 deutan, 21.4 normal, all >= 3:1 contrast). Assign slots in this order and never
 * cycle them. Green and amber are absent on purpose: this system reserves them for status,
 * so a series painted green would read as "good" rather than "revenue".
 */
export const SERIES = ["#f42a34", "#4f46e5", "#0891b2", "#7c3aed", "#be185d"];

const SURFACE = "#ffffff";
const INK = "#000000";
const INK_MUTED = "#646160";
const INK_SUBTLE = "#939190";
const GRID = "#e0ddd8";

/** A vertical wash under a line: vivid at the line, gone by the axis. */
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

const AXIS_POINTER = {
	// A crosshair, so the reader can line a point up with its date without hunting.
	type: "line",
	lineStyle: { color: INK_SUBTLE, width: 1, type: [4, 4] },
	label: { show: false },
};

const TOOLTIP = {
	trigger: "axis",
	axisPointer: AXIS_POINTER,
	backgroundColor: SURFACE,
	borderColor: GRID,
	borderWidth: 1,
	padding: [8, 12],
	// Values and labels wear ink, never the series colour: the swatch beside them carries
	// identity, and coloured text reads as a state.
	textStyle: { color: INK, fontSize: 12 },
	extraCssText:
		"box-shadow: 0 8px 24px rgba(0,0,0,0.12); border-radius: 8px;",
};

const BASE_GRID = {
	left: 8,
	right: 16,
	top: 28,
	bottom: 8,
	containLabel: true,
};

/**
 * Charts draw themselves in rather than appearing fully formed: the line sweeps left to
 * right, so the eye follows time in the direction the axis runs. Kept short and eased out,
 * because an animation you wait for stops being alive and starts being slow. Series are
 * staggered by index so two lines do not race each other.
 */
const ANIMATE = {
	animation: true,
	animationDuration: 900,
	animationEasing: "cubicOut",
};

/**
 * A line that draws itself, and a stagger so two of them follow each other.
 *
 * ⚠️ `animationDelay` here MUST be a number, never a function of the data index. A function
 * switches ECharts to per-element animation, and a line with `showSymbol: false` has no
 * elements to animate: its sweep is a clip on the whole polyline, so per-element animation
 * has nothing to act on and the line simply appears. A plain number delays the series as a
 * unit and leaves the sweep intact.
 */
const draw = (order = 0) => ({
	animationDelay: order * 160,
	animationDurationUpdate: 400,
});

/** Bars are separate elements, so here a per-bar delay is exactly the right tool. */
const drawBars = (step = 220) => ({
	animationDelay: (idx) => idx * step,
	animationDurationUpdate: 400,
});

const axisLabel = { color: INK_MUTED, fontSize: 11 };

const lineSeries = (name, data, color, order = 0) => ({
	name,
	...draw(order),
	type: "line",
	data,
	smooth: 0.25,
	showSymbol: false,
	// The dot only appears where the reader is pointing, and it is big enough to see.
	symbolSize: 9,
	lineStyle: { width: 2, color },
	itemStyle: { color, borderColor: SURFACE, borderWidth: 2 },
	areaStyle: { color: fade(color) },
	emphasis: { focus: "series", scale: 1.1 },
});

/**
 * Spend vs revenue over time, or RoAS over time. NEVER both at once.
 *
 * A second y-axis is the most common way to make a chart lie: two scales share one plot and
 * the crossings mean nothing. RoAS is a ratio and money is money, so they are separate
 * views of the same data rather than two axes on one chart.
 */
export const insightsTrendOption = (
	rows,
	{ metric = "money", previous = null } = {},
) => {
	const dates = rows.map((r) => r.date);
	const money = metric === "money";

	/**
	 * The previous period, aligned by POSITION rather than date: day 1 against day 1, so a
	 * 30-day window compares with the 30 before it on one x-axis. Drawn dashed and unfilled
	 * so it reads as background against the current line rather than competing with it.
	 */
	const ghost = (name, values, color, order = 1) => ({
		name,
		...draw(order),
		type: "line",
		data: values,
		smooth: 0.25,
		showSymbol: false,
		symbolSize: 8,
		lineStyle: { width: 1.5, color, type: [5, 4], opacity: 0.75 },
		itemStyle: { color },
		emphasis: { focus: "series" },
		z: 1,
	});
	return {
		...ANIMATE,
		color: SERIES,
		tooltip: {
			...TOOLTIP,
			valueFormatter: (v) =>
				v == null
					? "—"
					: money
						? formatCurrency(v)
						: `${Number(v).toFixed(2)}x`,
		},
		// A legend whenever there are two or more series, so identity is never colour alone.
		legend:
			money || previous
				? {
						bottom: 0,
						icon: "roundRect",
						itemWidth: 10,
						itemHeight: 10,
						textStyle: { color: INK_MUTED, fontSize: 12 },
					}
				: { show: false }, // a lone series needs no legend; the title names it
		grid: { ...BASE_GRID, bottom: money || previous ? 28 : 8 },
		xAxis: {
			type: "category",
			data: dates,
			boundaryGap: false,
			axisLine: { lineStyle: { color: GRID } },
			axisTick: { show: false },
			axisLabel: { ...axisLabel, formatter: (d) => String(d).slice(5) },
		},
		yAxis: {
			type: "value",
			splitLine: { lineStyle: { color: GRID, type: [3, 3] } },
			axisLabel: {
				...axisLabel,
				formatter: (v) => (money ? formatNumber(v) : `${v}x`),
			},
		},
		series: money
			? [
					lineSeries(
						"Ad spend",
						rows.map((r) => r.budget_consumed),
						SERIES[0],
					),
					lineSeries(
						"Ad revenue",
						rows.map((r) => r.ad_sales),
						SERIES[1],
						1,
					),
					...(previous
						? [
								ghost(
									"Ad spend (previous)",
									previous.map((r) => r.budget_consumed),
									SERIES[0],
									2,
								),
								ghost(
									"Ad revenue (previous)",
									previous.map((r) => r.ad_sales),
									SERIES[1],
									3,
								),
							]
						: []),
				]
			: [
					lineSeries(
						"RoAS",
						rows.map((r) => r.roas),
						SERIES[2],
					),
					...(previous
						? [
								ghost(
									"RoAS (previous)",
									previous.map((r) => r.roas),
									SERIES[2],
									1,
								),
							]
						: []),
				],
	};
};

export const buCompareOption = (days) => ({
	...ANIMATE,
	// Status hues, deliberately, and the one place in this file they are used for a series.
	// Here they ARE the subject: green is budget put to work, red is budget left unused, and
	// the red band between the lines is literally the money that went unspent.
	color: [BU_GREEN, BU_RED],
	tooltip: {
		...TOOLTIP,
		formatter: (params) => {
			const i = Array.isArray(params)
				? params[0]?.dataIndex
				: params?.dataIndex;
			const d = days[i];
			if (!d) return "";
			if (d.bu == null) {
				return (
					`<div style="font-weight:600">${d.date}</div>` +
					`<div style="color:${INK_MUTED}">Did not run</div>`
				);
			}
			const swatch = (c) =>
				`<span style="display:inline-block;width:8px;height:8px;border-radius:2px;` +
				`background:${c};margin-right:6px"></span>`;
			const left = Math.max(0, d.allowed - d.spend);
			return (
				`<div style="font-weight:600">${d.date}</div>` +
				`<div>${swatch(BU_GREEN)}Ad spend <b>${formatCurrency(d.spend)}</b></div>` +
				`<div>${swatch(BU_RED)}Daily budget <b>${formatCurrency(d.allowed)}</b></div>` +
				(d.roas == null
					? ""
					: `<div>${swatch(INK_SUBTLE)}RoAS <b>${d.roas.toFixed(2)}x</b></div>`) +
				`<div style="margin-top:4px;color:${INK_MUTED}">Used ${d.bu.toFixed(1)}%` +
				(left > 0
					? `, ${formatCurrency(left)} left unspent`
					: ", the full budget") +
				`</div>`
			);
		},
	},
	legend: {
		bottom: 0,
		icon: "roundRect",
		itemWidth: 10,
		itemHeight: 10,
		textStyle: { color: INK_MUTED, fontSize: 12 },
	},
	grid: { ...BASE_GRID, top: 20, bottom: 28 },
	xAxis: {
		type: "category",
		data: days.map((d) => d.date),
		boundaryGap: false,
		axisLine: { lineStyle: { color: GRID } },
		axisTick: { show: false },
		axisLabel: { ...axisLabel, formatter: (d) => String(d).slice(5) },
	},
	yAxis: {
		type: "value",
		splitLine: { lineStyle: { color: GRID, type: [3, 3] } },
		axisLabel: { ...axisLabel, formatter: (v) => formatNumber(v) },
	},
	series: [
		// Drawn FIRST and filled, so the spend area sits on top of it: what remains visible
		// of the red is the gap between the two, which is the unspent budget.
		{
			name: "Daily budget",
			...draw(1),
			type: "line",
			step: "middle",
			data: days.map((d) => d.allowed),
			showSymbol: false,
			symbolSize: 8,
			connectNulls: false,
			lineStyle: { width: 1.5, color: BU_RED, type: [5, 4] },
			itemStyle: { color: BU_RED },
			areaStyle: { color: `${BU_RED}1f` },
			emphasis: { focus: "series" },
			z: 1,
		},
		{
			...lineSeries(
				"Ad spend",
				days.map((d) => d.spend),
				BU_GREEN,
				0,
			),
			connectNulls: false,
			z: 2,
		},
	],
});

/**
 * Share of spend. A donut answers "how is the whole divided", so it carries the total in
 * the middle and labels the slices directly rather than sending the eye to a legend.
 */
export const insightsDonutOption = (
	items,
	{
		total,
		centerLabel = "Total spend",
		radius = ["58%", "80%"],
		// Labels anchored to the chart's left and right edges, so a narrow box gives each label
		// the whole gap beside the ring instead of truncating it ("In…" for Instamart).
		labelsToEdge = false,
		// Only worth it with a handful of slices; past that they collide.
		showLabels = false,
	} = {},
) => ({
	...ANIMATE,
	// The donut grows from the centre and sweeps round, which reads as a whole being divided.
	animationDuration: 750,
	color: SERIES,
	tooltip: {
		...TOOLTIP,
		trigger: "item",
		axisPointer: undefined,
		formatter: (p) =>
			`${p.name}<br/>${formatCurrency(p.value)} · ${p.percent}%`,
	},
	legend: { show: false }, // slices are labelled directly, which beats a colour lookup
	series: [
		{
			type: "pie",
			radius,
			center: ["50%", "50%"],
			avoidLabelOverlap: true,
			// A 2px ring of the surface between slices, so adjacent fills never touch.
			itemStyle: {
				borderColor: SURFACE,
				borderWidth: 2,
				borderRadius: 4,
			},
			label: {
				show: showLabels,
				formatter: labelsToEdge
					? (p) =>
							`${p.name}\n${p.percent < 10 ? p.percent.toFixed(1) : Math.round(p.percent)}%`
					: "{b}\n{d}%",
				color: INK_MUTED,
				fontSize: 11,
				lineHeight: 15,
				...(labelsToEdge
					? { alignTo: "edge", edgeDistance: 2, minMargin: 6, overflow: "none" }
					: {}),
			},
			labelLine: labelsToEdge
				? { length: 8, length2: 0, maxSurfaceAngle: 80, lineStyle: { color: GRID } }
				: { length: 8, length2: 8, lineStyle: { color: GRID } },
			emphasis: {
				scale: true,
				scaleSize: 6,
				label: { color: INK, fontSize: 12, fontWeight: 600 },
			},
			data: items,
		},
	],
	graphic:
		total == null
			? undefined
			: [
					{
						type: "text",
						left: "center",
						top: "46%",
						style: {
							text: formatCurrency(total),
							fontSize: 20,
							fontWeight: 600,
							fill: INK,
							textAlign: "center",
						},
					},
					{
						type: "text",
						left: "center",
						top: "56%",
						style: {
							text: centerLabel,
							fontSize: 11,
							fill: INK_SUBTLE,
							textAlign: "center",
						},
					},
				],
});

/**
 * A tile's split by marketplace, as the top half of a donut. No labels and no centre
 * total — the tile's headline is the total and the row under the arc names each
 * marketplace with its figure.
 * Radii are pixels rather than percentages, which would be taken from the shorter side (the
 * height) and leave the arc a sliver in a wide tile.
 */
export const halfDonutOption = (
	items,
	{ format = formatNumber, height = 56 } = {},
) => ({
	...ANIMATE,
	animationDuration: 750,
	tooltip: {
		...TOOLTIP,
		trigger: "item",
		axisPointer: undefined,
		// The tile clips its canvas, and a tooltip kept inside 56px covers the arc it describes.
		appendToBody: true,
		formatter: (p) => `${p.name}<br/>${format(p.value)} · ${p.percent}%`,
	},
	legend: { show: false },
	series: [
		{
			type: "pie",
			startAngle: 180,
			endAngle: 360,
			center: ["50%", height - 2],
			// Thickness scales with the band too: a 16px arc inside a tall band
			// reads as a line bent round a corner rather than a donut.
			radius: [height - 38, height - 18],
			itemStyle: {
				borderColor: SURFACE,
				borderWidth: 2,
				borderRadius: 3,
			},
			label: { show: false },
			labelLine: { show: false },
			emphasis: { scale: true, scaleSize: 3 },
			data: items,
		},
	],
});

const MINI_GRID = { left: 4, right: 4, top: 16, bottom: 4, containLabel: true };

/**
 * A tile's own comparison: this window against the one before it, day for day.
 *
 * Same shape as the big trend chart so the two read alike, but stripped to what fits in a
 * card: no legend box (the tooltip names each line), sparse axis labels, one hue since it
 * is one metric measured twice.
 */
export const miniCompareOption = (
	current,
	previous,
	{ color = SERIES[0], format } = {},
) => ({
	...ANIMATE,
	color: [color],
	tooltip: {
		...TOOLTIP,
		valueFormatter: (v) =>
			v == null ? "—" : format ? format(v) : formatNumber(v),
	},
	legend: { show: false },
	grid: MINI_GRID,
	xAxis: {
		type: "category",
		data: current.map((_, i) => `Day ${i + 1}`),
		boundaryGap: false,
		axisLine: { lineStyle: { color: GRID } },
		axisTick: { show: false },
		axisLabel: { show: false },
	},
	yAxis: {
		type: "value",
		splitLine: { lineStyle: { color: GRID, type: [3, 3] } },
		axisLabel: {
			...axisLabel,
			fontSize: 10,
			formatter: (v) => formatNumber(v),
		},
	},
	series: [
		{
			name: "This period",
			...draw(0),
			type: "line",
			data: current,
			smooth: 0.25,
			showSymbol: false,
			symbolSize: 8,
			lineStyle: { width: 2, color },
			itemStyle: { color },
			areaStyle: { color: fade(color) },
		},
		{
			name: "Previous",
			...draw(1),
			type: "line",
			data: previous,
			smooth: 0.25,
			showSymbol: false,
			symbolSize: 8,
			lineStyle: { width: 1.5, color, type: [5, 4], opacity: 0.7 },
			itemStyle: { color },
			z: 1,
		},
	],
});

/**
 * For metrics the daily endpoint does not carry (add-to-carts, units sold, active
 * campaigns): the two period totals side by side. Two bars is still a chart, and it is the
 * honest one — inventing a daily line from a single total would draw data that does not exist.
 */
export const twoBarOption = (
	now,
	before,
	{ color = SERIES[0], format, bare = false } = {},
) => ({
	...ANIMATE,
	color: [color],
	tooltip: {
		...TOOLTIP,
		trigger: "item",
		axisPointer: undefined,
		valueFormatter: (v) =>
			v == null ? "—" : format ? format(v) : formatNumber(v),
	},
	grid: { ...MINI_GRID, bottom: bare ? 2 : 18, top: bare ? 6 : 16 },
	xAxis: {
		type: "category",
		data: ["Previous", "This period"],
		axisLine: { show: !bare, lineStyle: { color: GRID } },
		axisTick: { show: false },
		axisLabel: bare ? { show: false } : { ...axisLabel, fontSize: 10 },
	},
	yAxis: {
		type: "value",
		splitLine: { show: !bare, lineStyle: { color: GRID, type: [3, 3] } },
		axisLabel: bare
			? { show: false }
			: { ...axisLabel, fontSize: 10, formatter: (v) => formatNumber(v) },
	},
	series: [
		{
			type: "bar",
			...drawBars(),
			barWidth: "42%",
			// Rounded at the data end only, anchored to the baseline.
			itemStyle: { borderRadius: [4, 4, 0, 0] },
			data: [
				{ value: before ?? null, itemStyle: { color, opacity: 0.45 } },
				{ value: now ?? null, itemStyle: { color } },
			],
		},
	],
});

