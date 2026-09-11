// ⚠️ The VALUES must be full lowercase day names. The engine decides whether a rule fires
// today with `eff.strftime("%A").lower() in days` (campaign_manager/bid.py, budget.py), so
// "mon" can never match "monday" — a rule saved with short codes stores and displays fine
// and then silently never runs. v2 sends these same full names; the DB's existing rules
// hold ["friday","saturday","sunday"].
const DAYS = [
	{ value: "monday", label: "Mon" },
	{ value: "tuesday", label: "Tue" },
	{ value: "wednesday", label: "Wed" },
	{ value: "thursday", label: "Thu" },
	{ value: "friday", label: "Fri" },
	{ value: "saturday", label: "Sat" },
	{ value: "sunday", label: "Sun" },
];

const ALL = DAYS.map((d) => d.value);

/** Multi-select day-of-week toggle row, shared by the budget and bid rule
 * builders (both take a `days: string[]` field on the same backend shape).
 *
 * Seven chips and an All chip, styled identically to the campaign path's trigger row
 * (pills, brand fill when chosen) so the two halves of one wizard look like one product.
 *
 * ⚠️ All sends the seven days EXPLICITLY. The engine happens to read an empty list as daily
 * too, but nothing chosen and every day chosen are different statements by a reader, and a
 * screen that treats them as the same one cannot show which was meant. Choosing nothing is
 * refused on save rather than silently promoted to daily. */
export const DayPicker = ({ value = [], onChange }) => {
	const toggle = (d) =>
		onChange(
			value.includes(d) ? value.filter((v) => v !== d) : [...value, d],
		);
	const allOn = ALL.every((d) => value.includes(d));
	return (
		<div className="flex flex-wrap items-center gap-1.5">
			{DAYS.map((d) => (
				<button
					key={d.value}
					type="button"
					onClick={() => toggle(d.value)}
					aria-pressed={value.includes(d.value)}
					className={`rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
						value.includes(d.value)
							? "border-brand bg-brand text-on-brand"
							: "border-border bg-card text-content-muted hover:text-content"
					}`}
				>
					{d.label}
				</button>
			))}
			<button
				type="button"
				aria-pressed={allOn}
				onClick={() => onChange(allOn ? [] : ALL)}
				className={`ml-1 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
					allOn
						? "border-content bg-content text-card"
						: "border-dashed border-content-subtle text-content-muted hover:text-content"
				}`}
			>
				All
			</button>
		</div>
	);
};
