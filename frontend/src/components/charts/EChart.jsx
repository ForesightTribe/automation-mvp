import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart, HeatmapChart } from "echarts/charts";
import {
	GridComponent,
	TooltipComponent,
	LegendComponent,
	VisualMapComponent,
	GraphicComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { CHART_THEME } from "./theme";

// Register only what we use — keeps the bundle small vs. importing all of echarts.
echarts.use([
	BarChart,
	LineChart,
	PieChart,
	HeatmapChart,
	GridComponent,
	TooltipComponent,
	LegendComponent,
	VisualMapComponent,
	// The donut's centre total is drawn with `graphic`; without this it silently does not
	// render and ECharts only warns in the console.
	GraphicComponent,
	CanvasRenderer,
]);

/**
 * Thin React wrapper around modular ECharts (no `echarts-for-react` — it lags
 * React 19). Pass an ECharts `option` object; the wrapper inits once with our
 * theme, re-applies `option` on change, and resizes with its container.
 *
 * Usage:
 *   <EChart option={{ xAxis: {...}, yAxis: {...}, series: [...] }} height={320} />
 */
export const EChart = ({ option, height = 320, className = "" }) => {
	const elRef = useRef(null);
	const chartRef = useRef(null);

	// Init + teardown once.
	useEffect(() => {
		chartRef.current = echarts.init(elRef.current, CHART_THEME);
		// ⚠️ A ResizeObserver fires once immediately on observe, reporting the size the
		// element already had. Acting on it calls `resize()` on a chart that is mid-draw,
		// which cancels the build-in animation and repaints the final frame: the chart
		// appears fully formed instead of drawing itself.
		//
		// Skipping that first callback outright is wrong too, because a chart initialised
		// before layout starts at 0×0 and that callback is what gives it a size. So compare
		// instead: resize only when the size actually differs from the one the chart was
		// last rendered at. A no-op resize is the only one that costs an animation.
		let last = {
			w: elRef.current.clientWidth,
			h: elRef.current.clientHeight,
		};
		const observer = new ResizeObserver(() => {
			const el = elRef.current;
			if (!el) return;
			const w = el.clientWidth;
			const h = el.clientHeight;
			if (w === last.w && h === last.h) return;
			last = { w, h };
			chartRef.current?.resize();
		});
		observer.observe(elRef.current);
		return () => {
			observer.disconnect();
			chartRef.current?.dispose();
		};
	}, []);

	// Re-apply option whenever it changes. `notMerge: true` so removed series
	// don't linger between renders.
	useEffect(() => {
		if (option) chartRef.current?.setOption(option, true);
	}, [option]);

	return <div ref={elRef} className={className} style={{ height }} />;
};
