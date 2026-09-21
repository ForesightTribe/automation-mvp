import { useMemo } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { Card } from "../../../components/ui/Card";
import { DeltaBadge } from "../../../components/ui/DeltaBadge";
import { EChart } from "../../../components/charts/EChart";
import { comparisonBars } from "../poCharts";

/**
 * One headline figure, with its comparison against the window before folded away
 * underneath: two bars, previous and this period, and the change in real units.
 */
export const PoKpiTile = ({
	label,
	value,
	hint,
	delta,
	goodWhenDown = false,
	prev,
	// Set on a figure with no cross-window comparison: no change badge, no chart.
	note,
	color = "#0284c7",
	format,
	open,
	onToggle,
}) => {
	const chart = useMemo(
		() =>
			open && !note
				? comparisonBars(value?.raw, prev, { color, format })
				: null,
		// eslint-disable-next-line react-hooks/exhaustive-deps
		[open, prev, value?.raw],
	);

	return (
		<Card>
			<div className="flex items-start justify-between gap-2">
				<p className="text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
					{label}
				</p>
				{!note && (
					<DeltaBadge delta={delta} goodWhenDown={goodWhenDown} />
				)}
			</div>

			<p className="mt-2 font-display text-2xl font-semibold tracking-tight text-content tabular-nums">
				{value?.display}
			</p>
			{hint && <p className="mt-1 text-xs text-content-subtle">{hint}</p>}

			{!note && (
				<button
					type="button"
					aria-expanded={open}
					onClick={onToggle}
					className="mt-3 flex items-center gap-1 text-xs font-medium text-content-muted transition-colors hover:text-brand"
				>
					{open ? "Hide comparison" : "Show comparison"}
					{open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
				</button>
			)}

			{open && !note && (
				<div className="mt-2 border-t border-border pt-2">
					<EChart option={chart} height={130} />
					{!note && (
						<dl className="mt-2 space-y-1 text-xs">
							<div className="flex justify-between gap-3">
								<dt className="text-content-muted">
									Previous period
								</dt>
								<dd className="text-content tabular-nums">
									{prev === null || prev === undefined
										? "no prior data"
										: (format ?? String)(prev)}
								</dd>
							</div>
							{prev != null && value?.raw != null && (
								<div className="flex justify-between gap-3">
									<dt className="text-content-muted">
										Change
									</dt>
									<dd className="text-content tabular-nums">
										{value.raw - prev >= 0 ? "+" : "−"}
										{(format ?? String)(
											Math.abs(value.raw - prev),
										)}
									</dd>
								</div>
							)}
						</dl>
					)}
				</div>
			)}
		</Card>
	);
};
