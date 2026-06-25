/**
 * Period-over-period growth pill: "+24%" green, "−8%" red, with a direction
 * arrow. `delta` is a fraction (0.24 = +24%) or null when growth can't be
 * computed (no prior value) — in which case nothing renders. For metrics where
 * lower is better (e.g. rank), pass `goodWhenDown` so the colors invert.
 */
export const DeltaBadge = ({ delta, goodWhenDown = false }) => {
	if (delta === null || delta === undefined) return null;

	const flat = delta === 0;
	const up = delta > 0;
	const good = goodWhenDown ? delta < 0 : delta > 0;

	const tone = flat
		? "text-content-subtle"
		: good
			? "text-success"
			: "text-danger";
	const arrow = flat ? "" : up ? "▲" : "▼";
	const pct = `${delta > 0 ? "+" : ""}${(delta * 100).toFixed(0)}%`;

	return (
		<span
			className={`inline-flex items-center gap-0.5 text-xs font-medium ${tone}`}
		>
			{arrow && <span aria-hidden>{arrow}</span>}
			{pct}
		</span>
	);
};
