import { useState } from "react";
import {
	ChevronUp,
	ChevronDown,
	Copy,
	Trash2,
	Plus,
	AlertTriangle,
} from "lucide-react";
import { TrendingUp, TrendingDown, Play, Pause } from "lucide-react";
import { formatCurrency } from "../../../lib/format";
import { TriggerRow, emptyTrigger, uid } from "./TriggerRow";

/**
 * Everything an automation can do to a campaign.
 *
 * Offered two ways, for two different moments. Adding an action opens an inline panel
 * INSIDE step 2 whose rows each carry a one-line `blurb`, because the first choice is where
 * the reader needs to learn what each one does. Once chosen, the card's header is a plain
 * dropdown of the same options: swapping is a one-click correction by someone who already
 * knows the list, and reopening the panel for it would be ceremony.
 *
 * `verb` is the row's own wording, written as an instruction to the campaign ("Raise
 * budget to") rather than as a feature name ("Increase Budget"), because the card reads as
 * a sentence: raise budget to ₹1,500, on these days, from this time.
 *
 * `form` names the card body an action needs. Every action today is time-based and uses
 * the "window" body (days and times). A performance template would declare a different
 * form and the card would render its body instead; the chooser needs no change for it.
 */
export const ACTIONS = [
	{
		id: "increase",
		group: "Budget",
		label: "Increase Budget",
		verb: "Raise budget to",
		form: "window",
		icon: TrendingUp,
		needsBudget: true,
		blurb: "Raise the campaign's budget for the window, then return to the default.",
	},
	{
		id: "decrease",
		group: "Budget",
		label: "Decrease Budget",
		verb: "Lower budget to",
		form: "window",
		icon: TrendingDown,
		needsBudget: true,
		blurb: "Lower the campaign's budget for the window, then return to the default.",
	},
	{
		id: "start",
		group: "Status",
		label: "Start Campaign",
		verb: "Start campaign",
		form: "window",
		icon: Play,
		needsBudget: false,
		blurb: "Run the campaign during the window at its default budget. A stopped campaign is started; one already running is left alone.",
	},
	{
		id: "stop",
		group: "Status",
		label: "Pause Campaign",
		verb: "Pause campaign",
		form: "window",
		icon: Pause,
		needsBudget: false,
		blurb: "Pause the campaign so it stops spending, at a time you choose. Give it a window ending when the campaign should go quiet.",
	},
];

/** "Increase Budget By ₹1,500 When" — the card's own headline. */
export const describeAction = (a) => {
	const meta = ACTIONS.find((x) => x.id === a.type);
	if (!meta) return "Action";
	return a.budget != null
		? `${meta.label} to ${formatCurrency(a.budget)} when`
		: `${meta.label} when`;
};

/**
 * The card's headline, with the amount typed straight into it.
 *
 * The amount is the number most likely to be adjusted while the schedule is being read, so
 * it is edited where it is read. Confining it to the Select Action modal would make changing
 * ₹2,500 to ₹3,000 a matter of deleting the action and rebuilding its triggers.
 */
const ActionHeadline = ({ action, onType, onBudget }) => {
	const meta = ACTIONS.find((x) => x.id === action.type);
	return (
		<span className="flex flex-wrap items-baseline gap-1.5">
			{/* Swapped in place: picking the wrong action costs one click to correct rather
			    than deleting the card and rebuilding its windows. */}
			<select
				aria-label="What this action does"
				value={action.type}
				onChange={(e) => onType(e.target.value)}
				className="cursor-pointer rounded-md border border-border bg-card px-2 py-1 text-base font-semibold text-content transition-colors hover:border-content-subtle focus:border-brand focus:outline-none"
			>
				{ACTIONS.map((a) => (
					<option key={a.id} value={a.id}>
						{a.verb}
					</option>
				))}
			</select>
			{meta?.needsBudget && (
				<span className="inline-flex items-baseline rounded-md border border-border bg-card focus-within:border-brand">
					<span className="pl-2 text-sm font-normal text-content-muted">
						₹
					</span>
					<input
						type="number"
						aria-label={`${meta.label} amount`}
						value={action.budget ?? ""}
						onChange={(e) =>
							onBudget(
								e.target.value === ""
									? null
									: Number(e.target.value),
							)
						}
						className="w-24 bg-transparent px-1.5 py-1 text-base font-semibold text-content tabular-nums focus:outline-none"
					/>
				</span>
			)}
			<span>when</span>
		</span>
	);
};

/**
 * The chooser: every action, grouped, each with a line saying what it does.
 *
 * Rendered in the flow of step 2 rather than over it, so the cards it adds to stay in
 * view. No search box: the list is short enough to read whole, and a search field above
 * four rows reads as clutter. It is one line to add if the catalogue ever outgrows a glance.
 */
const ActionChooser = ({ title, onPick, onCancel }) => {
	const groups = [...new Set(ACTIONS.map((a) => a.group))];
	return (
		<div className="rounded-lg border border-border bg-card">
			<div className="flex items-center justify-between border-b border-border px-4 py-2.5">
				<span className="text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
					{title}
				</span>
				<button
					type="button"
					onClick={onCancel}
					className="cursor-pointer text-xs text-content-muted transition-colors hover:text-content"
				>
					Cancel
				</button>
			</div>
			<div className="grid gap-x-6 gap-y-1 p-3 sm:grid-cols-2">
				{groups.map((g) => (
					<div key={g}>
						<p className="px-2 pt-1 pb-1.5 text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
							{g}
						</p>
						{ACTIONS.filter((a) => a.group === g).map((a) => {
							const Icon = a.icon;
							return (
								<button
									key={a.id}
									type="button"
									onClick={() => onPick(a.id)}
									className="group/opt flex w-full cursor-pointer items-start gap-3 rounded-md px-2 py-2 text-left transition-colors hover:bg-brand hover:text-on-brand"
								>
									<span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-brand group-hover/opt:bg-on-brand/20 group-hover/opt:text-on-brand">
										<Icon size={14} />
									</span>
									<span className="min-w-0">
										<span className="block text-sm font-semibold">
											{a.verb}
										</span>
										<span className="block text-xs text-content-muted group-hover/opt:text-on-brand/85">
											{a.blurb}
										</span>
									</span>
								</button>
							);
						})}
					</div>
				))}
			</div>
		</div>
	);
};

/** Says when the amount contradicts the action, or is missing. Same rule as the picker. */
export const budgetProblem = (action, base) => {
	const meta = ACTIONS.find((x) => x.id === action.type);
	if (!meta?.needsBudget) return null;
	if (action.budget == null || action.budget <= 0)
		return "Set an amount for this action.";
	if (!base) return null;
	// ⚠️ Equal is its own case, checked before the two directional ones. An amount equal to
	// the default neither raises nor lowers the budget, so it belongs under neither of them.
	if (action.budget === base)
		return `${formatCurrency(action.budget)} is the same as the default, so this window would change nothing.`;
	if (action.type === "increase" && action.budget < base)
		return `${formatCurrency(action.budget)} is below the default of ${formatCurrency(base)}, so this window would lower the budget instead of raising it.`;
	if (action.type === "decrease" && action.budget > base)
		return `${formatCurrency(action.budget)} is above the default of ${formatCurrency(base)}, so this window would raise the budget instead of lowering it.`;
	return null;
};

/**
 * Step 2 for a campaign automation: a list of actions, each with its own triggers.
 *
 * A schedule holds `rules[]`, so one automation can carry several windows. Every
 * (action, trigger) pair becomes one budget rule: "Increase to ₹1,500 at 19:00 on Mon and
 * Fri" is two rules sharing a budget.
 */
export const ActionCards = ({
	actions,
	onChange,
	defaultBudget,
	pauseAtEnd,
	onPauseAtEnd,
}) => {
	/**
	 * A new action starts at the default budget, on no days and with no times.
	 * Prefilling days or hours would be guessing at the operator's intent and, worse, would
	 * read as a decision already made; the empty fields are refused on save, so nothing can
	 * be created half-specified.
	 */
	const addOfType = (type) =>
		onChange([
			...actions,
			{
				id: uid(),
				type,
				budget: Number(defaultBudget) || null,
				triggers: [emptyTrigger()],
			},
		]);
	const [collapsed, setCollapsed] = useState({});
	const [adding, setAdding] = useState(false);

	const update = (id, patch) =>
		onChange(actions.map((a) => (a.id === id ? { ...a, ...patch } : a)));

	const duplicate = (a) =>
		onChange([
			...actions,
			{
				...a,
				id: uid(),
				triggers: a.triggers.map((t) => ({ ...t, id: uid() })),
			},
		]);

	return (
		<div className="flex flex-col gap-4">
			{actions.map((a) => {
				const isOpen = !collapsed[a.id];
				const form =
					ACTIONS.find((x) => x.id === a.type)?.form ?? "window";
				return (
					<div
						key={a.id}
						className="rounded-lg border border-border bg-card"
					>
						<div className="flex items-center gap-2 px-4 py-3">
							<span className="flex h-7 w-7 items-center justify-center rounded-full bg-muted text-brand">
								{(() => {
									const Icon = ACTIONS.find(
										(x) => x.id === a.type,
									)?.icon;
									return Icon ? <Icon size={14} /> : null;
								})()}
							</span>
							<div className="font-display text-base font-semibold tracking-tight text-content">
								<ActionHeadline
									action={a}
									onType={(type) => update(a.id, { type })}
									onBudget={(budget) =>
										update(a.id, { budget })
									}
								/>
							</div>
							<div className="ml-auto flex items-center gap-1">
								<>
									<button
										type="button"
										aria-label={
											isOpen ? "Collapse" : "Expand"
										}
										onClick={() =>
											setCollapsed({
												...collapsed,
												[a.id]: isOpen,
											})
										}
										className="rounded p-1.5 text-content-subtle hover:bg-muted hover:text-content"
									>
										{isOpen ? (
											<ChevronUp size={15} />
										) : (
											<ChevronDown size={15} />
										)}
									</button>
									<button
										type="button"
										aria-label="Duplicate"
										onClick={() => duplicate(a)}
										className="rounded p-1.5 text-content-subtle hover:bg-muted hover:text-content"
									>
										<Copy size={15} />
									</button>
								</>
								<button
									type="button"
									aria-label="Delete action"
									onClick={() =>
										onChange(
											actions.filter(
												(x) => x.id !== a.id,
											),
										)
									}
									className="rounded p-1.5 text-content-subtle hover:bg-muted hover:text-danger"
								>
									<Trash2 size={15} />
								</button>
							</div>
						</div>

						{budgetProblem(a, Number(defaultBudget) || 0) && (
							<p className="flex items-start gap-1.5 px-4 pb-2 text-[11px] text-warning">
								<AlertTriangle
									size={12}
									className="mt-0.5 shrink-0"
								/>
								<span>
									{budgetProblem(
										a,
										Number(defaultBudget) || 0,
									)}
								</span>
							</p>
						)}

						{/* The body is chosen by the action's `form`. Only "window" exists today;
						    a performance template would add its own branch here and nothing above
						    this line would need to know. */}
						{isOpen && form === "window" && (
							<div className="flex flex-col gap-2 px-4 pb-4">
								{a.triggers.map((t) => (
									<TriggerRow
										key={t.id}
										value={t}
										removable={a.triggers.length > 1}
										pauseAtEnd={pauseAtEnd}
										onPauseAtEnd={onPauseAtEnd}
										// Every window on the automation, not just this
										// card's: the flag they toggle is automation-wide.
										windowCount={actions.reduce(
											(n, x) => n + x.triggers.length,
											0,
										)}
										onChange={(next) =>
											update(a.id, {
												triggers: a.triggers.map((x) =>
													x.id === t.id ? next : x,
												),
											})
										}
										onRemove={() =>
											update(a.id, {
												triggers: a.triggers.filter(
													(x) => x.id !== t.id,
												),
											})
										}
									/>
								))}
								{/* One card can hold several windows at the SAME budget: "₹750 on Friday
								    evenings and again on Sunday afternoons" is one action, two windows.
								    Each becomes its own rule. It used to say "Add Trigger", which is the
								    engine's word for it and told a reader nothing. */}
								<button
									type="button"
									onClick={() =>
										update(a.id, {
											triggers: [
												...a.triggers,
												emptyTrigger(),
											],
										})
									}
									title="Run this same change at another time"
									className="flex w-fit items-center gap-1.5 rounded-md px-2 py-1.5 text-sm font-medium text-brand hover:bg-muted"
								>
									<Plus size={14} /> Add another time window
								</button>
								{a.triggers.length > 1 && (
									<p className="text-xs text-content-subtle">
										{a.triggers.length} windows, each
										running this same change.
									</p>
								)}
							</div>
						)}
					</div>
				);
			})}

			{/* One control, not an empty state beside a button. With nothing added yet the
			    row IS the invitation and says what an action is for; once cards exist it
			    shortens to "Add action", because by then the reader has seen one.

			    "Action", not "budget window": a card can raise or lower a budget, or start
			    or pause the campaign, and only two of those four are about budget.

			    The chooser opens IN PLACE of this row, so the cards it adds to stay exactly
			    where they were. */}
			{adding ? (
				<ActionChooser
					title="Add action"
					onPick={(type) => {
						addOfType(type);
						setAdding(false);
					}}
					onCancel={() => setAdding(false)}
				/>
			) : (
				<button
					type="button"
					onClick={() => setAdding(true)}
					className={`flex w-full cursor-pointer items-center gap-2 rounded-lg border border-dashed border-content-subtle bg-transparent font-medium text-brand transition-colors hover:bg-brand-soft/40 ${
						actions.length === 0
							? "flex-col justify-center px-4 py-8 text-center"
							: "px-4 py-3.5 text-sm"
					}`}
				>
					{actions.length === 0 ? (
						<>
							<span className="flex items-center gap-2 text-sm">
								<Plus size={16} /> Add action
							</span>
							<span className="text-xs font-normal text-content-subtle">
								Say what this automation should do, and when.
							</span>
						</>
					) : (
						<>
							<Plus size={16} /> Add action
						</>
					)}
				</button>
			)}
		</div>
	);
};
