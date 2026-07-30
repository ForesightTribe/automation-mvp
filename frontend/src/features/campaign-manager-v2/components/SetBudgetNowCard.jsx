import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { useClient } from "../../../context/ClientContext";
import { useSetBudgetNow } from "../hooks";
import { CampaignPicker } from "./CampaignPicker";
import { JobStatus } from "./JobStatus";

const LABEL = "text-xs font-medium text-content-muted";

/**
 * One-off "set this campaign's budget right now" — enqueues a job and polls it to a
 * result (enqueue→poll). Separate from the automations: no schedule, no windows, just
 * a manual push. Writes live once the account is armed.
 */
export const SetBudgetNowCard = () => {
	const setBudget = useSetBudgetNow();
	const qc = useQueryClient();
	const { activeClientId } = useClient();
	const [campaign, setCampaign] = useState({ id: "", name: "" });
	const [budget, setBudget2] = useState("");
	const [job, setJob] = useState(null);

	const refreshHistory = () => qc.invalidateQueries({ queryKey: ["cm2-history", activeClientId] });

	const submit = (e) => {
		e.preventDefault();
		if (!campaign.id || !budget) return;
		setBudget.mutate(
			{ campaign_id: Number(campaign.id), budget: Number(budget) },
			{
				onSuccess: (data) =>
					setJob({ label: `${campaign.name || `campaign ${campaign.id}`} → ₹${budget}`, jobId: data.job_id }),
			},
		);
	};

	const conflict = setBudget.error?.status === 409;

	return (
		<Card title="Set a budget now">
			<p className="mb-3 text-sm text-content-muted">
				Push a one-off budget to a campaign immediately — no schedule needed.
			</p>
			<form onSubmit={submit} className="grid gap-3 sm:grid-cols-[1fr_auto_auto] sm:items-end">
				<label className="flex flex-col gap-1">
					<span className={LABEL}>Campaign</span>
					<CampaignPicker
						value={campaign.id}
						name={campaign.name}
						onChange={(id, name) => setCampaign({ id, name })}
					/>
				</label>
				<label className="flex flex-col gap-1">
					<span className={LABEL}>Budget (₹)</span>
					<input
						type="number"
						min="1"
						value={budget}
						onChange={(e) => setBudget2(e.target.value)}
						placeholder="300"
						className="w-28 rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-content focus:border-primary focus:outline-none"
					/>
				</label>
				<Button type="submit" disabled={setBudget.isPending || !campaign.id || !budget}>
					Set budget
				</Button>
			</form>

			{conflict && (
				<p className="mt-3 text-xs text-danger">That job is already running — wait for it to finish.</p>
			)}
			{job && (
				<div className="mt-3 flex items-center gap-2 text-sm">
					<span className="text-content-muted">{job.label}:</span>
					<JobStatus jobId={job.jobId} onDone={refreshHistory} />
				</div>
			)}
		</Card>
	);
};
