/**
 * Shared timing editor for budget + bid rules. Emits a canonical timing object
 * ({ type, days, date, start_time, end_time, start_date, end_date }); the bid form
 * remaps end_* → stop_* on submit. Two shapes:
 *   - Recurring: a daily window (start/end time, may cross midnight) on chosen
 *     weekdays, optionally bounded by a date range.
 *   - One-time: a single-date window (start/end time).
 */
const DAYS = [
	["monday", "Mon"],
	["tuesday", "Tue"],
	["wednesday", "Wed"],
	["thursday", "Thu"],
	["friday", "Fri"],
	["saturday", "Sat"],
	["sunday", "Sun"],
];

const FIELD =
	"rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-content focus:border-primary focus:outline-none";
const LABEL = "text-xs font-medium text-content-muted";

export const emptyTiming = () => ({
	type: "recurring",
	days: [],
	date: "",
	start_time: "",
	end_time: "",
	start_date: "",
	end_date: "",
});

const Segmented = ({ value, onChange }) => (
	<div className="inline-flex rounded-lg border border-border bg-surface p-0.5">
		{[
			["recurring", "Recurring"],
			["once", "One-time"],
		].map(([v, label]) => (
			<button
				key={v}
				type="button"
				onClick={() => onChange(v)}
				className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
					value === v ? "bg-primary text-on-primary" : "text-content-muted hover:text-content"
				}`}
			>
				{label}
			</button>
		))}
	</div>
);

export const TimingFields = ({ value, onChange }) => {
	const set = (patch) => onChange({ ...value, ...patch });
	const toggleDay = (d) =>
		set({
			days: value.days.includes(d)
				? value.days.filter((x) => x !== d)
				: [...value.days, d],
		});
	const overnight =
		value.start_time && value.end_time && value.end_time <= value.start_time;

	return (
		<div className="space-y-4">
			<div className="flex items-center justify-between gap-3">
				<span className={LABEL}>Repeat</span>
				<Segmented value={value.type} onChange={(t) => set({ type: t })} />
			</div>

			<div>
				<div className="grid max-w-sm grid-cols-2 gap-3">
					<label className="flex flex-col gap-1">
						<span className={LABEL}>From</span>
						<input
							type="time"
							value={value.start_time}
							onChange={(e) => set({ start_time: e.target.value })}
							className={FIELD}
						/>
					</label>
					<label className="flex flex-col gap-1">
						<span className={LABEL}>Until</span>
						<input
							type="time"
							value={value.end_time}
							onChange={(e) => set({ end_time: e.target.value })}
							className={FIELD}
						/>
					</label>
				</div>
				<p className="mt-1 text-xs text-content-subtle">
					{overnight
						? "“Until” is earlier than “from”, so this runs overnight into the next day."
						: "Leave blank to run all day."}
				</p>
			</div>

			{value.type === "once" ? (
				<label className="flex max-w-48 flex-col gap-1">
					<span className={LABEL}>On date</span>
					<input
						type="date"
						value={value.date}
						onChange={(e) => set({ date: e.target.value })}
						className={FIELD}
					/>
				</label>
			) : (
				<>
					<div>
						<span className={LABEL}>On days</span>
						<span className="ml-1.5 text-xs text-content-subtle">(none = every day)</span>
						<div className="mt-1.5 flex flex-wrap gap-1.5">
							{DAYS.map(([d, short]) => (
								<button
									key={d}
									type="button"
									onClick={() => toggleDay(d)}
									className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
										value.days.includes(d)
											? "bg-primary text-on-primary"
											: "border border-border bg-surface text-content-muted hover:bg-muted"
									}`}
								>
									{short}
								</button>
							))}
						</div>
					</div>

					<div>
						<span className={LABEL}>Active between</span>
						<span className="ml-1.5 text-xs text-content-subtle">(optional)</span>
						<div className="mt-1.5 flex items-center gap-2">
							<input
								type="date"
								value={value.start_date}
								onChange={(e) => set({ start_date: e.target.value })}
								className={`${FIELD} w-40`}
							/>
							<span className="text-content-subtle">→</span>
							<input
								type="date"
								value={value.end_date}
								onChange={(e) => set({ end_date: e.target.value })}
								className={`${FIELD} w-40`}
							/>
						</div>
					</div>
				</>
			)}
		</div>
	);
};

/**
 * Build the API payload from the timing state: drops empty strings, keeps only the
 * fields the chosen `type` uses, and remaps end_* → stop_* for bid rules (`stop`).
 */
export const timingPayload = (t, { stop = false } = {}) => {
	const v = (x) => (x === "" || x == null ? undefined : x);
	const endTime = stop ? "stop_time" : "end_time";
	const endDate = stop ? "stop_date" : "end_date";
	if (t.type === "once") {
		return {
			type: "once",
			date: v(t.date),
			start_time: v(t.start_time),
			[endTime]: v(t.end_time),
		};
	}
	return {
		type: "recurring",
		days: t.days,
		start_time: v(t.start_time),
		[endTime]: v(t.end_time),
		start_date: v(t.start_date),
		[endDate]: v(t.end_date),
	};
};

/** Pre-fill the timing editor from an existing rule (inverse of `timingPayload`). `stop`
 *  reads the bid-rule `stop_*` fields instead of budget's `end_*`. */
export const timingFromRule = (r, { stop = false } = {}) => ({
	type: r.type || "recurring",
	days: r.days || [],
	date: r.date || "",
	start_time: r.start_time || "",
	end_time: (stop ? r.stop_time : r.end_time) || "",
	start_date: r.start_date || "",
	end_date: (stop ? r.stop_date : r.end_date) || "",
});

/** Human summary of a rule's timing, for the list rows. */
export const describeTiming = ({
	type,
	days,
	date,
	start_time,
	end_time,
	start_date,
	end_date,
	stop_time,
	stop_date,
}) => {
	const from = start_time || "00:00";
	const to = end_time || stop_time || "23:59";
	const window = `${from}–${to}`;
	if (type === "once") return `once ${date || "?"} · ${window}`;
	const when = days && days.length ? days.map((d) => d.slice(0, 3)).join(", ") : "every day";
	const sd = start_date;
	const ed = end_date || stop_date;
	const range = sd || ed ? ` · ${sd || "…"} → ${ed || "…"}` : "";
	return `${when} · ${window}${range}`;
};
