import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { CHART_THEME } from "./theme";

/**
 * Thin React wrapper around core ECharts (no `echarts-for-react` — it lags React
 * 19). Pass an ECharts `option` object; the wrapper inits once with our theme,
 * re-applies `option` on change, and resizes with its container.
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
