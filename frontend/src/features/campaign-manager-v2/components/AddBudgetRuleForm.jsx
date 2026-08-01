import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { useAddBudgetRule, useUpdateBudgetRule } from "../hooks";
import { TimingFields, emptyTiming, timingFromRule, timingPayload } from "./TimingFields";

const FIELD =
	"rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-content focus:border-primary focus:outline-none";

/**
 * Add OR edit a budget window ("during this window, use ₹X"). Pass `editing` (a rule) to
 * edit it in place (PATCH); otherwise it adds a new rule to `scheduleId`.
 */
export const AddBudgetRuleForm = ({ scheduleId, editing = null, onDone }) => {
	const isEdit = Boolean(editing);
	const [budget, setBudget] = useState(editing?.budget != null ? String(editing.budget) : "");
	const [timing, setTiming] = useState(isEdit ? timingFromRule(editing) : emptyTiming());
	const add = useAddBudgetRule();
	const update = useUpdateBudgetRule();
	const mutation = isEdit ? update : add;

	const submit = (e) => {
		e.preventDefault();
		if (!budget) return;
		const body = { budget: Number(budget), ...timingPayload(timing) };
		if (isEdit) {
			update.mutate({ ruleId: editing.id, body }, { onSuccess: () => onDone?.() });
		} else {
			add.mutate(
				{ scheduleId, body },
				{
					onSuccess: () => {
						setBudget("");
						setTiming(emptyTiming());
						onDone?.();
					},
				},
			);
		}
	};

	return (
		<form onSubmit={submit} className="space-y-3 rounded-lg border border-border bg-surface p-3">
			<label className="flex flex-col gap-1">
				<span className="text-xs font-medium text-content-muted">Budget during this window (₹)</span>
				<input
					type="number"
					min="1"
					value={budget}
					onChange={(e) => setBudget(e.target.value)}
					placeholder="e.g. 1500"
					className={`${FIELD} w-40`}
				/>
			</label>
			<TimingFields value={timing} onChange={setTiming} />
			{mutation.isError && (
				<p className="text-xs text-danger">
					{mutation.error?.message ?? `Failed to ${isEdit ? "save" : "add"} window`}
				</p>
			)}
			<div className="flex gap-2">
				<Button type="submit" size="sm" disabled={mutation.isPending || !budget}>
					{mutation.isPending ? "Saving…" : isEdit ? "Save window" : "Add window"}
				</Button>
				<Button type="button" size="sm" variant="ghost" onClick={onDone}>
					Cancel
				</Button>
			</div>
		</form>
	);
};
