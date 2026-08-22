import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { useUpdateBudgetSchedule } from "../hooks";

const FIELD =
	"rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-content focus:border-primary focus:outline-none";
const LABEL = "text-xs font-medium text-content-muted";

/** Edit a budget automation's own fields (label, default budget, and whether the campaign
 * is stopped when a window ends). Windows themselves are edited separately. */
export const EditBudgetScheduleForm = ({ schedule, onDone }) => {
	const [name, setName] = useState(schedule.name ?? "");
	const [defaultBudget, setDefaultBudget] = useState(
		String(schedule.default_budget),
	);
	const [stopAfterWindow, setStopAfterWindow] = useState(
		Boolean(schedule.stop_after_window),
	);
	const mutation = useUpdateBudgetSchedule();

	const submit = (e) => {
		e.preventDefault();
		if (!defaultBudget) return;
		mutation.mutate(
			{
				scheduleId: schedule.id,
				body: {
					name: name || null,
					default_budget: Number(defaultBudget),
					stop_after_window: stopAfterWindow,
				},
			},
			{ onSuccess: () => onDone?.() },
		);
	};

	return (
		<form
			onSubmit={submit}
			className="space-y-3 rounded-lg border border-border bg-surface p-3"
		>
			<label className="flex flex-col gap-1">
				<span className={LABEL}>Label</span>
				<input
					value={name}
					onChange={(e) => setName(e.target.value)}
					placeholder="Weekend nights"
					className={FIELD}
				/>
			</label>
			<label className="flex flex-col gap-1">
				<span className={LABEL}>Default budget (₹)</span>
				<input
					type="number"
					min="1"
					value={defaultBudget}
					onChange={(e) => setDefaultBudget(e.target.value)}
					className={`${FIELD} w-40`}
				/>
			</label>
			<label className="flex cursor-pointer items-start gap-2.5">
				<input
					type="checkbox"
					checked={stopAfterWindow}
					onChange={(e) => setStopAfterWindow(e.target.checked)}
					className="mt-0.5 h-4 w-4 accent-primary"
				/>
				<span className="min-w-0">
					<span className="block text-sm text-content">
						Stop the campaign when a window ends
					</span>
					<span className="block text-xs text-content-muted">
						Budget returns to the default budget and the campaign is
						stopped; it starts again at the next window.
					</span>
				</span>
			</label>
			{mutation.isError && (
				<p className="text-xs text-danger">
					{mutation.error?.message ?? "Failed to save"}
				</p>
			)}
			<div className="flex gap-2">
				<Button
					type="submit"
					size="sm"
					disabled={mutation.isPending || !defaultBudget}
				>
					{mutation.isPending ? "Saving…" : "Save"}
				</Button>
				<Button
					type="button"
					size="sm"
					variant="ghost"
					onClick={onDone}
				>
					Cancel
				</Button>
			</div>
		</form>
	);
};
