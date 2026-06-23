import { useDateRange } from "../context/DateRangeContext";

/**
 * Global date-window selector for the app shell. Writes to DateRangeContext;
 * every page whose query keys on `days` refetches when it changes.
 */
export const DateRangePicker = () => {
	const { days, setDays, presets } = useDateRange();

	return (
		<select
			value={days}
			onChange={(e) => setDays(Number(e.target.value))}
			className="rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium text-content"
		>
			{presets.map((p) => (
				<option key={p.days} value={p.days}>
					{p.label}
				</option>
			))}
		</select>
	);
};
