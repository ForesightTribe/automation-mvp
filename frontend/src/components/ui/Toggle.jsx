/**
 * An on/off switch. Presentational only — it reports the flip and nothing else.
 *
 * Deliberately without a confirmation of its own. The switches in this product all guard
 * live writes, but what needs saying before the write differs by surface, so the page
 * owns the dialog and this owns the affordance.
 *
 * `disabled` is for a state that is genuinely unknown or unreachable, never for "probably
 * fine": a switch that flips the wrong way stops something that is spending.
 */
export const Toggle = ({
	on,
	onChange,
	disabled = false,
	title,
	"aria-label": ariaLabel,
}) => (
	<button
		type="button"
		role="switch"
		aria-checked={on}
		aria-label={ariaLabel}
		disabled={disabled}
		title={title}
		onClick={(e) => {
			// The switch often sits inside a row that is itself a click target.
			e.stopPropagation();
			onChange?.(!on);
		}}
		className={`relative h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
			on ? "bg-success" : "bg-border"
		}`}
	>
		<span
			className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-card shadow-sm transition-transform ${
				on ? "translate-x-4" : ""
			}`}
		/>
	</button>
);
