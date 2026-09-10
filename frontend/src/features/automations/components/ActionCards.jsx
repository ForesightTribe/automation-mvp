import { useState } from "react";
import {
	ChevronUp,
	ChevronDown,
	Copy,
	Trash2,
	Plus,
	AlertTriangle,
} from "lucide-react";
import { ACTIONS, SelectActionModal } from "./SelectActionModal";
import { formatCurrency } from "../../../lib/format";
import { TriggerRow, emptyTrigger, uid } from "./TriggerRow";

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
const ActionHeadline = ({ action, onBudget }) => {
	const meta = ACTIONS.find((x) => x.id === action.type);
	if (!meta?.needsBudget) return <span>{describeAction(action)}</span>;
	return (
		<span className="flex flex-wrap items-baseline gap-1.5">
			{meta.label} to
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
			when
		</span>
	);
};

/** Says when the amount contradicts the action, or is missing. Same rule as the picker. */
export const budgetProblem = (action, base) => {
	const meta = ACTIONS.find((x) => x.id === action.type);
	if (!meta?.needsBudget) return null;
	if (action.budget == null || action.budget <= 0)
		return "Set an amount for this action.";
	if (!base) return null;
	if (action.type === "increase" && action.budget <= base)
		return `${formatCurrency(action.budget)} is not above the default of ${formatCurrency(base)}, so this window would lower the budget instead.`;
	if (action.type === "decrease" && action.budget >= base)
		return `${formatCurrency(action.budget)} is not below the default of ${formatCurrency(base)}, so this window would raise the budget instead.`;
	return null;
};

/**
 * Step 2 for a campaign automation: a list of actions, each with its own triggers.
 *
 * A schedule holds `rules[]`, so one automation can carry several windows. Every
 * (action, trigger) pair becomes one budget rule: "Increase to ₹1,500 at 19:00 on Mon and
 * Fri" is two rules sharing a budget.
 */
export const ActionCards = ({ actions, onChange, defaultBudget }) => {
	const [adding, setAdding] = useState(false);
	const [collapsed, setCollapsed] = useState({});

	const update = (id, patch) =>
		onChange(actions.map((a) => (a.id === id ? { ...a, ...patch } : a)));

	// The dialog collects the whole action, so a card only ever appears finished. It stays
	// editable here afterwards, which is the point of showing it as a card at all.
	const addAction = (action) => {
		onChange([...actions, { id: uid(), ...action }]);
		setAdding(false);
	};

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
			{actions.length === 0 && (
				<p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-content-subtle">
					No actions yet. Add one to say what this automation should
					do, and when.
				</p>
			)}

			{actions.map((a) => {
				const isOpen = !collapsed[a.id];
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

						{isOpen && (
							<div className="flex flex-col gap-2 px-4 pb-4">
								{a.triggers.map((t) => (
									<TriggerRow
										key={t.id}
										value={t}
										removable={a.triggers.length > 1}
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

			<button
				type="button"
				onClick={() => setAdding(true)}
				className="flex w-fit items-center gap-2 rounded-lg border border-brand bg-card px-4 py-2.5 text-sm font-medium text-brand transition-colors hover:bg-brand hover:text-on-brand hover:shadow-sm active:translate-y-px"
			>
				<Plus size={16} /> Add Action
			</button>

			{adding && (
				<SelectActionModal
					defaultBudget={defaultBudget}
					onAdd={addAction}
					onClose={() => setAdding(false)}
				/>
			)}
		</div>
	);
};
