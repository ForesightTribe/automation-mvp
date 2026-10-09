/**
 * What an automation IS, without rendering any of it.
 *
 * Three questions get asked about a rule all over this feature, and all three are pure
 * functions of what the API already returns: when does it run, how do you say that in
 * English, and is there anything wrong with it. They live together because they are one
 * subject and they share their vocabulary — days, clock times and windows are defined once
 * here and every answer is built from the same definitions.
 *
 * Nothing in this file touches React or the network. The components read it; it never reads
 * them.
 */

/* ────────────────────────────────────────────────────────────────────────────
 * 1. Reading a rule's timing
 *
 * Budget schedules keep their windows in `rules[]`; a bid rule IS its own window and uses
 * `stop_time` where a budget rule says `end_time`. Both shapes are normalised here so the
 * status pill, the drawer and the header summary all describe a schedule the same way.
 *
 * ⚠️ An empty `days` list is reported as "No days set", NOT as "Every day". The engine does
 * read empty as daily (budget.py / bid.py), but a rule where nobody chose a day and a rule
 * where somebody chose all seven are different statements, and a screen that prints the same
 * words for both cannot show which was meant. All seven, chosen explicitly, is what earns
 * the words "Every day".
 * ──────────────────────────────────────────────────────────────────────────── */

const DAY_INDEX = {
	sunday: 0,
	monday: 1,
	tuesday: 2,
	wednesday: 3,
	thursday: 4,
	friday: 5,
	saturday: 6,
};

/** The engine's own day names, in week order. Every "no days chosen" fallback uses this. */
const DAY_ORDER = Object.keys(DAY_INDEX);

const SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** "2026-09-07" reads as "7 Sept 2026" everywhere a window is described. */
const dayText = (iso) => {
	const d = new Date(`${iso}T00:00:00`);
	return Number.isNaN(d.getTime())
		? iso
		: d.toLocaleDateString("en-IN", {
				day: "numeric",
				month: "short",
				year: "numeric",
			});
};

/** "19:30" as its parts, or null when there is no usable time. */
const hhmm = (t) => {
	const [h, m] = String(t ?? "")
		.split(":")
		.map(Number);
	return Number.isNaN(h) ? null : { h, m: m || 0 };
};

/** The same clock time as minutes past midnight, for comparing two windows. */
const minutes = (t) => {
	const p = hhmm(t);
	return p ? p.h * 60 + p.m : null;
};

export const clockText = (t) => {
	const p = hhmm(t);
	if (!p) return null;
	return `${p.h % 12 === 0 ? 12 : p.h % 12}:${String(p.m).padStart(2, "0")}${p.h < 12 ? "am" : "pm"}`;
};

/** Every window on a row, whichever shape it came in. */
export const windowsOf = (row) => {
	if (!row) return [];
	if (Array.isArray(row.rules) && row.rules.length) {
		return row.rules.map((r) => ({
			days: r.days ?? [],
			start: r.start_time,
			end: r.end_time,
			budget: r.budget,
			date: r.date,
			type: r.type,
		}));
	}
	if (row.start_time || (row.days ?? []).length || row.date) {
		return [
			{
				days: row.days ?? [],
				start: row.start_time,
				// a bid rule names the same thing `stop_time`
				end: row.stop_time ?? row.end_time,
				date: row.date,
				type: row.type,
			},
		];
	}
	return [];
};

/** "Fri, Sat, Sun · 7:30pm to 2:00am" */
export const describeWindow = (w) => {
	const days =
		w.type === "once" && w.date
			? dayText(w.date)
			: (w.days ?? []).length === 7
				? "Every day"
				: (w.days ?? []).length
					? w.days
							.map(
								(d) =>
									SHORT[DAY_INDEX[String(d).toLowerCase()]] ??
									d,
							)
							.join(", ")
					: "No days set";
	const from = clockText(w.start);
	const to = clockText(w.end);
	if (!from) return `${days} · all day`;
	return `${days} · ${from}${to ? ` to ${to}` : " onwards"}`;
};

/** The soonest moment any of these windows opens, from `now`. */
export const nextOpening = (row, now = new Date()) => {
	let best = null;
	for (const w of windowsOf(row)) {
		const t = hhmm(w.start);
		if (!t) continue;
		const days = (w.days ?? []).length ? w.days : DAY_ORDER;
		for (const d of days) {
			const target = DAY_INDEX[String(d).toLowerCase()];
			if (target == null) continue;
			const at = new Date(now);
			at.setSeconds(0, 0);
			at.setHours(t.h, t.m);
			let delta = (target - now.getDay() + 7) % 7;
			if (delta === 0 && at <= now) delta = 7;
			at.setDate(at.getDate() + delta);
			if (!best || at < best) best = at;
		}
	}
	return best;
};

/**
 * The dates a recurring window actually fires on, inside the automation's run dates.
 *
 * "Every Monday" is only true of a window that gets more than one Monday. An automation
 * that runs from the 10th to the 10th fires at most once, and one whose single day is a
 * Wednesday never fires a Monday window at all. Both are decided by walking the range, so
 * the summary can say "On 10 Sept" or "never runs" instead of a repeat that will not happen.
 *
 * An open-ended range (no end date) is genuinely recurring and returns null, which callers
 * read as "describe it as a repeat". Capped at a year so a long range cannot fan out.
 */
export const fireDates = (days, startIso, endIso, { cap = 366 } = {}) => {
	if (!startIso || !endIso) return null;
	const wanted = new Set(
		((days ?? []).length ? days : DAY_ORDER).map((d) =>
			String(d).toLowerCase(),
		),
	);
	// ⚠️ Formatted from LOCAL fields, never via toISOString(): that converts to UTC first,
	// and local midnight in IST is 18:30 the previous evening, so every date lands a day
	// early. The two-digit padding keeps the output comparable with the ISO inputs.
	const iso = (d) =>
		`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
	const out = [];
	const cursor = new Date(`${startIso}T00:00:00`);
	const end = new Date(`${endIso}T00:00:00`);
	for (let i = 0; i < cap && cursor <= end; i += 1) {
		if (wanted.has(DAY_ORDER[cursor.getDay()])) out.push(iso(cursor));
		cursor.setDate(cursor.getDate() + 1);
	}
	return out;
};

export const WHEN = new Intl.DateTimeFormat("en-IN", {
	weekday: "short",
	hour: "numeric",
	minute: "2-digit",
	hour12: true,
});

/* ────────────────────────────────────────────────────────────────────────────
 * 2. Saying it in plain language
 *
 * One-liners and pills for an automation row, so someone can audit intent without opening
 * the rule. Every one of them describes timing through `describeWindow` above rather than
 * formatting it again: a second copy of that logic drifts in ways that quietly misreport a
 * live rule, dropping the hours from a one-time window so a 4:00pm to 3:00am run reads as a
 * bare date, showing nothing when a window has a start and no end, or matching days against
 * three-letter codes when the engine stores full names ("monday").
 * ──────────────────────────────────────────────────────────────────────────── */

/** "Fri, Sat · 7:30pm to 2:00am", or "Every day · all day". Empty when there is no window. */
const timeWindow = (rule) => {
	const [w] = windowsOf(rule);
	return w ? describeWindow(w) : "";
};

/**
 * Short pill tags for the table's Actions Summary column.
 *
 * Amounts are absolute rupees because that is the only mode the wizard offers. Each tag
 * carries a `detail` line shown when the pill is opened, built from fields the API already
 * returns: `default_budget` doubles as the floor a decrease-window cannot cross, since it is
 * exactly what the schedule reverts to outside its window.
 */
export const budgetScheduleTags = (schedule) => {
	const rules = schedule.rules ?? [];
	if (rules.length === 0) {
		return [
			{
				label: `Fixed Budget ₹${schedule.default_budget}`,
				detail: "No scheduled change",
			},
		];
	}
	const tags = rules.map((r) => {
		// The figure that matters is what the budget BECOMES. A delta ("by ₹240") makes the
		// reader do arithmetic against a default that is not on the pill, and the engine sets
		// a target rather than applying a difference, so the target is also the truer word.
		const verb =
			r.budget >= schedule.default_budget ? "Increase" : "Decrease";
		const label = `${verb} Budget to ₹${r.budget}`;
		const when = timeWindow(r);
		return {
			label,
			detail: `${label} when${when ? ` ${when}` : ""} · Reverts to ₹${schedule.default_budget}`,
		};
	});
	if (schedule.stop_after_window) {
		tags.push({
			label: "Pause Campaign",
			detail: "Pauses the campaign when a window ends, so it stops spending until the next one opens. The automation itself keeps running.",
		});
	}
	return tags;
};

/* ────────────────────────────────────────────────────────────────────────────
 * Ad slots — what a keyword automation targets
 *
 * The Nth SPONSORED listing on the search page, counted among the ads actually shown and
 * nothing else. "Ad #2" is position 5 on a page whose ads sit at 2, 5, 6, 9 and position 3 on
 * one whose ads sit at 1, 3, 5 — the engine finds it, the client never needs the layout.
 * Organic listings never move a bid; they only raise the overlap warning below.
 * Capped at 5 by the API (search is read 48 products deep).
 * ──────────────────────────────────────────────────────────────────────────── */

export const MAX_AD_SLOT = 5;

const ORDINALS = ["first", "second", "third", "fourth", "fifth"];

/** "second" for 2 — the slot as a word, for sentences. */
export const ordinalWord = (slot) => ORDINALS[Number(slot) - 1] ?? "chosen";

/** The target as a rule carries it. `target_ad_slot` from the API; the older field as a fallback. */
export const targetAdSlot = (rule) =>
	rule?.target_ad_slot ?? rule?.target_position ?? null;

/** One line under the wizard's target: what the number means. */
export const adSlotHint = (slot) => {
	const n = Number(slot);
	const nth = Number.isInteger(n) && n >= 1 ? ORDINALS[n - 1] : null;
	if (n > MAX_AD_SLOT) return `Pick Ad #1 to Ad #${MAX_AD_SLOT}.`;
	return `${nth ? `The ${nth}` : "Which"} sponsored listing on the search page, wherever it appears. Organic listings don't count.`;
};

/** `Ad #2 · position 5`, or `Ad #2` when the page position is unknown. */
export const adSlotLabel = (slot, pagePosition) =>
	slot == null
		? "no ad slot"
		: `Ad #${slot}${pagePosition != null ? ` · position ${pagePosition}` : ""}`;

const positionsList = (ps) =>
	ps.length <= 1
		? `position ${ps[0]}`
		: `positions ${ps.slice(0, -1).join(", ")} and ${ps.at(-1)}`;

/**
 * The organic-overlap warning, worded, or null. The API sets `organic_overlap` when most recent
 * checks at a store show us organically ABOVE the target slot — the spend may buy visibility
 * we already have. Shown, never acted on: the engine pushes the ad where it was asked.
 */
export const organicOverlapText = (rule) => {
	const o = rule?.organic_overlap;
	if (!o || !o.organic_positions?.length) return null;
	const where =
		o.target_page_position != null
			? ` (position ${o.target_page_position})`
			: "";
	const stores = o.of > 1 ? ` at ${o.stores} of ${o.of} stores` : "";
	return `Targeting Ad #${targetAdSlot(rule)}${where}, but you already appear organically at ${positionsList(o.organic_positions)}${stores}. This spend may be buying visibility you already have.`;
};

export const bidRuleTags = (rule) => {
	const when = timeWindow(rule);
	const range = rule.max_bid
		? `₹${rule.min_bid}–₹${rule.max_bid}`
		: `min ₹${rule.min_bid}`;
	const slot = targetAdSlot(rule);
	const tags = [
		{
			label: `Target Ad #${slot}`,
			detail: `Hold the ${ORDINALS[slot - 1] ?? `#${slot}`} sponsored listing on the page (${range})${when ? ` · ${when}` : ""}`,
		},
	];
	const overlap = organicOverlapText(rule);
	if (overlap)
		tags.push({
			label: "Already ranks organically",
			detail: overlap,
			tone: "warning",
		});
	return tags;
};

/* ────────────────────────────────────────────────────────────────────────────
 * 3. Checking it before it is armed
 *
 * Derived from the state the wizard already holds, so it is available at the moment of the
 * decision rather than in a log the next morning. Nothing here blocks a save on its own:
 * the summary states these, and the wizard decides which are severe enough to stop on.
 * ──────────────────────────────────────────────────────────────────────────── */

/** A window that ends before it starts runs past midnight into the following day. */
export const crossesMidnight = (trigger) => {
	const a = minutes(trigger.start_time);
	const b = trigger.revert ? minutes(trigger.end_time) : null;
	return a != null && b != null && b <= a;
};

/** Every window an action holds, flattened with the action it belongs to. */
const allWindows = (actions) =>
	actions
		.filter((a) => a.type !== "stop")
		.flatMap((a) => a.triggers.map((t) => ({ action: a, t })));

/**
 * Problems worth saying out loud, each as { level, text }.
 *
 * `level` is "block" for something the engine cannot act on sensibly, "warn" for something
 * legal that is probably not what was meant. The wizard blocks on the first and states the
 * second, because a warning that stops you is indistinguishable from a bug when it is wrong.
 */
export const scheduleIssues = ({
	actions,
	defaultBudget,
	currentBudget,
	minBudget = null,
	marketplaceName = "The marketplace",
}) => {
	const out = [];
	const base = Number(defaultBudget) || 0;

	// ── below the marketplace's published minimum daily budget ─────────────────
	//
	// Zepto publishes ₹500 and refuses anything lower; Blinkit publishes none (`minBudget`
	// null). Blocked here because the API refuses it too — the save would fail anyway.
	if (minBudget != null) {
		const low = [
			base,
			...actions
				.filter((a) => a.budget != null && a.type !== "stop")
				.map((a) => Number(a.budget)),
		].filter((v) => v > 0 && v < minBudget);
		if (low.length) {
			out.push({
				level: "block",
				text: `${marketplaceName} does not accept a daily budget below ₹${minBudget.toLocaleString("en-IN")}. Raise ${low.length > 1 ? "each amount" : "the amount"} to at least that.`,
			});
		}
	}

	// ── a window with no day chosen ──────────────────────────────────────────
	//
	// ⚠️ The engine reads an empty day list as EVERY day, which is the opposite of what an
	// empty row of chips looks like. Rather than caption that, it is refused: Select All is
	// how you say every day, and it has to be said.
	for (const a of actions) {
		if (a.triggers.some((t) => !t.date && (t.days?.length ?? 0) === 0)) {
			out.push({
				level: "block",
				text: "One window has no day chosen. Pick the days it runs on, or Select All for every day.",
			});
			break;
		}
	}

	// ── an action that can never fire ────────────────────────────────────────
	for (const a of actions) {
		if (a.type !== "stop" && a.triggers.length === 0) {
			out.push({
				level: "block",
				text: "One action has no time window, so it will never run.",
			});
			break;
		}
	}

	// ── Stop beside Start ────────────────────────────────────────────────────
	if (
		actions.some((a) => a.type === "stop") &&
		actions.some((a) => a.type === "start")
	) {
		out.push({
			level: "warn",
			text: "Start Campaign and Pause Campaign are both on. Each window starts the campaign and pauses it again when it ends, which is what Pause Campaign already does on its own.",
		});
	}

	// ── two windows covering the same hours on the same day ──────────────────
	const w = allWindows(actions);
	outer: for (let i = 0; i < w.length; i += 1) {
		for (let j = i + 1; j < w.length; j += 1) {
			const [x, y] = [w[i], w[j]];
			const xd = x.t.days?.length ? x.t.days : DAY_ORDER;
			const yd = y.t.days?.length ? y.t.days : DAY_ORDER;
			if (!xd.some((d) => yd.includes(d))) continue;
			const xs = minutes(x.t.start_time);
			const ys = minutes(y.t.start_time);
			if (xs == null || ys == null) continue;
			const xe = x.t.revert ? (minutes(x.t.end_time) ?? 1440) : 1440;
			const ye = y.t.revert ? (minutes(y.t.end_time) ?? 1440) : 1440;
			// Windows that run past midnight are treated as running to end of day here, which
			// over-reports rather than under-reports. An overlap warning that fires slightly
			// too often is cheaper than one that misses a real clash.
			if (xs < (ye <= ys ? 1440 : ye) && ys < (xe <= xs ? 1440 : xe)) {
				out.push({
					level: "warn",
					text: "Two windows cover the same hours on the same day. Whichever the engine reaches first wins, so the other one's budget may never apply.",
				});
				break outer;
			}
		}
	}

	// ── the baseline nobody meant to change ──────────────────────────────────
	if (currentBudget != null && base && base !== currentBudget) {
		out.push({
			level: "warn",
			text: `This changes the campaign's everyday budget from ₹${currentBudget.toLocaleString("en-IN")} to ₹${base.toLocaleString("en-IN")}, outside your windows as well as inside them.`,
		});
	}
	if (currentBudget == null && base) {
		out.push({
			level: "warn",
			text: `${marketplaceName} has not reported what this campaign runs at today, so there is no way to check what this baseline is changing it from.`,
		});
	}

	return out;
};
