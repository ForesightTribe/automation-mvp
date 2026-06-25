import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import {
	GridComponent,
	TooltipComponent,
	LegendComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { CHART_THEME } from "./theme";

// Register only what we use — keeps the bundle small vs. importing all of echarts.
echarts.use([
	BarChart,
	LineChart,
	GridComponent,
	TooltipComponent,
	LegendComponent,
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
		const observer = new ResizeObserver(() => chartRef.current?.resize());
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
