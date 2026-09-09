import { formatDate } from "../../../lib/format";

/**
 * Structured, read-only timing display for the Scheduled rows.
 *
 * The list used to render timing as one long sentence (`describeTiming`), which is fine
 * in prose but is the first thing to get truncated in a column. These render the same
 * facts as fixed-width pieces instead — a weekday strip that is the same width whether a
 * rule runs on one day or seven, and a time range in tabular numerals — so a row stays
 * legible on a laptop without hiding anything.
 *
 * Budget rules end with `end_*`, bid rules with `stop_*`; `timingOf` flattens that
 * difference so every component here takes one shape.
 */
const DAYS = [
	["monday", "M", "Mon"],
	["tuesday", "T", "Tue"],
	["wednesday", "W", "Wed"],
	["thursday", "T", "Thu"],
	["friday", "F", "Fri"],
	["saturday", "S", "Sat"],
	["sunday", "S", "Sun"],
];

export const timingOf = (rule) => ({
	type: rule.type || "recurring",
	days: rule.days ?? [],
	date: rule.date || null,
	start_time: rule.start_time || null,
	end_time: rule.end_time || rule.stop_time || null,
	start_date: rule.start_date || null,
	end_date: rule.end_date || rule.stop_date || null,
});

/** M T W T F S S with the rule's days filled. No days selected means every day, which is
 *  what the editor promises ("none = every day"), so all seven read as active. */
export const WeekPills = ({ days = [] }) => {
	const everyDay = days.length === 0;
	const label = everyDay
		? "Every day"
		: DAYS.filter(([d]) => days.includes(d))
				.map(([, , long]) => long)
				.join(", ");

	return (
		<span className="inline-flex gap-0.5" title={label} aria-label={label}>
			{DAYS.map(([day, short], i) => {
				const on = everyDay || days.includes(day);
				return (
					<span
						key={`${day}-${i}`}
						className={`inline-flex h-4 w-4 items-center justify-center rounded-[3px] text-[9px] leading-none font-semibold ${
							on
								? "bg-primary text-on-primary"
								: "bg-muted text-content-subtle"
						}`}
					>
						{short}
					</span>
				);
			})}
		</span>
	);
};

/** 09:00 – 13:00, or "All day" when the window is unbounded. A window whose end is at or
 *  before its start crosses midnight — the engine treats it as overnight, so say so. */
export const TimeRange = ({ start, end }) => {
	if (!start && !end)
		return <span className="text-content-muted">All day</span>;
	const from = start || "00:00";
	const to = end || "23:59";
	const overnight = Boolean(start && end && end <= start);
	return (
		<span className="inline-flex items-center gap-1.5 whitespace-nowrap">
			<span className="tabular-nums">
				{from} – {to}
			</span>
			{overnight && (
				<span
					title="Ends the next day."
					className="rounded bg-muted px-1 py-px text-[10px] font-medium text-content-muted"
				>
					+1d
				</span>
			)}
		</span>
	);
};

/** The date bounds of a recurring rule — the part that silently decides whether an
 *  automation is still alive, so it is never abbreviated away. */
export const DateWindow = ({ from, to }) => {
	if (!from && !to)
		return <span className="text-content-subtle">No date limit</span>;
	if (from && to)
		return (
			<span className="whitespace-nowrap">
				{formatDate(from)} → {formatDate(to)}
			</span>
		);
	return (
		<span className="whitespace-nowrap">
			{from ? `From ${formatDate(from)}` : `Until ${formatDate(to)}`}
		</span>
	);
};

/** Weekday strip (or the one-off date) above the time range — the compact "when" cell
 *  used inside a collapsed row, where there is no space for the date bounds too. */
export const WhenSummary = ({ rule }) => {
	const t = timingOf(rule);
	return (
		<span className="block space-y-1">
			{t.type === "once" ? (
				<span className="block text-xs whitespace-nowrap text-content">
					Once · {t.date ? formatDate(t.date) : "no date"}
				</span>
			) : (
				<WeekPills days={t.days} />
			)}
			<span className="block text-xs text-content">
				<TimeRange start={t.start_time} end={t.end_time} />
			</span>
		</span>
	);
};
