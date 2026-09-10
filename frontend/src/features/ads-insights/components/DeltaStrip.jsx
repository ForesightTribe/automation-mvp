import { formatCurrency } from "../../../lib/format";

const pct = (now, before) => {
	if (!before) return null;
	return ((now - before) / Math.abs(before)) * 100;
};

/**
 * How this window compares with the one before it.
 *
 * Direction is stated in words and an arrow as well as colour, because colour alone is not
 * readable to everyone. And direction is not judgement: spending more is not "bad" and
 * earning more is not automatically "good", so only RoAS, which has an unambiguous better
 * direction, is tinted. The rest are neutral ink.
 */
const Item = ({ label, now, before, format, judge = false, unit = "" }) => {
	const change = pct(now, before);
	const up = change != null && change > 0;
	const tone =
		!judge || change == null
			? "text-content-muted"
			: up
				? "text-success"
				: "text-danger";
	return (
		<div className="min-w-0">
			<p className="text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
				{label}
			</p>
			<p className="mt-0.5 font-display text-base font-semibold text-content tabular-nums">
				{format(now)}
				{unit}
			</p>
			<p className={`text-xs tabular-nums ${tone}`}>
				{change == null
					? "no prior data"
					: `${up ? "▲" : "▼"} ${Math.abs(change).toFixed(1)}% vs previous ${format(before)}${unit}`}
			</p>
		</div>
	);
};

export const DeltaStrip = ({ now, before }) => (
	<div className="grid grid-cols-2 gap-4 rounded-lg border border-border bg-surface p-3 sm:grid-cols-3">
		<Item
			label="Ad spend"
			now={now.spend}
			before={before.spend}
			format={formatCurrency}
		/>
		<Item
			label="Ad revenue"
			now={now.revenue}
			before={before.revenue}
			format={formatCurrency}
		/>
		<Item
			label="RoAS"
			now={now.roas}
			before={before.roas}
			format={(v) => (v == null ? "—" : v.toFixed(2))}
			unit="x"
			judge
		/>
	</div>
);
