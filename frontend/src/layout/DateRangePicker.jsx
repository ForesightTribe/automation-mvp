import { useDateRange } from "../context/DateRangeContext";
import { CUSTOM_RANGE_KEY } from "../lib/constants";

/**
 * Global date-window selector for the app shell: preset chips (7/30/90d) plus a
 * custom from/to range. Writes to DateRangeContext; every page whose query keys
 * on the range refetches when it changes.
 */
export const DateRangePicker = () => {
	const { range, activePreset, presets, setPreset, setCustomRange } =
		useDateRange();

	const onFrom = (e) => setCustomRange(e.target.value, range.to);
	const onTo = (e) => setCustomRange(range.from, e.target.value);

	// The active preset is a brand-led control in the shell — hence `brand`
	// rather than `primary`. See --color-brand in index.css.
	const chipClass = (active) =>
		`rounded-md px-2.5 py-1 text-sm transition-colors ${
			active
				? "bg-brand font-semibold text-on-brand"
				: "font-normal text-content-muted hover:bg-muted"
		}`;

	return (
		<div className="flex items-center gap-2">
			<div className="flex items-center gap-1 rounded-md border border-border bg-card p-0.5">
				{presets.map((p) => (
					<button
						key={p.key}
						type="button"
						onClick={() => setPreset(p.key)}
						className={chipClass(activePreset === p.key)}
					>
						{p.days}d
					</button>
				))}
			</div>

			<div className="flex items-center gap-1">
				<input
					type="date"
					value={range.from}
					max={range.to}
					onChange={onFrom}
					className={`rounded-md border bg-card px-2 py-1 text-sm font-normal text-content-muted ${
						activePreset === CUSTOM_RANGE_KEY
							? "border-primary"
							: "border-border"
					}`}
				/>
				<span className="text-xs text-content-subtle">to</span>
				<input
					type="date"
					value={range.to}
					min={range.from}
					onChange={onTo}
					className={`rounded-md border bg-card px-2 py-1 text-sm font-normal text-content-muted ${
						activePreset === CUSTOM_RANGE_KEY
							? "border-primary"
							: "border-border"
					}`}
				/>
			</div>
		</div>
	);
};
