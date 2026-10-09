import { Eye } from "lucide-react";

/**
 * Chart or table — the same data, shown two ways.
 *
 * One button that flips, rather than a segmented pair: the choice is binary and
 * the card already shows which view you are in, so a second button only ever
 * restates the obvious. Deliberately NOT a `ViewToggle` — that control chooses
 * what the card is *about* (revenue vs units, by brand vs by city), and three
 * identical word-toggles in a header made a display preference look like
 * another data choice.
 *
 * Icon-only, so it carries the label it is switching TO for screen readers and
 * as a tooltip — "Show as table" is what the click does, which is more useful
 * than naming the state you are already looking at.
 */
export const ChartTableSwitch = ({ value, onChange }) => {
	const next = value === "chart" ? "table" : "chart";
	const label = next === "table" ? "Show as table" : "Show as chart";
	return (
		<button
			type="button"
			onClick={() => onChange(next)}
			aria-label={label}
			title={label}
			className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-content-muted transition-colors hover:border-content-subtle hover:text-content"
		>
			<Eye size={14} aria-hidden strokeWidth={2} />
			{next === "table" ? "Table" : "Chart"}
		</button>
	);
};
