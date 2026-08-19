import { Card } from "./Card";
import { DeltaBadge } from "./DeltaBadge";
import { Sparkline } from "../charts/Sparkline";

/**
 * One headline KPI: label, a preformatted value, and its growth badge. The
 * caller formats `value` (currency, percent, etc.) since formatting is
 * metric-specific; this tile only handles layout. `delta` is a fraction or null;
 * `goodWhenDown` flips the badge colors for lower-is-better metrics like rank.
 * Pass `series` (array of daily values) to render a sparkline under the number.
 *
 * `hint` is the small line under the value — use it to carry the counts behind a
 * percentage ("24,410 of 25,474 listed"). A ratio with no denominator is not
 * interpretable, so any percentage tile should set it.
 */
export const MetricTile = ({
	label,
	value,
	hint,
	delta,
	goodWhenDown = false,
	series,
	sparkColor,
}) => {
	return (
		<Card>
			<p className="text-xs font-medium uppercase tracking-wide text-content-subtle">
				{label}
			</p>
			<div className="mt-2 flex items-baseline justify-between gap-2">
				<p className="font-display text-xl font-bold text-content xl:text-2xl">
					{value}
				</p>
				<DeltaBadge delta={delta} goodWhenDown={goodWhenDown} />
			</div>
			{hint && (
				<p className="mt-1 text-xs text-content-subtle">{hint}</p>
			)}
			{series && (
				<div className="mt-2">
					<Sparkline values={series} color={sparkColor} />
				</div>
			)}
		</Card>
	);
};
