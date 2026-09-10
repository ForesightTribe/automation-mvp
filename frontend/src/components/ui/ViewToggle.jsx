/**
 * Compact segmented control. Domain-agnostic — used for the Chart/Table switch on
 * cards and for the Revenue/Units metric switch. `options` is [{ value, label }];
 * the selected value is highlighted. Controlled: pass `value` + `onChange`.
 */
/**
 * `size="lg"` is for the ONE control that chooses what the page is showing.
 * Everything else stays small: when every toggle is the same weight, a header
 * with three of them reads as a settings bar rather than a page.
 */
const SIZES = {
	sm: "px-2 py-0.5 text-xs",
	lg: "px-3.5 py-1.5 text-sm",
};

export const ViewToggle = ({ options, value, onChange, size = "sm" }) => (
	<div className="inline-flex rounded-lg border border-border bg-card p-0.5">
		{options.map((o) => (
			<button
				key={o.value}
				type="button"
				onClick={() => onChange(o.value)}
				aria-pressed={value === o.value}
				className={`rounded-md font-medium transition-colors ${SIZES[size]} ${
					value === o.value
						? "bg-brand text-on-brand shadow-sm"
						: "text-content-muted hover:bg-muted hover:text-content"
				}`}
			>
				{o.label}
			</button>
		))}
	</div>
);
