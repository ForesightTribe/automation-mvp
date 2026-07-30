import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { useAddBudgetRule } from "../hooks";
import { TimingFields, emptyTiming, timingPayload } from "./TimingFields";

const FIELD =
	"rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-content focus:border-primary focus:outline-none";

/** Add a budget rule (a "during this window, use ₹X" override) to a schedule. */
export const AddBudgetRuleForm = ({ scheduleId, onDone }) => {
	const [budget, setBudget] = useState("");
	const [timing, setTiming] = useState(emptyTiming());
	const mutation = useAddBudgetRule();

	const submit = (e) => {
		e.preventDefault();
		if (!budget) return;
		mutation.mutate(
			{ scheduleId, body: { budget: Number(budget), ...timingPayload(timing) } },
			{
				onSuccess: () => {
					setBudget("");
					setTiming(emptyTiming());
					onDone?.();
				},
			},
		);
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
				<p className="text-xs text-danger">{mutation.error?.message ?? "Failed to add rule"}</p>
			)}
			<div className="flex gap-2">
				<Button type="submit" size="sm" disabled={mutation.isPending || !budget}>
					{mutation.isPending ? "Adding…" : "Add rule"}
				</Button>
				<Button type="button" size="sm" variant="ghost" onClick={onDone}>
					Cancel
				</Button>
			</div>
		</form>
	);
};
