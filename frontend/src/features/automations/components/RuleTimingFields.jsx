import { DayPicker } from "./DayPicker";
import { TimePicker } from "./TimePicker";

/**
 * Shared timing block for both rule types (BudgetRuleIn/BidRuleIn have the
 * same shape: type "recurring"|"once", days[], start/end time, or a single
 * date for a one-off). Works on a generic { type, days, start_time, end_time,
 * start_date, end_date, date } value; the caller renames end_time -> stop_time
 * when building a bid-rule payload (the two schemas use different field names
 * for the same concept).
 */
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
		<div className="flex flex-col gap-3">
			<div className="flex gap-4">
				<label className="flex items-center gap-1.5 text-sm text-content">
					<input
						type="radio"
						checked={value.type === "recurring"}
						onChange={() => setType("recurring")}
					/>
					Recurring
				</label>
				<label className="flex items-center gap-1.5 text-sm text-content">
					<input
						type="radio"
						checked={value.type === "once"}
						onChange={() => setType("once")}
					/>
					One-time
				</label>
			</div>

			{value.type === "once" ? (
				<div>
					<label className="mb-1 block text-xs text-content-muted">
						Date
					</label>
					<input
						type="date"
						value={value.date ?? ""}
						onChange={(e) => set({ date: e.target.value })}
						className="rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-content"
					/>
				</div>
			) : (
				<div>
					<label className="mb-1 block text-xs text-content-muted">
						On days
					</label>
					<DayPicker
						value={value.days ?? []}
						onChange={(days) => set({ days })}
					/>
				</div>
			)}

			<div className="flex flex-wrap items-end gap-3">
				<div>
					<label className="mb-1 block text-xs text-content-muted">
						Start time
					</label>
					<TimePicker
						aria-label="Start time"
						value={value.start_time ?? ""}
						onChange={(t) => set({ start_time: t })}
					/>
				</div>
				<div>
					<label className="mb-1 block text-xs text-content-muted">
						End time
					</label>
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
