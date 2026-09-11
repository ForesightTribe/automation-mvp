import { useDateRange } from "../context/DateRangeContext";
import { CUSTOM_RANGE_KEY } from "../lib/constants";
import { DatePicker } from "../components/ui/DatePicker";

/**
 * Global date-window selector for the app shell: preset chips (7/30/90d) plus a
 * custom from/to range. Writes to DateRangeContext; every page whose query keys
 * on the range refetches when it changes.
 *
 * The two fields are our own DatePicker, not `<input type="date">`: the browser
 * draws that calendar itself, in its own type and colours, and it looked like a
 * different product every time it opened. Each field bounds the other, so the
 * range cannot be inverted from either end.
 *
 * ⚠️ Neither can be CLEARED. Every page derives its window from this range, so an
 * empty end is not "no end" here, it is an unusable date that each of them then
 * carries into its own query.
 */
export const DateRangePicker = () => {
	const { range, activePreset, presets, setPreset, setCustomRange } =
		useDateRange();

	const custom = activePreset === CUSTOM_RANGE_KEY;

	// The active preset is a brand-led control in the shell — hence `brand`
	// rather than `primary`. See --color-brand in index.css.
	const chipClass = (active) =>
		`rounded-md px-2.5 py-1 text-sm transition-colors ${
			active
				? "bg-brand font-semibold text-on-brand"
				: "font-normal text-content-muted hover:bg-muted"
		}`;

	return (
		<div
			role="group"
			aria-label="Date range"
			className="flex items-center gap-2"
		>
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
				<DatePicker
					value={range.from}
					max={range.to}
					onChange={(v) => setCustomRange(v, range.to)}
					ariaLabel="From date"
					allowClear={false}
					className={custom ? "border-primary" : ""}
				/>
				<span className="text-xs text-content-subtle">to</span>
				<DatePicker
					value={range.to}
					min={range.from}
					onChange={(v) => setCustomRange(range.from, v)}
					ariaLabel="To date"
					allowClear={false}
					className={custom ? "border-primary" : ""}
				/>
			</div>
		</div>
	);
};
