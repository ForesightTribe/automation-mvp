import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { useCreateBudgetSchedule } from "../hooks";
import { CampaignPicker } from "./CampaignPicker";
import { TimingFields, emptyTiming, timingPayload } from "./TimingFields";

const FIELD =
	"rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-content focus:border-primary focus:outline-none";
const LABEL = "text-xs font-medium text-content-muted";

/**
 * Automate a campaign's daily budget. In one step: pick the campaign, set the
 * default budget (what applies when no window is active), and optionally add a
 * first scheduled window (₹ + timing). More windows can be added later from the
 * scheduled list. Backend takes the inline `rule`, so this is a single request.
 */
export const AutomateBudgetForm = ({ onDone }) => {
	const [campaign, setCampaign] = useState({ id: "", name: "" });
	const [label, setLabel] = useState("");
	const [defaultBudget, setDefaultBudget] = useState("");
	const [windowBudget, setWindowBudget] = useState("");
	const [timing, setTiming] = useState(emptyTiming());
	const mutation = useCreateBudgetSchedule();

	const valid = campaign.id && defaultBudget && windowBudget;

	const submit = (e) => {
		e.preventDefault();
		if (!valid) return;
		mutation.mutate(
			{
				campaign_id: Number(campaign.id),
				campaign_name: campaign.name || null,
				name: label || null,
				default_budget: Number(defaultBudget),
				rule: { budget: Number(windowBudget), ...timingPayload(timing) },
			},
			{ onSuccess: () => onDone?.() },
		);
	};

	return (
		<form onSubmit={submit} className="space-y-4">
			<div className="grid gap-4 sm:grid-cols-2">
				<label className="flex flex-col gap-1 sm:col-span-2">
					<span className={LABEL}>Campaign</span>
					<CampaignPicker
						value={campaign.id}
						name={campaign.name}
						onChange={(id, name) => setCampaign({ id, name })}
					/>
				</label>
				<label className="flex flex-col gap-1">
					<span className={LABEL}>Everyday budget (₹)</span>
					<input
						type="number"
						min="1"
						value={defaultBudget}
						onChange={(e) => setDefaultBudget(e.target.value)}
						placeholder="300"
						className={FIELD}
					/>
					<span className="text-xs text-content-subtle">Used outside the scheduled window.</span>
				</label>
				<label className="flex flex-col gap-1">
					<span className={LABEL}>Label (optional)</span>
					<input
						value={label}
						onChange={(e) => setLabel(e.target.value)}
						placeholder="Weekend nights"
						className={FIELD}
					/>
				</label>
			</div>

			<div className="space-y-3 border-t border-border pt-4">
				<div>
					<h3 className="text-sm font-semibold text-content">Scheduled window</h3>
					<p className="text-xs text-content-muted">
						When to apply a different budget — and how much.
					</p>
				</div>
				<label className="flex max-w-48 flex-col gap-1">
					<span className={LABEL}>Budget during window (₹)</span>
					<input
						type="number"
						min="1"
						value={windowBudget}
						onChange={(e) => setWindowBudget(e.target.value)}
						placeholder="1500"
						className={FIELD}
					/>
				</label>
				<TimingFields value={timing} onChange={setTiming} />
			</div>

			{mutation.isError && (
				<p className="text-xs text-danger">
					{mutation.error?.status === 409
						? "An automation for that campaign already exists."
						: (mutation.error?.message ?? "Failed to create automation")}
				</p>
			)}

			<div className="flex gap-2">
				<Button type="submit" disabled={mutation.isPending || !valid}>
					{mutation.isPending ? "Creating…" : "Create budget automation"}
				</Button>
				<Button type="button" variant="ghost" onClick={onDone}>
					Cancel
				</Button>
			</div>
		</form>
	);
};
