import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useHistory } from "../hooks";
import { formatCurrency } from "../../../lib/format";
import { outcomeOf } from "../../../lib/runLog";

const DAY_INDEX = {
	sunday: 0,
	monday: 1,
	tuesday: 2,
	wednesday: 3,
	thursday: 4,
	friday: 5,
	saturday: 6,
};

const hhmm = (t) => {
	const [h, m] = String(t).split(":").map(Number);
	return { h: h || 0, m: m || 0 };
};

const clock = (t) => {
	const { h, m } = hhmm(t);
	const suffix = h < 12 ? "am" : "pm";
	return `${h % 12 === 0 ? 12 : h % 12}:${String(m).padStart(2, "0")}${suffix}`;
};

const WHEN = new Intl.DateTimeFormat("en-IN", {
	weekday: "short",
	hour: "numeric",
	minute: "2-digit",
	hour12: true,
});

/**
 * The soonest moment any rule opens a window, from now.
 *
 * Worth computing rather than showing "next run: —": a schedule's whole point is that it
 * acts while nobody is watching, and "Friday 7:30pm" is the one fact that says it is armed.
 * An empty `days` list is treated as daily HERE only, because this is computing when the
 * engine will next act and the engine does read empty as daily. The wording elsewhere does
 * not call it "Every day": see describeWindow in automation.js.
 */
const nextWindow = (schedules, now = new Date()) => {
	let best = null;
	for (const s of schedules ?? []) {
		for (const r of s.rules ?? []) {
			if (!r.start_time) continue;
			const days = (r.days ?? []).length
				? r.days
				: Object.keys(DAY_INDEX);
			for (const d of days) {
				const target = DAY_INDEX[String(d).toLowerCase()];
				if (target == null) continue;
				const { h, m } = hhmm(r.start_time);
				const at = new Date(now);
				at.setSeconds(0, 0);
				at.setHours(h, m);
				let delta = (target - now.getDay() + 7) % 7;
				if (delta === 0 && at <= now) delta = 7;
				at.setDate(at.getDate() + delta);
				if (!best || at < best.at) {
					best = { at, schedule: s, rule: r };
				}
			}
		}
	}
	return best;
};

const Row = ({ children }) => (
	<li className="text-sm text-content">{children}</li>
);

const Section = ({ title, children }) => (
	<div>
		<p className="mb-1.5 text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
			{title}
		</p>
		{children}
	</div>
);

/**
 * Current status — one line by default, the detail behind a click.
 *
 * It replaces a strip of headline tiles that restated the table. Everything here is
 * something the table does NOT show: whether anything is inside a window right now, when
 * the next one opens, and what the engine last actually did to the account. Each section
 * says so in a sentence when it is empty rather than rendering an empty box.
 */
export const StatusSummary = ({ schedules = [], bidRules = [] }) => {
	const [at, setAt] = useState(null); // viewport coords, or null when closed
	const wrap = useRef(null);
	const open = at != null;

	// Same reason as the schedule popover: this hangs off a header that lives inside the
	// page's scrolling area, so an absolutely-positioned panel is clipped by it. Fixed
	// coordinates come from the trigger's own rect and are right-aligned to it.
	const toggle = () => {
		if (open) return setAt(null);
		const r = wrap.current?.getBoundingClientRect();
		if (!r) return;
		setAt({ right: window.innerWidth - r.right, top: r.bottom + 6 });
	};
	const { data: history } = useHistory(1);

	// A popover that only closes by re-clicking its own trigger traps the reader: it covers
	// the page it is describing. Clicking anywhere else, or Escape, dismisses it.
	useEffect(() => {
		if (!open) return;
		const onDown = (e) => {
			if (wrap.current && !wrap.current.contains(e.target)) setAt(null);
		};
		const onKey = (e) => e.key === "Escape" && setAt(null);
		// Anchored to a rect measured once, so it must not linger while the page scrolls.
		const onScroll = () => setAt(null);
		document.addEventListener("mousedown", onDown);
		document.addEventListener("keydown", onKey);
		window.addEventListener("scroll", onScroll, true);
		return () => {
			document.removeEventListener("mousedown", onDown);
			document.removeEventListener("keydown", onKey);
			window.removeEventListener("scroll", onScroll, true);
		};
	}, [open]);

	const all = [...schedules, ...bidRules];
	const running = all.filter((a) => a.status === "running");
	const paused = all.filter(
		(a) => a.status === "paused" || a.status === "stopped",
	);
	const next = useMemo(() => nextWindow(schedules), [schedules]);
	const recent = (history?.items ?? []).slice(0, 3);
	const lastRun = recent[0];

	const summary =
		all.length === 0
			? "No automations yet. Create one to schedule budgets or defend a keyword's rank."
			: // How many there are, and how many are doing something. The next window, what
				// is running and what last happened are all in the panel: a label that has to
				// be read word by word is not a status, and this one sits above the table it
				// describes.
				[
					`${all.length} automation${all.length === 1 ? "" : "s"}`,
					running.length
						? `${running.length} acting now`
						: "none acting now",
				].join(" · ");

	return (
		// Sized to its content and anchored right: this is a status readout, not a banner, so
		// it should not claim a full-width band. The detail opens as a popover over the page
		// rather than pushing everything below it down.
		<div ref={wrap} className="relative ml-auto w-fit max-w-full">
			<button
				type="button"
				onClick={toggle}
				aria-expanded={open}
				className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-left transition-colors ${
					open
						? "border-content-subtle bg-muted/50"
						: "border-border bg-card hover:bg-muted/50"
				}`}
			>
				<span
					className={`h-2 w-2 shrink-0 rounded-full ${
						running.length
							? "bg-success"
							: all.length
								? "bg-info"
								: "bg-content-subtle"
					}`}
				/>
				<span className="truncate text-sm text-content">{summary}</span>
				{all.length > 0 && (
					<span className="ml-2 flex shrink-0 items-center gap-1 text-xs text-content-subtle">
						{open ? "Hide" : "Details"}
						{open ? (
							<ChevronUp size={14} />
						) : (
							<ChevronDown size={14} />
						)}
					</span>
				)}
			</button>

			{open && all.length > 0 && (
				<div
					style={{ right: at.right, top: at.top }}
					className="fixed z-[70] grid w-[46rem] max-w-[90vw] gap-5 rounded-lg border border-border bg-card p-4 shadow-xl sm:grid-cols-3"
				>
					<Section title="Acting now">
						{running.length ? (
							<ul className="space-y-1">
								{running.map((a) => (
									<Row key={`${a.id}-${a.keyword ?? "c"}`}>
										{a.keyword ?? a.name ?? a.campaign_name}
									</Row>
								))}
							</ul>
						) : (
							<p className="text-sm text-content-muted">
								Nothing is inside a window right now.
								{paused.length > 0 &&
									` ${paused.length} paused or stopped.`}
							</p>
						)}
					</Section>

					<Section title="Next window">
						{next ? (
							<p className="text-sm text-content">
								<span className="font-medium">
									{WHEN.format(next.at)}
								</span>
								{" · "}
								{next.schedule.campaign_name}
								{next.rule.budget != null &&
									` → ${formatCurrency(next.rule.budget)}`}
								{next.rule.end_time && (
									<span className="text-content-muted">
										{" "}
										until {clock(next.rule.end_time)}
									</span>
								)}
							</p>
						) : (
							<p className="text-sm text-content-muted">
								No scheduled window. These automations only act
								when one is set.
							</p>
						)}
					</Section>

					<Section title="Last acted">
						{lastRun ? (
							<ul className="space-y-1">
								{recent.map((r) => (
									<li
										key={r.id}
										className="text-sm"
										title={r.reason ?? undefined}
									>
										<span
											className={
												r.success
													? "text-content"
													: "text-danger"
											}
										>
											{outcomeOf(r)}
											{r.new_value != null &&
												` ${formatCurrency(r.new_value)}`}
										</span>
										<span className="text-content-muted">
											{" · "}
											{r.keyword ?? r.campaign_name}
										</span>
										{/* A dry run changed nothing on the account, and saying so is the
										    difference between "it worked" and "it would have". */}
										{r.dry_run && (
											<span className="ml-1 text-xs text-content-subtle">
												(dry run)
											</span>
										)}
									</li>
								))}
							</ul>
						) : (
							<p className="text-sm text-content-muted">
								Nothing has run yet.
							</p>
						)}
					</Section>
				</div>
			)}
		</div>
	);
};
