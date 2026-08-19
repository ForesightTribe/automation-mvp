import { formatDate } from "../../../lib/format";

/**
 * Page-local week selector. Scorecard data is weekly snapshots, so this drives
 * the whole page in place of the global date-range picker (which is ignored
 * here). `weeks` are ISO `from_date_ist` strings, newest first; `value` is the
 * selected week. Each option reads as the week's start date.
 */
export const WeekPicker = ({ weeks = [], value, onChange }) => (
	<label className="flex items-center gap-2 text-sm text-content-muted">
		<span className="whitespace-nowrap">Week of</span>
		<select
			value={value ?? ""}
			onChange={(e) => onChange(e.target.value)}
			disabled={weeks.length === 0}
			className="rounded-md border border-border bg-card px-2.5 py-1 text-sm text-content focus:outline-none focus:ring-2 focus:ring-brand/30 disabled:opacity-50"
		>
			{weeks.length === 0 && <option value="">No weeks</option>}
			{weeks.map((w) => (
				<option key={w} value={w}>
					{formatDate(w)}
				</option>
			))}
		</select>
	</label>
);
