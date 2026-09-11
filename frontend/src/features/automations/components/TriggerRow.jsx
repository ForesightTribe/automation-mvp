import { AlertTriangle, Trash2 } from "lucide-react";
import { TimePicker } from "./TimePicker";
import { Tooltip } from "./Tooltip";

/**
 * One time window: the days it runs on, when it is checked, and when it reverts.
 *
 * Lives in its own module because BOTH the action card and the "Add action" dialog render
 * it. An action's amount and its timing are one decision, so the dialog that creates an
 * action asks for both, and the card that shows it afterwards edits both. Two copies of this
 * editor would have drifted the moment either was touched.
 */
const DAYS = [
	["sunday", "Sun"],
	["monday", "Mon"],
	["tuesday", "Tue"],
	["wednesday", "Wed"],
	["thursday", "Thu"],
	["friday", "Fri"],
	["saturday", "Sat"],
];
const ALL_DAYS = DAYS.map(([v]) => v);

export const uid = () => Math.random().toString(36).slice(2, 9);

export const emptyTrigger = () => ({
	id: uid(),
	start_time: "",
	days: [],
	revert: false,
	end_time: "",
	// A window repeats unless told otherwise; "once" carries a `date` instead of days.
	type: "recurring",
	date: null,
});

/**
 * One trigger = one WINDOW = one budget rule. "Check at" is the rule's `start_time`,
 * the days are its `days`, and "Revert at" is its `end_time` — the moment the budget
 * goes back to the default. Leaving revert off means the window has no end time, which
 * the engine reads as running to the end of the day.
 */
export const TriggerRow = ({
	value,
	onChange,
	onRemove,
	removable,
	pauseAtEnd = false,
	onPauseAtEnd,
	windowCount = 1,
}) => {
	const allOn = ALL_DAYS.every((d) => value.days.includes(d));
	/**
	 * A window is one-off because it carries a DATE, not because a toggle says so.
	 *
	 * The day chips already say "this repeats", so a separate Weekly/Once control asked the
	 * same question twice. Picking any day is how a one-off becomes weekly; the date field
	 * only appears on a window that already has one, which is the case this screen has to
	 * edit without silently converting.
	 */
	const once = Boolean(value.date);
	// A dated window still lands on a weekday, so that chip is lit like any other selected
	// day. The row then reads the same whether the window repeats or not, and there is
	// nothing to explain in words underneath it.
	const dateDay = once
		? DAYS[new Date(`${value.date}T00:00:00`).getDay()]?.[0]
		: null;
	const isOn = (v) => value.days.includes(v) || v === dateDay;
	/**
	 * Choosing a day says "repeat", which a fixed date contradicts, so the date goes.
	 *
	 * ⚠️ The date's own weekday is folded into the list FIRST. On a dated window that chip is
	 * lit by the date rather than by `days`, so dropping the date without seeding it wiped a
	 * selection the reader could plainly see: picking a second day left only the second day.
	 */
	const toggleDay = (d) => {
		const base =
			value.days.length === 0 && dateDay ? [dateDay] : value.days;
		onChange({
			...value,
			date: null,
			type: "recurring",
			days: base.includes(d) ? base.filter((x) => x !== d) : [...base, d],
		});
	};

	return (
		// TWO deliberate lines, not one line that happens to wrap. With the AM/PM controls
		// added, a single flex-wrap row broke between "Revert at" and its own time field —
		// the label on one line, the control it labels on the next. Splitting it by intent
		// keeps every label next to the thing it names at any width.
		<div className="flex flex-col gap-2 rounded-md bg-muted/60 px-3 py-2.5">
			<div className="flex flex-wrap items-center gap-x-2 gap-y-2">
				<span className="shrink-0 text-sm text-content-muted">
					Check at
				</span>
				<TimePicker
					aria-label="Check at"
					value={value.start_time}
					onChange={(t) => onChange({ ...value, start_time: t })}
				/>
				<span className="text-sm text-content-muted">on</span>
				{/* Always all seven, always editable, and "All" belongs to the SAME group.
				    As a separate checkbox it wrapped onto its own line the moment the row ran
				    out of width, so the control that sets every day appeared to belong to
				    something else. Here it cannot separate from the days it acts on. */}
				<div className="flex flex-wrap items-center gap-1">
					{DAYS.map(([v, label]) => (
						<button
							key={v}
							type="button"
							onClick={() => toggleDay(v)}
							aria-pressed={isOn(v)}
							className={`rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
								isOn(v)
									? "border-brand bg-brand text-on-brand"
									: "border-border bg-card text-content-muted hover:text-content"
							}`}
						>
							{label}
						</button>
					))}
					<button
						type="button"
						aria-pressed={allOn}
						onClick={() =>
							onChange({
								...value,
								date: null,
								days: allOn ? [] : ALL_DAYS,
							})
						}
						className={`ml-1 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
							allOn
								? "border-content bg-content text-card"
								: "border-dashed border-content-subtle text-content-muted hover:text-content"
						}`}
					>
						All
					</button>
				</div>
			</div>

			<div className="flex flex-wrap items-center gap-2">
				<label className="flex cursor-pointer items-center gap-1.5 text-sm text-content">
					<input
						type="checkbox"
						checked={value.revert}
						onChange={(e) =>
							onChange({
								...value,
								revert: e.target.checked,
								end_time: e.target.checked
									? value.end_time
									: "",
							})
						}
					/>
					<span className="text-content-muted">Revert at</span>
				</label>
				<TimePicker
					aria-label="Revert at"
					value={value.end_time}
					disabled={!value.revert}
					onChange={(t) => onChange({ ...value, end_time: t })}
				/>
				{/* What happens at the end of the window, offered where the end time is set:
				    wanting the campaign to stop rather than revert is a thought that occurs
				    here, and making it cost a second action card sends the reader hunting.

				    ⚠️ Pausing is a property of the AUTOMATION, not of this window.
				    `stop_after_window` lives on the schedule and budget.py evaluates it
				    against every rule at once, so ticking it here pauses the campaign whenever
				    ANY window ends. With more than one window that is not what the row appears
				    to say, so the row says it. */}
				{value.revert ? (
					<label className="flex cursor-pointer items-center gap-1.5 text-xs text-content-muted">
						<input
							type="checkbox"
							checked={pauseAtEnd}
							onChange={(e) => onPauseAtEnd?.(e.target.checked)}
						/>
						and pause the campaign
					</label>
				) : (
					<span className="text-xs text-content-subtle">
						leave off to run to the end of the day
					</span>
				)}
				{value.revert && pauseAtEnd && windowCount > 1 && (
					<span className="flex items-center gap-1 text-xs text-warning">
						<AlertTriangle size={12} />
						applies whenever any of this automation&rsquo;s{" "}
						{windowCount} windows ends
					</span>
				)}

				{removable && (
					<Tooltip label="Remove this window" className="ml-auto">
						<button
							type="button"
							aria-label="Remove window"
							onClick={onRemove}
							className="rounded p-1 text-content-subtle transition-colors hover:bg-muted hover:text-danger"
						>
							<Trash2 size={13} />
						</button>
					</Tooltip>
				)}
			</div>
		</div>
	);
};
