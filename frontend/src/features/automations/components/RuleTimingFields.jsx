import { ViewToggle } from "../../../components/ui/ViewToggle";
import { DatePicker } from "../../../components/ui/DatePicker";
import { DayPicker } from "./DayPicker";
import { TimePicker } from "./TimePicker";

/**
 * Shared timing block for both rule types (BudgetRuleIn/BidRuleIn have the
 * same shape: type "recurring"|"once", days[], start/end time, or a single
 * date for a one-off). Works on a generic { type, days, start_time, end_time,
 * start_date, end_date, date } value; the caller renames end_time -> stop_time
 * when building a bid-rule payload (the two schemas use different field names
 * for the same concept).
 *
 * The two modes answer WHICH DAYS differently, and each needs its own answer in
 * full: a one-off names the single date it runs on, while a recurring rule names
 * the span it runs across and then the weekdays inside it. Without that span a
 * recurring rule has a start but no end and simply runs forever.
 *
 * Span first, weekdays second, because that is the order the sentence reads in:
 * between these dates, on these days, at these times. Asking which weekdays before
 * saying which weeks they fall in puts the qualifier before the thing it qualifies.
 */
const LABEL = "mb-1 block text-xs text-content-muted";

/** Today in the local calendar. Never `toISOString()`, which is UTC and lands a day
 *  early for an IST evening. */
const todayIso = () => {
	const d = new Date();
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export const RuleTimingFields = ({ value, onChange }) => {
	const set = (patch) => onChange({ ...value, ...patch });

	/**
	 * ⚠️ Switching mode CLEARS whatever the other mode owned. A one-off is described by its
	 * date and a recurring window by its days, and leaving the unused field populated means
	 * the rule carries two contradictory answers: a date to run on and a weekday to repeat
	 * on. Whichever the reader is shown, the other one is still in the payload.
	 */
	const setType = (type) =>
		onChange({
			...value,
			type,
			...(type === "once" ? { days: [] } : { date: null }),
		});

	return (
		// gap-5, not gap-3: three separate decisions live here (how often, which days or
		// which date, at what times) and at the tighter spacing the rows read as one
		// crowded block.
		<div className="flex flex-col gap-5">
			{/* A segmented control, in the same shape as the other fields on this card.
			    No label above it: the two options say what the choice is on their own. */}
			<div>
				<ViewToggle
					value={value.type ?? "recurring"}
					onChange={setType}
					options={[
						{ value: "recurring", label: "Recurring" },
						{ value: "once", label: "One-time" },
					]}
				/>
			</div>

			{value.type === "once" ? (
				<div>
					<span className={LABEL}>Date</span>
					<DatePicker
						className="w-52"
						ariaLabel="Date"
						value={value.date ?? ""}
						onChange={(d) => set({ date: d })}
					/>
				</div>
			) : (
				<>
					{/* The span the weekdays repeat inside. "No end date" is a checkbox
					    rather than an empty field, because a blank date is ambiguous —
					    it reads as "not filled in yet" just as easily as "runs forever"
					    — and this is the difference between an automation that stops and
					    one that does not. */}
					<div className="flex flex-wrap items-start gap-5">
						<div>
							<span className={LABEL}>Start date</span>
							<DatePicker
								className="w-52"
								ariaLabel="Start date"
								value={value.start_date ?? ""}
								onChange={(d) => set({ start_date: d })}
							/>
						</div>
						<div>
							<span className={LABEL}>End date</span>
							<DatePicker
								className="w-52"
								ariaLabel="End date"
								disabled={!value.end_date}
								min={value.start_date || undefined}
								value={value.end_date ?? ""}
								onChange={(d) => set({ end_date: d })}
							/>
						</div>
						<label className="mt-6 flex cursor-pointer items-center gap-2 text-sm text-content">
							<input
								type="checkbox"
								className="accent-brand"
								checked={!value.end_date}
								onChange={(e) =>
									set({
										end_date: e.target.checked
											? ""
											: todayIso(),
									})
								}
							/>
							No end date
						</label>
					</div>

					<div>
						<span className={LABEL}>On days</span>
						<DayPicker
							value={value.days ?? []}
							onChange={(days) => set({ days })}
						/>
					</div>
				</>
			)}

			<div className="flex flex-wrap items-end gap-3">
				<div>
					<span className={LABEL}>Start time</span>
					<TimePicker
						aria-label="Start time"
						value={value.start_time ?? ""}
						onChange={(t) => set({ start_time: t })}
					/>
				</div>
				<div>
					<span className={LABEL}>End time</span>
					<TimePicker
						aria-label="End time"
						value={value.end_time ?? ""}
						onChange={(t) => set({ end_time: t })}
					/>
				</div>
				<p className="pb-2 text-xs text-content-subtle">
					Leave blank to run all day.
				</p>
			</div>
		</div>
	);
};
