import { useEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import { Button } from "../../../components/ui/Button";
import { ChannelBadge } from "./ChannelBadge";
import { CampaignPickerList } from "./CampaignPickerList";
import { JobLine } from "./JobLine";
import { KeywordPicker } from "./KeywordPicker";
import { ActionCards } from "./ActionCards";
import { KeywordActionCard } from "./KeywordActionCard";
import { DatePicker } from "../../../components/ui/DatePicker";
import { Field, FIELD_INPUT } from "./Field";
import { scheduleIssues } from "../automation";
import { WizardContext } from "./WizardContext";
import { WizardSummary } from "./WizardSummary";
import { formatMeasuredAt } from "../../../lib/format";
import { useAutomationMarketplace } from "../../../context/MarketplaceContext";
import { autoPicksLocation } from "../../../lib/marketplaces";
import {
	useCreateBudgetSchedule,
	useUpdateBudgetSchedule,
	useAddBudgetRule,
	useUpdateBudgetRule,
	useCreateBidRule,
	useUpdateBidRule,
	useAllKeywordMetrics,
	useBidContext,
	useCampaigns,
	useDeleteBudgetRule,
	useWriteMode,
} from "../hooks";

const STEPS = ["Automation Details", "Create Actions", "Summary"];

// Actions whose rule carries an amount of its own. "start" runs at the default and "stop"
// is a flag on the schedule, so neither has one to set.
const NEEDS_BUDGET = new Set(["increase", "decrease"]);

const emptyTiming = {
	type: "recurring",
	days: [],
	start_time: "",
	end_time: "",
	date: "",
	start_date: "",
	end_date: "",
};

const todayIso = () => new Date().toISOString().slice(0, 10);

/**
 * One wizard, two modes — matches Dcluttr's own pattern of reusing the exact
 * same "Add Automation Details -> Create Actions -> Summary" stepper for both
 * Create and Edit, just pre-filled and with identity fields (kind, campaign)
 * locked once an automation exists. Full-screen overlay, not a side drawer —
 * this is a multi-step flow, not a quick detail panel.
 *
 * `editRow` present = edit mode (calls the update* hooks, budget rules via
 * add/update since a schedule's rule is its own sub-resource); absent =
 * create mode (calls create* with `initialKind` as the starting type).
 *
 * Amount is always an absolute ₹ delta — no percentage mode — so the summary
 * and the table's action pills both show the raw number the user entered.
 */
export const AutomationWizard = ({
	open,
	onClose,
	editRow,
	initialKind = "campaign",
	onActivateCampaign,
	activationJobId,
	activationError = null,
}) => {
	const isEdit = Boolean(editRow);
	const [step, setStep] = useState(1);
	// The one marketplace this wizard creates on — the navbar's choice for the automation
	// pages. Every save goes to its address; its name goes in the copy; its minimum daily
	// budget (Zepto ₹500) is checked before the save rather than refused by it.
	const {
		marketplace,
		name: mpName,
		minDailyBudget,
	} = useAutomationMarketplace();
	// Zepto picks one of the campaign's own cities when a keyword rule names none, so there
	// the city is optional; Blinkit would fall back to a default store nobody chose.
	const locationOptional = autoPicksLocation(marketplace);
	// Why the last save failed, in the server's words. A save is several requests (a
	// schedule, then each extra rule), and without this a refusal left the wizard sitting
	// on "Create Automation" with nothing said at all (ZC-E11).
	const [saveError, setSaveError] = useState(null);
	// Everything below the picker on step 1 describes whatever is being picked, so none of it
	// is answerable until that list has arrived. Showing the fields first invites someone to
	// fill them in and then have the step reflow underneath them when the list lands. Each
	// path waits on its OWN list: the campaign path on campaigns, the keyword path on the
	// keyword metrics its picker reads.
	// Only while open: the wizard is mounted closed on the page, and these used to load
	// the campaign list and every keyword page on page open for a dialog nobody had opened
	// (2026-09-25 — part of the burst that exhausted the API's connection pool).
	const { isLoading: loadingCampaigns } = useCampaigns({ enabled: open });
	const { isLoading: loadingKeywords } = useAllKeywordMetrics({
		enabled: open,
	});
	const [kind, setKind] = useState(isEdit ? editRow.kind : initialKind);
	// Declared after `kind`, which it reads: a const is in its temporal dead zone until its
	// own line, so ordering here is correctness rather than tidiness.
	const loadingPicker =
		kind === "keyword" ? loadingKeywords : loadingCampaigns;
	const [campaign, setCampaign] = useState(null);

	const [name, setName] = useState("");
	const [defaultBudget, setDefaultBudget] = useState("");
	const [keyword, setKeyword] = useState("");
	// No control for this — v2 has none either, and the engine defaults to EXACT. Kept as
	// state so EDITING a rule preserves the match type it already has rather than
	// silently rewriting it to EXACT on save.
	const [matchType, setMatchType] = useState("EXACT");

	// [{ id, type, budget, triggers: [{ id, start_time, days[], revert, end_time }] }]
	const [actions, setActions] = useState([]);
	/**
	 * ⚠️ Derived from the cards, never held separately.
	 *
	 * "Stop Campaign" is `stop_after_window` on the schedule rather than a rule of its own,
	 * so the card IS the flag: it is derived from the cards on save and never held in state
	 * beside them. A separate copy lets the two disagree, either drawing no card for a flag
	 * that is set, or keeping a flag alive after the card for it is removed.
	 */
	/**
	 * Two ways to say the same thing, and still only ONE flag.
	 *
	 * `stop_after_window` can be set either by adding a Pause Campaign action or by ticking
	 * "and pause the campaign" on a window's revert row, because that is where the thought
	 * usually occurs. Both feed a DERIVED value rather than a second stored copy, so the two
	 * entry points cannot disagree about what will be saved.
	 */
	// Set when Continue is pressed on an unsatisfied step, cleared on every step change: the
	// reader is told what is missing at the moment they ask to move on, not while they are
	// still filling the step in.
	const [triedToAdvance, setTriedToAdvance] = useState(false);
	const [pauseAtEnd, setPauseAtEnd] = useState(
		isEdit ? Boolean(editRow?.stop_after_window) : false,
	);
	const stopAfterWindow =
		pauseAtEnd || actions.some((a) => a.type === "stop");
	const [timing, setTiming] = useState(emptyTiming);

	const [targetPosition, setTargetPosition] = useState("");
	const [minBid, setMinBid] = useState("");
	const [maxBid, setMaxBid] = useState("");
	// Where position is measured. NOT optional: with no location the engine falls back to
	// a default Bengaluru store, so the rule would silently measure somewhere nobody chose.
	const [city, setCity] = useState("");
	const [locationId, setLocationId] = useState("");
	// The target picker is a transient tool: open until it has an answer, collapsed after,
	// re-opened by "Change". Tracked separately from the selection so re-opening it does
	// not clear what is already chosen.
	const [pickerOpen, setPickerOpen] = useState(true);

	useEffect(() => {
		if (!open) return;
		if (isEdit) {
			setKind(editRow.kind);
			setCampaign({
				campaign_id: editRow.campaign_id,
				name: editRow.campaign_name,
			});
			if (editRow.kind === "campaign") {
				// Stored rules → action cards. Rules sharing a budget are one action with
				// several triggers, which is exactly how they were created. `ruleId` is kept on
				// each trigger so saving can tell an edit from an addition, and so a trigger
				// removed here deletes the rule it came from rather than orphaning it.
				const byBudget = new Map();
				for (const r of editRow.rules ?? []) {
					if (!byBudget.has(r.budget)) byBudget.set(r.budget, []);
					byBudget.get(r.budget).push(r);
				}
				const cards = [...byBudget.entries()].map(
					([budget, rules]) => ({
						id: `a${budget}`,
						type:
							budget > editRow.default_budget
								? "increase"
								: budget < editRow.default_budget
									? "decrease"
									: "start",
						budget,
						triggers: rules.map((r) => ({
							id: `t${r.id}`,
							ruleId: r.id,
							start_time: r.start_time ?? "",
							days: r.days ?? [],
							revert: Boolean(r.end_time),
							end_time: r.end_time ?? "",
							// ⚠️ A rule may be one-time (`type: "once"` + `date`), which this wizard has
							// no control for: it only creates recurring windows. Carrying the pair
							// through untouched is what stops an edit from silently converting a
							// one-off into something that fires every day from now on.
							type: r.type ?? "recurring",
							date: r.date ?? null,
						})),
					}),
				);
				// The schedule flag becomes a card, so what the table lists as two actions
				// opens as two actions, and removing the card actually clears the flag.
				if (editRow.stop_after_window) {
					cards.push({
						id: "stop",
						type: "stop",
						budget: null,
						triggers: [],
					});
				}
				setActions(cards);
				setName(editRow.name ?? "");
				setDefaultBudget(String(editRow.default_budget ?? ""));
				// The cards above already carry every rule; this only lifts the automation's DATE
				// RANGE out of the first one, which is the automation-level field step 1 shows
				// and which ruleBodies() stamps back onto every window.
				const rule = editRow.rules?.[0];
				if (rule) {
					setTiming({
						type: rule.type ?? "recurring",
						days: rule.days ?? [],
						start_time: rule.start_time ?? "",
						end_time: rule.end_time ?? "",
						date: rule.date ?? "",
						start_date: rule.start_date ?? "",
						end_date: rule.end_date ?? "",
					});
				} else {
					setTiming(emptyTiming);
				}
			} else {
				setKeyword(editRow.keyword ?? "");
				setMatchType(editRow.match_type ?? "EXACT");
				setTargetPosition(String(editRow.target_position ?? ""));
				setMinBid(String(editRow.min_bid ?? ""));
				setMaxBid(
					editRow.max_bid != null ? String(editRow.max_bid) : "",
				);
				// Blank = keep the rule's existing measurement store; typing replaces it.
				setCity("");
				setLocationId("");
				setTiming({
					type: editRow.type ?? "recurring",
					days: editRow.days ?? [],
					start_time: editRow.start_time ?? "",
					end_time: editRow.stop_time ?? "",
					date: editRow.date ?? "",
					start_date: editRow.start_date ?? "",
					end_date: editRow.stop_date ?? "",
				});
			}
		} else {
			setKind(initialKind);
			setCampaign(null);
			setName("");
			setDefaultBudget("");
			setKeyword("");
			setMatchType("EXACT");
			setActions([]);
			setTiming({ ...emptyTiming, start_date: todayIso() });
			setTargetPosition("");
			setMinBid("");
			setMaxBid("");
			setCity("");
			setLocationId("");
		}
		setPickerOpen(true);
		setStep(1);
		setSaveError(null);
	}, [open, isEdit, editRow, initialKind]);

	const { mode: writeMode } = useWriteMode({ enabled: open });
	// What the campaign runs at TODAY, which is what any baseline change is measured against.
	// The marketplace reports it for only some campaigns, so it is often unknown and never
	// guessed.
	const currentBudget = isEdit
		? (editRow.default_budget ?? null)
		: (campaign?.daily_budget ?? null);

	const createSchedule = useCreateBudgetSchedule();
	const updateSchedule = useUpdateBudgetSchedule();
	const addRule = useAddBudgetRule();
	const updateRule = useUpdateBudgetRule();
	const createBid = useCreateBidRule();
	const updateBid = useUpdateBidRule();
	const deleteRule = useDeleteBudgetRule();
	const saving =
		createSchedule.isPending ||
		updateSchedule.isPending ||
		addRule.isPending ||
		updateRule.isPending ||
		createBid.isPending ||
		updateBid.isPending;

	// ── Keyword context: the marketplace's published floors + the campaign's cities ──
	// Both come from the daily scrape and are read-only. An unscraped campaign returns
	// empty fields rather than 404ing, so every branch below degrades to free text.
	const campaignId = campaign?.campaign_id ?? null;
	const { data: ctx, isPending: ctxPending } = useBidContext(
		kind === "keyword" ? campaignId : null,
	);

	// The keyword itself is chosen in <KeywordPicker> — from /ads/keywords on Blinkit, from
	// the campaign catalogue on Zepto. bid-context only supplies what surrounds it: the
	// marketplace's published floors and the campaign's targeted cities.
	// The published floor for the CHOSEN keyword AND match type. It varies per keyword (₹200
	// on one, ₹400 on another in the same campaign) and, on Zepto, per match type (the same
	// keyword's PHRASE floor can be double its EXACT one), so it resolves only once both are
	// known. It used to match EXACT only, which read Zepto's PHRASE/BROAD rules against the
	// wrong floor.
	const floor = useMemo(() => {
		const kw = keyword.trim().toLowerCase();
		if (!kw) return null;
		return (
			(ctx?.keywords ?? []).find(
				(k) =>
					k.match_type === matchType &&
					k.keyword.toLowerCase() === kw,
			) ?? null
		);
	}, [ctx, keyword, matchType]);

	// The campaign's published floors, available the moment a campaign is picked — before
	// any keyword is typed. Floors differ per keyword within one campaign (₹200–₹400 is
	// normal), so a campaign has a RANGE; only when every keyword shares one floor is
	// there a single campaign-level number.
	const campaignFloor = useMemo(() => {
		const vals = (ctx?.keywords ?? [])
			.map((k) => k.min_bid)
			.filter((v) => v !== null && v !== undefined);
		if (!vals.length) return null;
		const lo = Math.min(...vals);
		const hi = Math.max(...vals);
		return { lo, hi, single: lo === hi, count: vals.length };
	}, [ctx]);

	// Prefill the min bid, and re-prefill when the CAMPAIGN changes — selecting a different
	// campaign must update the floor rather than leaving the previous campaign's number
	// sitting there. A value typed by hand is never overwritten: only a field that is empty
	// or still holds exactly what we last filled in is replaced.
	const autoFilled = useRef(null);
	// Same idea for the default daily budget: selecting a campaign fills it with what that
	// campaign currently runs at, and switching campaigns updates it — but a number typed by
	// hand is never overwritten. Blinkit only reports `daily_budget` for campaigns whose
	// budget has been read live at least once, so it is often absent; the field then stays
	// empty rather than inventing a figure, and the hint says so.
	const autoFilledBudget = useRef(null);
	useEffect(() => {
		const live = campaign?.daily_budget;
		if (live == null || isEdit) return;
		if (
			defaultBudget === "" ||
			defaultBudget === autoFilledBudget.current
		) {
			autoFilledBudget.current = String(live);
			setDefaultBudget(String(live));
		}
	}, [campaign, defaultBudget, isEdit]);
	useEffect(() => {
		const next =
			floor?.min_bid != null
				? floor.min_bid
				: campaignFloor?.single
					? campaignFloor.lo
					: null;
		if (next == null) return;
		if (minBid === "" || minBid === autoFilled.current) {
			autoFilled.current = String(next);
			setMinBid(String(next));
		}
	}, [floor, campaignFloor, minBid]);

	// Where this rule may measure — the WHOLE answer, already sorted, already canonical, and
	// already narrowed to the campaign's own cities when it targets some. The form does not
	// second-guess it: there is no second city source to fall back to (see `_measurement_cities`).
	const cityOptions = ctx?.cities ?? [];
	// Auto-fill only when the campaign genuinely has one city. A one-city CATALOGUE would
	// mean something very different, so this reads `region_type`, never the list's length.
	const singleCity =
		ctx?.region_type === "CITY" && cityOptions.length === 1
			? cityOptions[0]
			: null;

	// A city chosen for one campaign need not exist in the next one's list, and a value that
	// matches no option reads as an empty field while still being what gets saved. Declared
	// ABOVE the auto-fill so a campaign switch clears before that refills, not after.
	useEffect(() => {
		setCity("");
	}, [campaignId]);

	useEffect(() => {
		if (singleCity && !city && !locationId) setCity(singleCity.name);
	}, [singleCity, city, locationId]);

	// Clearing this on every step change is what keeps the message tied to the moment
	// Continue was pressed: it is stale as soon as the step is satisfied, and it must not
	// follow the reader into the next step.
	useEffect(() => {
		setTriedToAdvance(false);
	}, [step]);

	// Below the floor the engine would raise the bid to it on the first write, so saving a
	// lower number would quietly not mean what it says — block instead.
	// Below the exact keyword floor when we know it; otherwise below the campaign's LOWEST
	// published floor, which no keyword on it can legally sit under either.
	const effectiveFloor = floor?.min_bid ?? campaignFloor?.lo ?? null;
	const belowFloor =
		effectiveFloor != null &&
		minBid !== "" &&
		Number(minBid) < effectiveFloor;
	const hasLocation = Boolean(
		city || locationId || (isEdit && editRow?.location_name),
	);
	// What this rule measures at TODAY, said in full ("Block C, Kolkata"). Shown when editing,
	// where leaving the city blank keeps it — so the reader has to be able to tell what they
	// are keeping, and a bare store label does not say where it is.
	const existingLocation = formatMeasuredAt(
		editRow?.location_name,
		editRow?.city_name,
	);

	// A bidding automation needs both halves before the picker has done its job; a campaign
	// automation only needs the campaign.
	const targetChosen =
		kind === "keyword" ? Boolean(campaign && keyword) : Boolean(campaign);
	const campaignLabel =
		campaign?.name ??
		campaign?.campaign_name ??
		(campaignId ? `Campaign ${campaignId}` : "");

	if (!open) return null;

	const base = Number(defaultBudget) || 0;
	// The date of a one-off window, if this automation is made of one. It lives on the rule
	// rather than on the automation, so every header that describes "when" has to look here.
	const onceDate =
		actions.flatMap((a) => a.triggers).find((t) => t.date)?.date ?? null;

	// Step 1 can only require what step 1 COLLECTS. Target position and min bid belong to
	// step 2, so requiring them here would hold Continue shut on a keyword automation with no
	// way to satisfy it. `canAdvanceFrom2` is where those are enforced.
	// Below the marketplace's published minimum (Zepto ₹500) the API refuses the save, so the
	// step does not let it through either.
	const belowMinBudget =
		kind === "campaign" &&
		minDailyBudget != null &&
		defaultBudget !== "" &&
		Number(defaultBudget) < minDailyBudget;
	const canAdvanceFrom1 = isEdit
		? !belowMinBudget
		: Boolean(campaign) &&
			(kind === "campaign" ? defaultBudget && !belowMinBudget : keyword);
	// The step labels double as Back/Continue: an earlier step is always reachable (Back),
	// the next one only when this step is valid (Continue), and never further — Continue
	// advances one step at a time, so neither do the labels.
	// Warnings are stated on the summary rather than enforced here: a warning that stops you
	// is indistinguishable from a bug on the occasions it is wrong. Only "block" issues, which
	// the engine genuinely cannot act on, hold the step.
	const blocking =
		kind === "campaign"
			? scheduleIssues({
					actions,
					defaultBudget,
					currentBudget,
					minBudget: minDailyBudget,
					marketplaceName: mpName,
				}).filter((i) => i.level === "block")
			: [];
	// ⚠️ `actions.length` first, and it is load-bearing: `every` is true of an empty array and
	// `scheduleIssues` only inspects the actions it is given, so with no actions at all both
	// tests pass and the summary describes an automation that would do nothing.
	const canAdvanceFrom2 =
		kind === "campaign"
			? actions.length > 0 &&
				actions.every(
					(a) =>
						!NEEDS_BUDGET.has(a.type) ||
						(a.budget != null && a.budget > 0),
				) &&
				blocking.length === 0
			: Boolean(targetPosition && minBid) &&
				(hasLocation || locationOptional) &&
				!belowFloor;

	const canAdvanceNow =
		step === 1 ? canAdvanceFrom1 : step === 2 ? canAdvanceFrom2 : true;
	const stepReachable = (n) =>
		n <= step || (n === step + 1 && Boolean(canAdvanceNow));
	/**
	 * The ONE thing still missing, in the order the step asks for it.
	 *
	 * Not a combined sentence: "pick a campaign and set a budget" keeps naming the campaign
	 * after one has been picked, so the reader re-reads it looking for what they got wrong.
	 * Each branch returns only the first unmet requirement, and the message disappears as
	 * soon as that requirement is met.
	 */
	const missingOnThisStep = () => {
		if (step === 1) {
			if (!campaign) return "Pick a campaign to continue.";
			if (kind === "campaign" && !defaultBudget)
				return "Set a default daily budget to continue.";
			if (belowMinBudget)
				return `${mpName} does not accept a daily budget below ₹${minDailyBudget.toLocaleString("en-IN")}. Raise it to continue.`;
			if (kind === "keyword" && !keyword)
				return "Pick a keyword to continue.";
			return null;
		}
		if (kind === "campaign") {
			if (actions.length === 0)
				return "Add at least one action to continue. An automation with none would never do anything.";
			if (blocking.length) return blocking[0].text;
			return "Give every budget action an amount to continue.";
		}
		if (!targetPosition) return "Set a target position to continue.";
		if (!minBid) return "Set a minimum bid to continue.";
		if (belowFloor)
			return `Raise the min bid to ${mpName}'s published floor to continue.`;
		if (!hasLocation && !locationOptional)
			return "Choose where to measure position to continue.";
		return null;
	};

	const stepBlockedReason = (n) =>
		n !== step + 1
			? `Go through “${STEPS[n - 2]}” first.`
			: (missingOnThisStep() ?? "");

	// Every (action, trigger) pair is one budget rule — that is the whole mapping.
	//   increase / decrease → a rule at the action's budget
	//   start              → a rule at the DEFAULT budget: while a rule is active the
	//                        scheduler returns "running" and starting is unconditional
	//                        (budget.py, AD7), so a window IS the scheduled start
	//   stop               → a window at the DEFAULT budget, exactly like "start". The pause
	//                        itself is `stop_after_window` on the schedule: the engine pauses
	//                        when a window has just ended (budget.py, AD2), so a stop AT a time
	//                        is a window that ENDS at that time. Without a window of its own a
	//                        stop had no time it could be given, which is why it gets one.
	const ruleBodies = () =>
		actions.flatMap((a) =>
			a.triggers.map((t) => ({
				ruleId: t.ruleId ?? null,
				body: {
					budget:
						a.type === "start" || a.type === "stop"
							? base
							: a.budget,
					// A window with a date is a one-off; everything else repeats. Derived rather
					// than stored, so the date field and the day chips cannot disagree.
					type: t.date ? "once" : "recurring",
					days: t.days,
					start_time: t.start_time || null,
					end_time: t.revert ? t.end_time || null : null,
					start_date: timing.start_date || null,
					end_date: timing.end_date || null,
					date: t.date ?? null,
				},
			})),
		);

	/**
	 * Save, and SAY so when it fails (ZC-E11). The server's refusal — a duplicate rule, a
	 * campaign of the wrong marketplace, a budget below the minimum — is the most specific
	 * explanation available, so it is shown as sent. The wizard stays open on the summary
	 * with everything still filled in, so the reader can fix it and save again.
	 *
	 * ⚠️ A campaign automation is several requests. If a later one fails, the earlier ones
	 * have already landed (the schedule exists, some rules may too), and the message says so
	 * rather than implying nothing happened.
	 */
	const submit = async () => {
		setSaveError(null);
		// Set once any request of a multi-request save has landed, so a later failure can say
		// that part of the automation already exists.
		const progress = { landed: false };
		try {
			await save(progress);
			onClose();
		} catch (err) {
			// `lib/axios` rejects with `{ status, data }` — FastAPI's `detail` is a sentence
			// for a refusal and a list of field errors for a 422.
			const detail = err?.data?.detail;
			const said =
				typeof detail === "string"
					? detail
					: Array.isArray(detail)
						? detail.map((d) => d.msg).join("; ")
						: (err?.message ?? "The save failed.");
			setSaveError(
				progress.landed
					? `${said} Part of this automation may already be saved — check the list before trying again.`
					: said,
			);
		}
	};

	const save = async (progress) => {
		if (kind === "campaign") {
			const bodies = ruleBodies();
			// "Stop Campaign" is a schedule flag, not a rule, so it is folded in here.
			// Set by the presence of a Pause Campaign action and nothing else. ⚠️ The engine's
			// flag is schedule-wide, so it pauses at the end of EVERY window on this automation,
			// not only the Pause Campaign one. The summary says so.
			const stopFlag = stopAfterWindow;

			if (isEdit) {
				await updateSchedule.mutateAsync({
					scheduleId: editRow.id,
					body: {
						name: name || null,
						default_budget: base,
						stop_after_window: stopFlag,
					},
				});
				progress.landed = true;
				// A window removed from the cards is a rule that must actually go, or it keeps
				// firing invisibly.
				const kept = new Set(
					bodies.map((b) => b.ruleId).filter(Boolean),
				);
				for (const r of editRow.rules ?? []) {
					if (!kept.has(r.id)) await deleteRule.mutateAsync(r.id);
				}
				for (const { ruleId, body } of bodies) {
					if (ruleId) await updateRule.mutateAsync({ ruleId, body });
					else
						await addRule.mutateAsync({
							scheduleId: editRow.id,
							body,
						});
				}
			} else {
				// The schedule must exist before extra rules can hang off it, so the first
				// window rides along with it and the rest are added afterwards.
				const [first, ...rest] = bodies.map((b) => b.body);
				const schedule = await createSchedule.mutateAsync({
					campaign_id: campaign.campaign_id,
					campaign_name: campaign.name,
					name: name || null,
					default_budget: base,
					stop_after_window: stopFlag,
					rule: first ?? null,
				});
				progress.landed = true;
				for (const body of rest) {
					await addRule.mutateAsync({
						scheduleId: schedule.id,
						body,
					});
				}
			}
		} else {
			const body = {
				campaign_id: campaign.campaign_id,
				campaign_name: campaign.name,
				keyword,
				match_type: matchType,
				target_position: Number(targetPosition),
				min_bid: Number(minBid),
				max_bid: maxBid ? Number(maxBid) : null,
				// undefined (not null) so an edit that leaves both blank keeps the rule's
				// existing store — `exclude_unset` treats an omitted key as "unchanged".
				city: city || undefined,
				location_id: locationId || undefined,
				type: timing.type,
				// A one-off runs on its date, never on weekdays. Sending both lets the engine
				// see a repeat where the reader chose a single day.
				days: timing.type === "once" ? [] : timing.days,
				start_time: timing.start_time || null,
				stop_time: timing.end_time || null,
				start_date: timing.start_date || null,
				stop_date: timing.end_date || null,
				date: timing.type === "once" ? timing.date : null,
			};
			if (isEdit) {
				await updateBid.mutateAsync({ ruleId: editRow.id, body });
			} else {
				await createBid.mutateAsync(body);
			}
		}
	};

	return (
		// A dialog, not a takeover: the list stays visible (blurred) behind it, so it is
		// obvious this is a step on top of the page rather than a different place.
		<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-6 backdrop-blur-sm">
			{/* ⚠️ A FIXED height, not max-h. The three steps hold very different amounts, and
			    sizing to each one made the dialog jump on every Back and Next: the buttons moved
			    under the pointer and the page behind it re-centred. One height for all three is
			    steadier to use, and short steps centre their content (below) so the fixed box
			    never reads as empty. 82vh leaves the backdrop visible top and bottom, which is
			    what says this is a step on top of the page rather than a new page. */}
			<div className="flex h-[82vh] w-[62vw] min-w-216 max-w-304 flex-col overflow-hidden rounded-xl border border-border bg-card shadow-2xl">
				<header className="flex items-center justify-between border-b border-border px-6 py-4">
					<div className="flex items-center gap-3">
						<button
							type="button"
							aria-label="Close"
							onClick={onClose}
							className="rounded p-1 text-content-subtle hover:bg-muted hover:text-content"
						>
							<X size={20} />
						</button>
						<h2 className="font-display text-lg font-semibold tracking-tight text-content">
							{`${isEdit ? "Edit" : "Create"} ${kind === "campaign" ? "Campaign" : "Keyword"} Automation`}
						</h2>
						{/* Which marketplace this saves to — on create too, where it is the
						    navbar's choice and nothing else on the dialog says it. */}
						<ChannelBadge
							platform={isEdit ? editRow.platform : marketplace}
						/>
					</div>
					<div className="flex gap-8">
						{STEPS.map((label, i) => {
							const n = i + 1;
							const current = step === n;
							const canGo = stepReachable(n);
							return (
								<button
									key={label}
									type="button"
									aria-current={current ? "step" : undefined}
									disabled={!canGo}
									title={
										canGo ? undefined : stepBlockedReason(n)
									}
									onClick={() => canGo && setStep(n)}
									className={`flex items-center gap-2 rounded-md px-1 py-0.5 ${
										canGo && !current
											? "hover:bg-muted"
											: ""
									} ${canGo ? "" : "cursor-not-allowed"}`}
								>
									<span
										className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold ${
											current
												? "bg-content text-card"
												: step > n
													? "bg-muted text-content"
													: "bg-muted text-content-subtle"
										}`}
									>
										{n}
									</span>
									<span
										className={`text-sm font-medium ${current ? "text-content" : "text-content-subtle"}`}
									>
										{label}
									</span>
								</button>
							);
						})}
					</div>
					<div className="w-8" />
				</header>

				<div className="min-h-0 flex-1 overflow-auto px-6 py-5">
					{/* Top-aligned on every step. The dialog holds one height, so a step starts
				    where the last one started and a field does not move between Back and Next;
				    a short step simply leaves space below it. */}
					<div className="mx-auto max-w-6xl">
						{step === 1 && (
							<div className="flex flex-col gap-5">
								{/* WHAT to automate comes first, because it is the choice everything else hangs off,
							    and the table answering it is the tallest thing on the step. Once it is
							    answered the table collapses to a single line, so a tool that has finished
							    its job stops pushing the remaining fields below the fold. */}
								<div>
									{/* The label is rendered by the picker itself, on the same line as its search
								    box, so it costs no row of its own. */}
									<div>
										{isEdit ? (
											<div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-content-subtle">
												{editRow.campaign_name}{" "}
												<span className="text-content-subtle">
													(fixed)
												</span>
											</div>
										) : targetChosen && !pickerOpen ? (
											<div className="flex items-center justify-between gap-3 rounded-md border border-brand bg-muted px-3 py-2.5">
												<div className="min-w-0 truncate text-sm">
													<span className="mr-1.5 text-brand">
														✓
													</span>
													{kind === "keyword" ? (
														<>
															<span className="font-medium text-content">
																“{keyword}”
															</span>
															<span className="text-content-muted">
																{" "}
																in{" "}
																{campaignLabel}
															</span>
														</>
													) : (
														<span className="font-medium text-content">
															{campaignLabel}
														</span>
													)}
												</div>
												<Button
													variant="secondary"
													size="sm"
													onClick={() =>
														setPickerOpen(true)
													}
												>
													Change
												</Button>
											</div>
										) : kind === "keyword" ? (
											// Both pivots. Campaign × Keywords is the campaign-first path — pick a
											// campaign and the next window asks which of its keywords to bid on;
											// Keyword × Campaigns runs the same motion the other way round.
											<KeywordPicker
												campaignId={
													campaign?.campaign_id ??
													null
												}
												keyword={keyword}
												matchType={matchType}
												onChange={({
													campaign_id,
													campaign_name,
													keyword: kw,
													match_type,
												}) => {
													setCampaign({
														campaign_id,
														name: campaign_name,
													});
													setKeyword(kw);
													// Zepto's catalogue rows name their match
													// type; Blinkit's picker rows do not, and
													// the rule keeps the engine's default.
													setMatchType(
														match_type ?? "EXACT",
													);
													setPickerOpen(false);
												}}
											/>
										) : (
											<>
												{/* ⚠️ Reported HERE, not on the page. This
												    wizard is a full-screen overlay, so a
												    status line behind it is invisible — and
												    the campaign toggle that produces this
												    result lives inside the picker below.
												    The one message that most needs reading
												    ("this campaign is ON_HOLD, raise its
												    budget") was being written where nobody
												    could see it. */}
												{activationJobId && (
													<div className="mb-2">
														<JobLine
															jobId={
																activationJobId
															}
														/>
													</div>
												)}
												{/* A start/stop the queue refused to TAKE
												    (409: one is already running) — no job,
												    so the JobLine above has nothing to say. */}
												{activationError && (
													<p
														role="alert"
														className="mb-2 text-sm text-warning"
													>
														{activationError}
													</p>
												)}
												<CampaignPickerList
													selectedId={
														campaign?.campaign_id
													}
													onActivate={
														onActivateCampaign
													}
													onSelect={(c) => {
														setCampaign(c);
														setPickerOpen(false);
													}}
												/>
											</>
										)}
									</div>
								</div>

								{!loadingPicker && (
									<>
										{kind === "campaign" && (
											<Field
												label="Automation name"
												hint="Optional. It names this automation in the list and in the change log, so you can tell it apart from others on the same campaign."
											>
												<input
													type="text"
													value={name}
													onChange={(e) =>
														setName(e.target.value)
													}
													className={`w-full max-w-sm ${FIELD_INPUT}`}
												/>
											</Field>
										)}

										{kind === "campaign" && (
											<Field
												className="w-56"
												label={`Default daily budget (₹)${
													minDailyBudget != null
														? ` · min ₹${minDailyBudget.toLocaleString("en-IN")}`
														: ""
												}`}
												hint={`The campaign runs at this budget whenever none of your windows is open. It is the amount every window returns to when it ends.${
													campaign?.name
														? ` It applies to ${campaign.name}.`
														: ""
												}`}
												note={
													belowMinBudget
														? `${mpName} does not accept less than ₹${minDailyBudget.toLocaleString("en-IN")} a day.`
														: !campaign
															? null
															: currentBudget ==
																  null
																? `${mpName} has not reported what this campaign runs at today, so there is no way to check what this is changing it from.`
																: Number(
																			defaultBudget,
																	  ) ===
																	  currentBudget
																	? null
																	: `Today it runs at ₹${currentBudget.toLocaleString("en-IN")}. Saving this changes its everyday budget outside your windows too.`
												}
												noteTone={
													belowMinBudget ||
													(currentBudget != null &&
														Number(
															defaultBudget,
														) !== currentBudget)
														? "warn"
														: "subtle"
												}
											>
												<input
													type="number"
													value={defaultBudget}
													onChange={(e) =>
														setDefaultBudget(
															e.target.value,
														)
													}
													className={`w-full ${FIELD_INPUT}`}
												/>
											</Field>
										)}

										{/* Campaign automations only. A keyword automation sets its dates on
										    Create Actions, where the rest of its timing lives, and asking for
										    them again here left the same question in two places with nothing
										    to say which one the engine reads. */}
										{kind === "campaign" && (
											<div className="flex flex-wrap items-start gap-5">
												<Field
													label="Start date"
													hint="The first day this automation is allowed to act. Its windows do nothing before this."
													note={
														isEdit
															? "Cannot be changed once created"
															: null
													}
												>
													<DatePicker
														className="w-52"
														ariaLabel="Start date"
														disabled={isEdit}
														value={
															timing.start_date ??
															""
														}
														onChange={(d) =>
															setTiming({
																...timing,
																start_date: d,
															})
														}
													/>
												</Field>
												<Field
													label="End date"
													hint="The last day it acts. Leave it off and it keeps running until you stop it."
												>
													<DatePicker
														className="w-52"
														ariaLabel="End date"
														disabled={
															!timing.end_date
														}
														min={
															timing.start_date ||
															undefined
														}
														value={
															timing.end_date ??
															""
														}
														onChange={(d) =>
															setTiming({
																...timing,
																end_date: d,
															})
														}
													/>
												</Field>
												<label className="mt-7 flex cursor-pointer items-center gap-2 text-sm text-content">
													<input
														type="checkbox"
														checked={
															!timing.end_date
														}
														onChange={(e) =>
															setTiming({
																...timing,
																end_date: e
																	.target
																	.checked
																	? ""
																	: todayIso(),
															})
														}
													/>
													No end date
												</label>
											</div>
										)}
									</>
								)}
							</div>
						)}

						{step === 2 && (
							<div className="flex flex-col gap-4">
								{/* The numbers typed here only make sense against the ones set on step 1:
							    an increase of ₹2,500 means nothing without the default it moves from,
							    and a window is meaningless outside the automation's date range. */}
								<WizardContext
									kind={kind}
									campaignLabel={campaignLabel}
									campaignId={campaignId}
									keyword={keyword}
									matchType={matchType}
									name={name}
									defaultBudget={defaultBudget}
									timing={timing}
									onceDate={onceDate}
									onChange={() => setStep(1)}
								/>
								{/* A campaign automation is a LIST of actions, each with its own triggers —
							    the engine has always stored `rules[]`, the UI just never exposed more
							    than one. Every (action, trigger) pair becomes one budget rule. */}
								{kind === "campaign" ? (
									<ActionCards
										actions={actions}
										onChange={setActions}
										defaultBudget={defaultBudget}
										pauseAtEnd={stopAfterWindow}
										onPauseAtEnd={setPauseAtEnd}
									/>
								) : (
									<KeywordActionCard
										keyword={keyword}
										matchType={matchType}
										locationOptional={locationOptional}
										targetPosition={targetPosition}
										onTargetPosition={setTargetPosition}
										minBid={minBid}
										onMinBid={setMinBid}
										maxBid={maxBid}
										onMaxBid={setMaxBid}
										belowFloor={belowFloor}
										effectiveFloor={effectiveFloor}
										floor={floor}
										campaignFloor={campaignFloor}
										scrapedAt={ctx?.scraped_at}
										city={city}
										onCity={setCity}
										cityOptions={cityOptions}
										citiesLoading={Boolean(
											campaignId && ctxPending,
										)}
										regionType={ctx?.region_type ?? null}
										singleCity={singleCity}
										hasLocation={hasLocation}
										existingLocationName={existingLocation}
										isEdit={isEdit}
										timing={timing}
										onTiming={setTiming}
									/>
								)}
							</div>
						)}

						{step === 3 && (
							<WizardSummary
								kind={kind}
								campaignLabel={campaignLabel}
								campaignId={campaignId}
								keyword={keyword}
								matchType={matchType}
								name={name}
								defaultBudget={defaultBudget}
								actions={actions}
								stopAfterWindow={stopAfterWindow}
								timing={timing}
								targetPosition={targetPosition}
								minBid={minBid}
								maxBid={maxBid}
								city={city}
								locationName={existingLocation}
								effectiveFloor={effectiveFloor}
								isEdit={isEdit}
								currentBudget={currentBudget}
								writeMode={writeMode}
								onActionBudgetChange={(id, budget) =>
									setActions(
										actions.map((a) =>
											a.id === id ? { ...a, budget } : a,
										),
									)
								}
							/>
						)}
					</div>
				</div>

				<footer className="border-t border-border px-6 py-4">
					<div className="mx-auto flex max-w-6xl items-center justify-between">
						<Button
							variant="secondary"
							onClick={() =>
								step === 1 ? onClose() : setStep(step - 1)
							}
						>
							{step === 1 ? "Cancel" : "Back"}
						</Button>
						{step < 3 ? (
							/* Continue is LIVE even when the step is unsatisfied. A disabled button
							   cannot be pressed, so it can never explain itself; pressing this one
							   either moves on or names the one thing still missing. The message
							   sits beside the button rather than in a tooltip, which is only found
							   by someone already hunting. */
							<div className="flex items-center gap-3">
								{triedToAdvance && !canAdvanceNow && (
									<span
										role="alert"
										className="text-sm text-danger"
									>
										{missingOnThisStep()}
									</span>
								)}
								<Button
									variant="brand"
									className="px-8"
									onClick={() => {
										if (!canAdvanceNow)
											return setTriedToAdvance(true);
										setTriedToAdvance(false);
										setStep(step + 1);
									}}
								>
									Continue
								</Button>
							</div>
						) : (
							<div className="flex items-center gap-3">
								{saveError && (
									<span
										role="alert"
										className="max-w-xl text-sm text-danger"
									>
										{saveError}
									</span>
								)}
								<Button
									variant="brand"
									className="px-8"
									disabled={saving}
									onClick={submit}
								>
									{saving
										? "Saving…"
										: isEdit
											? "Save Changes"
											: "Create Automation"}
								</Button>
							</div>
						)}
					</div>
				</footer>
			</div>
		</div>
	);
};
