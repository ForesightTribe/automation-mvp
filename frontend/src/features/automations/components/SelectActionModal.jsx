import { useState } from "react";
import {
	TrendingUp,
	TrendingDown,
	Play,
	Pause,
	ChevronRight,
	Plus,
	Info,
} from "lucide-react";
import { TriggerRow, emptyTrigger } from "./TriggerRow";
import { HoverHint } from "../../../components/ui/HoverHint";
import { formatCurrency } from "../../../lib/format";
import { Button } from "../../../components/ui/Button";

/**
 * "Select Action" — the catalogue of things an automation can do to a campaign.
 *
 * Four entries, all of which the engine genuinely performs:
 *   increase / decrease — a budget rule for the window (`BudgetRuleIn.budget`)
 *   start              — implicit in having a window at all: while a rule is active the
 *                        scheduler returns state "running" and starting is UNCONDITIONAL
 *                        (budget.py, AD7), so a window IS a scheduled start
 *   stop               — `stop_after_window` on the schedule: when the window ends the
 *                        budget returns to default and the campaign is paused
 *
 * The design's fifth entry, "Prevent Out of Budget", is deliberately absent: nothing in
 * the engine implements it. ON_HOLD (budget exhausted) is a state the engine *reports* and
 * can write through, not a guard it can arm — so drawing the control would promise
 * behaviour that would never happen.
 */
export const ACTIONS = [
	{
		id: "increase",
		group: "Budget",
		label: "Increase Budget",
		icon: TrendingUp,
		needsBudget: true,
		blurb: "Raise the campaign's budget for the window, then return to the default.",
	},
	{
		id: "decrease",
		group: "Budget",
		label: "Decrease Budget",
		icon: TrendingDown,
		needsBudget: true,
		blurb: "Lower the campaign's budget for the window, then return to the default.",
	},
	{
		id: "start",
		group: "Status",
		label: "Start Campaign",
		icon: Play,
		needsBudget: false,
		blurb: "Run the campaign during the window at its default budget. A stopped campaign is started; one already running is left alone.",
	},
	{
		id: "stop",
		group: "Status",
		label: "Pause Campaign",
		icon: Pause,
		needsBudget: false,
		blurb: "Pause the campaign so it stops spending, at a time you choose. Give it a window ending when the campaign should go quiet.",
	},
];

const GROUPS = ["Budget", "Status"];

/**
 * "Select Action" — the catalogue of things an automation can do to a campaign.
 *
 * ⚠️ It collects the WHOLE action: what should happen, how much, and when. Amount and
 * timing are one decision, so they are made in one place rather than split between this
 * modal and the card list, where a half-specified card would stand in for a finished one.
 * The card that appears afterwards is a finished action, and edits the same fields.
 */
export const SelectActionModal = ({ defaultBudget, onAdd, onClose }) => {
	const [picked, setPicked] = useState(null);
	const [amount, setAmount] = useState("");
	const [triggers, setTriggers] = useState([emptyTrigger()]);

	const action = ACTIONS.find((a) => a.id === picked) ?? null;
	const base = Number(defaultBudget) || 0;
	const value = Number(amount || 0);

	// "Increase" that lowers the budget is almost certainly a mis-click, and the engine would
	// store it happily. Warn rather than block: the default budget is editable too, and
	// changing it flips the comparison.
	const wrongDirection =
		action?.needsBudget &&
		amount !== "" &&
		base > 0 &&
		(picked === "increase" ? value <= base : value >= base);

	const valid = Boolean(action) && (!action?.needsBudget || value > 0);

	const submit = () =>
		onAdd({
			type: picked,
			budget: action.needsBudget ? value : null,
			triggers,
		});

	return (
		<div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-6">
			<div className="flex h-[80vh] max-h-[80vh] w-full max-w-5xl flex-col rounded-xl border border-border bg-card shadow-2xl">
				<header className="flex items-center justify-between border-b border-border px-5 py-4">
					<h3 className="font-display text-base font-semibold text-content">
						Select Action
					</h3>
					<button
						type="button"
						aria-label="Close"
						onClick={onClose}
						className="rounded p-1 text-content-subtle hover:bg-muted hover:text-content"
					>
						✕
					</button>
				</header>

				<div className="flex flex-1 overflow-hidden">
					<div className="w-72 shrink-0 overflow-auto border-r border-border bg-surface p-3">
						{GROUPS.map((g) => (
							<div key={g} className="mb-3">
								<p className="mb-1 px-2 text-[11px] font-semibold tracking-wide text-content-subtle uppercase">
									{g}
								</p>
								{ACTIONS.filter((a) => a.group === g).map(
									(a) => {
										const Icon = a.icon;
										const on = picked === a.id;
										return (
											<button
												key={a.id}
												type="button"
												onClick={() => {
													setPicked(a.id);
													setAmount("");
												}}
												// Selected reads as a filled brand row rather than brand-coloured text on a
												// grey fill: in a form carrying validation copy, coloured text on grey reads
												// as a row reporting an error rather than the row that is chosen.
												className={`flex w-full items-center justify-between rounded-md px-2.5 py-2.5 text-left text-sm transition-colors ${
													on
														? "bg-brand font-medium text-on-brand"
														: "text-content hover:bg-muted"
												}`}
											>
												<span className="flex items-center gap-2">
													<Icon size={14} />
													{a.label}
												</span>
												<ChevronRight
													size={14}
													className={
														on
															? "text-on-brand/70"
															: "text-content-subtle"
													}
												/>
											</button>
										);
									},
								)}
							</div>
						))}
					</div>

					<div className="flex-1 overflow-auto p-6">
						{!action ? (
							<div className="flex h-full flex-col items-center justify-center text-center">
								<p className="text-sm font-medium text-content">
									Select an action
								</p>
								<p className="mt-1 text-sm text-content-subtle">
									Choose an action from the list to configure
									it
								</p>
							</div>
						) : (
							<div className="flex flex-col gap-5">
								<div>
									<p className="text-sm font-medium text-content">
										{action.label}
									</p>
									<p className="mt-1 text-xs leading-relaxed text-content-muted">
										{action.blurb}
									</p>
								</div>

								{action.needsBudget && (
									<div>
										{/* ⚠️ The WHOLE label is the hover target, not the 15px icon inside it.
										    Hovering the words and getting nothing reads as "this must need a
										    click", which is the one thing a hint should never require.
										    The wording names the actual numbers rather than describing the
										    mechanism: "what the campaign runs at while this window is open" is
										    true and unreadable. */}
										<HoverHint
											label={
												value > 0
													? `The campaign runs at ${formatCurrency(value)} during the window you define. Outside that window, the default of ${base ? formatCurrency(base) : "the campaign's budget"} applies.`
													: `The campaign runs at this budget during the window you define. Outside that window, the default of ${base ? formatCurrency(base) : "the campaign's budget"} applies.`
											}
										>
											<span className="mb-1 flex cursor-help items-center gap-1.5 text-xs text-content-muted">
												Budget during the window (₹)
												<Info
													size={14}
													className="text-content-subtle"
												/>
											</span>
										</HoverHint>
										<input
											type="number"
											autoFocus
											value={amount}
											aria-invalid={wrongDirection}
											onChange={(e) =>
												setAmount(e.target.value)
											}
											// Neutral on focus. A brand-red ring on a number field reads as a
											// rejection, and this one is right far more often than it is wrong.
											className="w-44 rounded-md border border-border bg-card px-3 py-2 text-base text-content transition-colors focus:border-content focus:outline-none aria-[invalid=true]:border-warning"
										/>
										{wrongDirection && (
											<p className="mt-1 text-xs text-warning">
												That is{" "}
												{picked === "increase"
													? "not above"
													: "not below"}{" "}
												the default of ₹{base}. Check
												whether you meant{" "}
												{picked === "increase"
													? "Decrease"
													: "Increase"}
												.
											</p>
										)}
									</div>
								)}

								{/* One question at a time. The timing appears only once the amount is in,
								    so the dialog opens as a single decision rather than a full form, and the
								    two halves are still made together in one place. */}
								{!action.needsBudget || value > 0 ? (
									<div>
										<p className="mb-2 text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
											When it runs
										</p>
										<div className="flex flex-col gap-2">
											{triggers.map((t) => (
												<TriggerRow
													key={t.id}
													value={t}
													removable={
														triggers.length > 1
													}
													onChange={(next) =>
														setTriggers(
															triggers.map((x) =>
																x.id === t.id
																	? next
																	: x,
															),
														)
													}
													onRemove={() =>
														setTriggers(
															triggers.filter(
																(x) =>
																	x.id !==
																	t.id,
															),
														)
													}
												/>
											))}
											<button
												type="button"
												onClick={() =>
													setTriggers([
														...triggers,
														emptyTrigger(),
													])
												}
												className="flex w-fit items-center gap-1.5 rounded-md px-2 py-1.5 text-sm font-medium text-brand hover:bg-muted"
											>
												<Plus size={14} /> Add another
												time window
											</button>
										</div>
									</div>
								) : null}
							</div>
						)}
					</div>
				</div>

				<footer className="flex justify-end gap-2 border-t border-border px-5 py-4">
					<Button variant="secondary" size="sm" onClick={onClose}>
						Cancel
					</Button>
					<Button
						variant="brand"
						size="sm"
						disabled={!valid}
						onClick={submit}
					>
						Add action
					</Button>
				</footer>
			</div>
		</div>
	);
};
