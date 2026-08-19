/**
 * Compact segmented control. Domain-agnostic — used for the Chart/Table switch on
 * cards and for the Revenue/Units metric switch. `options` is [{ value, label }];
 * the selected value is highlighted. Controlled: pass `value` + `onChange`.
 */
export const ViewToggle = ({ options, value, onChange }) => (
	<div className="inline-flex rounded-md border border-border bg-card p-0.5">
		{options.map((o) => (
			<button
				key={o.value}
				type="button"
				onClick={() => onChange(o.value)}
				aria-pressed={value === o.value}
				className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
					value === o.value
						? "bg-brand text-on-brand"
						: "text-content-muted hover:text-content"
				}`}
			>
				{o.label}
			</button>
		))}
	</div>
);
