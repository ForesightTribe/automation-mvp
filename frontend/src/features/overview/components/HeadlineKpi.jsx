/**
 * The page's lead number: label, the value at full size, and the comparisons
 * that make it readable, divided into cells beneath it.
 *
 * Every comparison is real. No "vs target" cell — this product has no revenue
 * target — and no year-on-year, since the data begins in June 2026. Each cell
 * names the day it compares against and carries that day's figure on hover.
 */
const Cell = ({ value, unit = "percent", label, hint }) => {
	const missing = value === null || value === undefined;
	const flat = !missing && Math.round(value * 10) === 0;
	const tone = missing
		? "text-content-subtle"
		: flat
			? "text-content-muted"
			: value > 0
				? "text-success"
				: "text-danger";
	const shown = missing
		? "—"
		: unit === "pp"
			? `${value > 0 ? "+" : "−"}${Math.abs(value).toFixed(1)}pp`
			: `${value > 0 ? "+" : "−"}${Math.abs(value).toFixed(0)}%`;

	return (
		<div
			title={hint}
			className={`flex flex-col gap-0.5 pr-5 last:pr-0 ${hint ? "cursor-help" : ""}`}
		>
			<span
				className={`font-display text-lg font-bold tabular-nums ${tone}`}
			>
				{shown}
			</span>
			<span className="text-[11px] leading-tight whitespace-nowrap text-content-muted">
				{label}
			</span>
		</div>
	);
};

export const HeadlineKpi = ({
	label,
	value,
	comparisons = [],
	hint,
	valueTitle,
}) => (
	<div className="flex flex-col gap-2">
		<p className="flex items-center gap-1 text-[11px] font-semibold tracking-[0.1em] text-content-subtle uppercase">
			{label}
			{hint}
		</p>
		{/* The full figure, so it steps down a size to stay on one line. */}
		<p
			title={valueTitle}
			className="font-display text-3xl font-bold text-content tabular-nums xl:text-4xl"
		>
			{value}
		</p>
		{/* Directly under the number, with no rule between: these qualify the
		    figure above rather than forming a section of their own. */}
		<div className="flex flex-wrap gap-y-3">
			{comparisons.map((c) => (
				<Cell key={c.label} {...c} />
			))}
		</div>
	</div>
);
