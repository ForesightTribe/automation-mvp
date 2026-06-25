import { useMemo } from "react";
import { EChart } from "./EChart";
import { sparklineOption } from "./options";

/**
 * Tiny inline trend line for KPI tiles. `values` may contain nulls (gaps are
 * preserved). Renders nothing if there aren't at least two real points to draw.
 */
export const Sparkline = ({ values, color, height = 32 }) => {
	const option = useMemo(
		() => sparklineOption(values ?? [], color),
		[values, color],
	);
	const realPoints = (values ?? []).filter(
		(v) => v !== null && v !== undefined,
	);
	if (realPoints.length < 2) return null;
	return <EChart option={option} height={height} className="w-full" />;
};
