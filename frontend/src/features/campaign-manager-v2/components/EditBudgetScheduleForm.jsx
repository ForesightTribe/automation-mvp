import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { useUpdateBudgetSchedule } from "../hooks";

const FIELD =
	"rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-content focus:border-primary focus:outline-none";
const LABEL = "text-xs font-medium text-content-muted";

/** Edit a budget automation's own fields (label + everyday budget). Windows are edited separately. */
export const EditBudgetScheduleForm = ({ schedule, onDone }) => {
	const [name, setName] = useState(schedule.name ?? "");
	const [defaultBudget, setDefaultBudget] = useState(String(schedule.default_budget));
	const mutation = useUpdateBudgetSchedule();

	const submit = (e) => {
		e.preventDefault();
		if (!defaultBudget) return;
		mutation.mutate(
			{ scheduleId: schedule.id, body: { name: name || null, default_budget: Number(defaultBudget) } },
			{ onSuccess: () => onDone?.() },
		);
	};

	return (
		<form onSubmit={submit} className="space-y-3 rounded-lg border border-border bg-surface p-3">
			<label className="flex flex-col gap-1">
				<span className={LABEL}>Label</span>
				<input value={name} onChange={(e) => setName(e.target.value)} placeholder="Weekend nights" className={FIELD} />
			</label>
			<label className="flex flex-col gap-1">
				<span className={LABEL}>Everyday budget (₹)</span>
				<input
					type="number"
					min="1"
					value={defaultBudget}
					onChange={(e) => setDefaultBudget(e.target.value)}
					className={`${FIELD} w-40`}
				/>
			</label>
			{mutation.isError && (
				<p className="text-xs text-danger">{mutation.error?.message ?? "Failed to save"}</p>
			)}
			<div className="flex gap-2">
				<Button type="submit" size="sm" disabled={mutation.isPending || !defaultBudget}>
					{mutation.isPending ? "Saving…" : "Save"}
				</Button>
				<Button type="button" size="sm" variant="ghost" onClick={onDone}>
					Cancel
				</Button>
			</div>
		</form>
	);
};
