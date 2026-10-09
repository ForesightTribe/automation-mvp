import { AlertTriangle } from "lucide-react";

import { ACTIONS, budgetProblem } from "./ActionCards";
import {
	clockText,
	crossesMidnight,
	fireDates,
	nextOpening,
	ordinalWord,
	scheduleIssues,
	WHEN,
} from "../automation";
import { formatCurrency } from "../../../lib/format";
import { useAutomationMarketplace } from "../../../context/MarketplaceContext";
import { bidUnit } from "../../../lib/marketplaces";

/**
 * Step 3. Not a receipt of the fields that were filled in, but a statement of what the
 * automation will DO once it is saved, written as sentences.
 *
 * ⚠️ It reads as English on purpose. The earlier version laid the same facts out as label
 * and value pairs pushed to opposite edges of the card, which turned a schedule anybody
 * could describe in one line into a form to be decoded. The facts that are genuinely
 * reference data (type, campaign, dates) sit in a tight block where the label and its answer
 * are adjacent; everything about BEHAVIOUR is prose.
 *
 * Everything here is derived from the same state the submit handler sends, so what is read
 * on this step is what the engine is asked for.
 */
const DAY_LABEL = {
	sunday: "Sunday",
	monday: "Monday",
	tuesday: "Tuesday",
	wednesday: "Wednesday",
	thursday: "Thursday",
	friday: "Friday",
	saturday: "Saturday",
};

const SHORT = {
	sunday: "Sun",
	monday: "Mon",
	tuesday: "Tue",
	wednesday: "Wed",
	thursday: "Thu",
	friday: "Fri",
	saturday: "Sat",
};

/** "Every Monday", "Mon and Wed", "Mon, Wed and Fri", "Every day". Sentence-leading.
 *
 * Nothing chosen is NOT every day: it is a window with no days, which the wizard refuses to
 * save. Saying "Every day" for it would describe a rule nobody wrote. */
const daysText = (days) => {
	if (!days?.length) return "no days set";
	if (days.length === 7) return "Every day";
	const names = days.map((d) =>
		days.length === 1
			? (DAY_LABEL[String(d).toLowerCase()] ?? d)
			: (SHORT[String(d).toLowerCase()] ?? d),
	);
	if (names.length === 1) return `Every ${names[0]}`;
	return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
};

const dateText = (iso) =>
	iso
		? new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", {
				day: "numeric",
				month: "short",
				year: "numeric",
			})
		: null;

/** Label and answer sit next to each other, not at opposite ends of the card. */
const Facts = ({ rows }) => (
	<dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
		{rows.map(([label, value, title]) => (
			<div key={label} className="contents">
				<dt className="whitespace-nowrap text-content-muted">
					{label}
				</dt>
				<dd
					className="min-w-0 truncate font-medium text-content"
					title={title}
				>
					{value}
				</dd>
			</div>
		))}
	</dl>
);

/**
 * A brand edge down the left of the card, and nothing else.
 *
 * ⚠️ No tinted fills. A pale wash of brand behind a field reads as a highlight, which is to
 * say as a state, and none of these fields are in one. The edge and the brand-coloured times
 * inside the sentences carry the identity; everything else stays on white.
 */
const Section = ({ title, children }) => (
	<section className="overflow-hidden rounded-lg border border-border border-l-[3px] border-l-brand bg-card px-4 py-3.5">
		<h3 className="mb-3 text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
			{title}
		</h3>
		{children}
	</section>
);

const Note = ({ tone = "muted", children }) => (
	<p
		className={`flex items-start gap-1.5 text-[11px] leading-relaxed ${
			tone === "warn" ? "text-warning" : "text-content-subtle"
		}`}
	>
		{tone === "warn" && (
			<AlertTriangle size={12} className="mt-0.5 shrink-0" />
		)}
		<span>{children}</span>
	</p>
);

export const WizardSummary = ({
	kind,
	campaignLabel,
	campaignId,
	keyword,
	matchType,
	name,
	defaultBudget,
	actions,
	stopAfterWindow,
	timing,
	targetPosition,
	minBid,
	maxBid,
	city,
	locationName,
	effectiveFloor,
	isEdit,
	onActionBudgetChange,
	currentBudget,
	writeMode,
}) => {
	const {
		marketplace,
		name: mpName,
		minDailyBudget,
	} = useAutomationMarketplace();
	const unit = bidUnit(marketplace);
	const base = Number(defaultBudget) || 0;
	const stops = stopAfterWindow || actions.some((a) => a.type === "stop");
	const scheduled = actions.filter((a) => a.type !== "stop");
	const issues =
		kind === "campaign"
			? scheduleIssues({
					actions,
					defaultBudget,
					currentBudget,
					minBudget: minDailyBudget,
					marketplaceName: mpName,
				})
			: [];

	// The first moment this will actually act, from the same windows the engine gets.
	const pseudo =
		kind === "campaign"
			? {
					rules: scheduled.flatMap((a) =>
						a.triggers.map((t) => ({
							days: t.days,
							start_time: t.start_time,
							end_time: t.revert ? t.end_time : null,
						})),
					),
				}
			: {
					days: timing.days,
					start_time: timing.start_time,
					stop_time: timing.end_time,
					type: timing.type,
					date: timing.date,
				};
	/** A fire date and a start time as one moment. No start time means "sometime today",
	 * so it is treated as the end of that day: an all-day window today has not gone by. */
	const fireMoment = (isoDate, startTime) => {
		const at = new Date(`${isoDate}T00:00:00`);
		const [h, m] = startTime
			? String(startTime).split(":").map(Number)
			: [23, 59];
		at.setHours(h || 0, m || 0, 0, 0);
		return at.getTime();
	};

	/**
	 * The first moment this will act, respecting the run dates. `nextOpening` walks
	 * weekdays from today and knows nothing about the range, so for a bounded automation it
	 * can name a Monday that falls after the end date. Bounded ranges are walked instead;
	 * `null` means nothing inside the range matches, which the reader is told outright.
	 */
	const firstFire = (() => {
		if (kind !== "campaign" || !timing.start_date || !timing.end_date)
			return undefined;
		const now = Date.now();
		let best = null;
		let anyInRange = false;
		for (const a of scheduled) {
			for (const t of a.triggers) {
				const dates = t.date
					? [t.date]
					: (fireDates(t.days, timing.start_date, timing.end_date) ??
						[]);
				for (const d of dates) {
					anyInRange = true;
					const at = fireMoment(d, t.start_time);
					if (at >= now && (best === null || at < best)) best = at;
				}
			}
		}
		// Three answers, not two: a date, "already passed", or "never". Collapsing the
		// last two into one would blame the run dates for a window that merely went by.
		return best !== null ? new Date(best) : anyInRange ? "past" : null;
	})();
	const next =
		firstFire === undefined
			? nextOpening(pseudo)
			: firstFire instanceof Date
				? firstFire
				: null;

	const from = dateText(timing.start_date);
	const to = dateText(timing.end_date);
	const onceTrigger = scheduled
		.flatMap((a) => a.triggers)
		.find((t) => t.date);
	const active = from
		? to
			? `${from} to ${to}`
			: `${from} onwards`
		: onceTrigger
			? `${dateText(onceTrigger.date)} only`
			: "Not set";

	const facts =
		kind === "campaign"
			? [
					["Type", "Campaign budget automation"],
					["Marketplace", mpName],
					[
						"Campaign",
						campaignLabel || "Not selected",
						campaignId ? `ID ${campaignId}` : undefined,
					],
					["Name", name || "Untitled"],
					["Active", active],
					[
						"First check",
						next
							? WHEN.format(next)
							: firstFire === "past"
								? "Already passed: every chosen time in the run dates has gone by"
								: firstFire === null
									? "Never: no chosen day falls inside the run dates"
									: "Not scheduled",
					],
				]
			: [
					["Type", "Keyword bid automation"],
					["Marketplace", mpName],
					[
						"Campaign",
						campaignLabel || "Not selected",
						campaignId ? `ID ${campaignId}` : undefined,
					],
					[
						"Keyword",
						keyword
							? `“${keyword}”, ${matchType} match`
							: "Not selected",
					],
					["Active", active],
					["First check", next ? WHEN.format(next) : "Not scheduled"],
				];

	/** One window, as a sentence, with its amount still editable inside it. */
	const sentence = (a, t) => {
		const meta = ACTIONS.find((x) => x.id === a.type);
		const at = clockText(t.start_time) || "the first check of the day";
		const back = t.revert && t.end_time ? clockText(t.end_time) : null;
		const over = crossesMidnight(t) ? " the next morning" : "";

		/**
		 * "Every Monday" is only true when the run dates hold more than one Monday that has
		 * not yet happened. The firings still ahead decide the wording: none in the range
		 * and the window is dead; some in the range but all behind us and it is in the past;
		 * exactly one ahead and it is a date rather than a repeat; more, and it repeats.
		 */
		const inRange = t.date
			? [t.date]
			: fireDates(t.days, timing.start_date, timing.end_date);
		if (inRange && inRange.length === 0) {
			const names = daysText(t.days).replace(/^Every /, "");
			return (
				<span className="text-warning">
					<AlertTriangle size={13} className="mr-1 inline" />
					This window never runs:{" "}
					{t.days?.length > 1
						? `none of ${names}`
						: `no ${names}`}{" "}
					falls between {from} and {to}.
				</span>
			);
		}
		const ahead = inRange
			? inRange.filter((d) => fireMoment(d, t.start_time) >= Date.now())
			: null;
		if (ahead && ahead.length === 0) {
			const last = inRange[inRange.length - 1];
			return (
				<span className="text-warning">
					<AlertTriangle size={13} className="mr-1 inline" />
					This window is in the past: {dateText(last)} at {at} has
					already gone by, so it will not run.
				</span>
			);
		}
		const on = ahead
			? ahead.length === 1
				? `On ${dateText(ahead[0])}`
				: daysText(t.days)
			: daysText(t.days);
		const amount = a.budget ?? base;
		const verb =
			amount > base
				? "goes up to"
				: amount < base
					? "comes down to"
					: "is set to";

		if (a.type === "start") {
			return (
				<>
					{on} at <b className="text-brand">{at}</b>, the campaign is
					started and runs at {formatCurrency(base)}
					{back ? (
						<>
							, then returns to its default at{" "}
							<b className="text-brand">{back}</b>
							{over}
						</>
					) : (
						" for the rest of the day"
					)}
					.
				</>
			);
		}
		if (a.type === "stop") {
			return (
				<>
					{on} at <b className="text-brand">{at}</b> the campaign runs
					at {formatCurrency(base)}
					{back ? (
						<>
							, and is{" "}
							<b className="text-brand">paused at {back}</b>
							{over}
						</>
					) : (
						", and is paused at the end of the day"
					)}
					.
				</>
			);
		}
		return (
			<>
				{on} at <b className="text-brand">{at}</b>, the budget {verb}{" "}
				{onActionBudgetChange && meta?.needsBudget ? (
					<span className="inline-flex items-baseline rounded-md border border-border bg-card focus-within:border-content">
						<span className="pl-1.5 text-content-muted">₹</span>
						<input
							type="number"
							aria-label={`${meta.label} amount`}
							value={a.budget ?? ""}
							onChange={(e) =>
								onActionBudgetChange(
									a.id,
									e.target.value === ""
										? null
										: Number(e.target.value),
								)
							}
							className="w-20 bg-transparent px-1 py-0.5 text-sm font-semibold text-content tabular-nums focus:outline-none"
						/>
					</span>
				) : (
					<b className="text-brand">{formatCurrency(amount)}</b>
				)}
				{back ? (
					<>
						, then back to {formatCurrency(base)} at{" "}
						<b className="text-brand">{back}</b>
						{over}
					</>
				) : (
					" for the rest of the day"
				)}
				.
			</>
		);
	};

	return (
		<div className="mx-auto flex max-w-2xl flex-col gap-4">
			<Section title="The automation">
				<Facts rows={facts} />
			</Section>

			{kind === "campaign" ? (
				<Section title="What it will do">
					<div className="flex flex-col gap-2.5">
						{scheduled.length === 0 ? (
							<p className="text-sm text-content-muted">
								No scheduled change.{" "}
								{campaignLabel || "The campaign"} stays at{" "}
								{formatCurrency(base)} throughout.
							</p>
						) : (
							scheduled.map((a) =>
								a.triggers.length === 0 ? (
									<p
										key={a.id}
										className="text-sm text-warning"
									>
										{
											ACTIONS.find((x) => x.id === a.type)
												?.label
										}{" "}
										has no time window, so it will never
										run.
									</p>
								) : (
									a.triggers.map((t) => (
										<p
											key={t.id}
											className="text-sm leading-relaxed text-content"
										>
											{sentence(a, t)}
										</p>
									))
								),
							)
						)}

						<p className="border-t border-border pt-2.5 text-sm text-content-muted">
							At every other time it runs at its default of{" "}
							{formatCurrency(base)}.
							{stops &&
								" The campaign is paused whenever a window ends, until the next one opens."}
						</p>

						{scheduled.map((a) => {
							const problem = budgetProblem(a, base);
							return problem ? (
								<Note key={a.id} tone="warn">
									{problem}
								</Note>
							) : null;
						})}
					</div>
				</Section>
			) : (
				<Section title="What it will do">
					<p className="text-sm leading-relaxed text-content">
						{timing.type === "once" && timing.date
							? `On ${dateText(timing.date)}`
							: daysText(timing.days)}{" "}
						at{" "}
						<b className="text-brand">
							{clockText(timing.start_time) || "the first check"}
						</b>
						, it checks where the ad for “{keyword}” sits in{" "}
						{city || locationName || "the chosen city"} and moves
						the bid to hold{" "}
						<b className="text-brand">
							Ad #{targetPosition || "?"}
						</b>{" "}
						(the {ordinalWord(targetPosition)} sponsored listing on
						the page, wherever it appears), never below{" "}
						{minBid
							? formatCurrency(Number(minBid))
							: "the minimum you set"}
						{maxBid ? (
							<>
								{" "}
								and never above {formatCurrency(Number(maxBid))}
							</>
						) : (
							" and with no ceiling"
						)}{" "}
						({unit.code}, {unit.per}).
						{timing.end_time
							? ` It stops checking at ${clockText(timing.end_time)}.`
							: ""}
					</p>
					{effectiveFloor != null && (
						<p className="mt-2 text-[11px] text-content-subtle">
							{mpName}'s published minimum for this keyword is{" "}
							{formatCurrency(effectiveFloor)} {unit.per}.
						</p>
					)}
					{/* Zepto picks one of the campaign's own cities when none is chosen (the
					    frozen city first, else the one with the most stores), so a blank
					    city is a choice there, not a mistake. */}
					{!city &&
						!locationName &&
						(marketplace === "zepto" ? (
							<Note>
								No city chosen, so one of the campaign's own
								cities is picked when this is saved. The list
								shows which one.
							</Note>
						) : (
							<Note tone="warn">
								Without a city the engine measures at a default
								store, which is probably not where you meant.
							</Note>
						))}
				</Section>
			)}

			{issues.length > 0 && (
				<ul className="flex flex-col gap-1.5">
					{issues.map((i) => (
						<li key={i.text}>
							<Note tone="warn">{i.text}</Note>
						</li>
					))}
				</ul>
			)}

			{writeMode === "dry" && (
				<Note tone="warn">
					Automations on {mpName} only simulate their changes right
					now: the engine&rsquo;s live switch for this account is off,
					so nothing will change on {mpName} until it is turned on.
				</Note>
			)}

			<Note>
				{isEdit
					? "Saving replaces the rules on this automation. Windows removed here stop firing straight away."
					: `This starts acting on your ${mpName} account as soon as the first window opens.`}
			</Note>
		</div>
	);
};
