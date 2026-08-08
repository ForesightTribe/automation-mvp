import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { useClient } from "../../../context/ClientContext";
import { useCampaigns, useSetActivationNow } from "../hooks";
import { CampaignPicker } from "./CampaignPicker";
import { JobStatus } from "./JobStatus";

const LABEL = "text-xs font-medium text-content-muted";
const FIELD =
	"w-28 rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-content focus:border-primary focus:outline-none";

// Blinkit's own campaign states. `blocked` ones we never write — ON_HOLD is imposed by
// Blinkit and COMPLETED is terminal — so the button carries the reason rather than
// letting the user discover it as a failed job.
const STATE = {
	ACTIVE: { tone: "bg-success-soft text-success", label: "Running" },
	STOPPED: { tone: "bg-muted text-content-muted", label: "Stopped" },
	DRAFT: { tone: "bg-info-soft text-info", label: "Draft" },
	ON_HOLD: {
		tone: "bg-warning-soft text-warning",
		label: "On hold",
		blocked:
			"Blinkit put this campaign on hold — it can't be started or stopped from here.",
	},
	COMPLETED: {
		tone: "bg-muted text-content-subtle",
		label: "Completed",
		blocked:
			"This campaign has ended. Completed campaigns can't be restarted.",
	},
};

/**
 * Start or stop one campaign right now — enqueues a job and polls it (enqueue→poll).
 *
 * Stopping is one click. **Starting opens a confirm step**, because on Blinkit a restart
 * is not a status flip: it re-submits the whole campaign and sets its budget, so the
 * number being written is shown to whoever is clicking rather than applied behind them.
 * Leaving the budget blank reuses the campaign's current one, read fresh on the VM.
 *
 * The status shown comes from the last dashboard sync, so it can lag reality — it steers
 * the UI but never decides the write. The real guardrails run on the VM against a live
 * read (terminal states, budget bounds, rate limit, no-op).
 */
export const ActivateNowCard = () => {
	const activate = useSetActivationNow();
	const { data: campaigns = [] } = useCampaigns();
	const qc = useQueryClient();
	const { activeClientId } = useClient();
	const [campaign, setCampaign] = useState({ id: "", name: "" });
	const [confirming, setConfirming] = useState(false);
	const [budget, setBudget] = useState("");
	const [job, setJob] = useState(null);

	const selected = campaigns.find(
		(c) => c.campaign_id === Number(campaign.id),
	);
	const state = STATE[selected?.status] ?? null;
	const blocked = state?.blocked ?? null;

	const refreshHistory = () =>
		qc.invalidateQueries({ queryKey: ["cm2-history", activeClientId] });

	const send = (status, amount) => {
		const label = campaign.name || `campaign ${campaign.id}`;
		activate.mutate(
			{
				campaignId: Number(campaign.id),
				status,
				...(status === "running" && amount
					? { budget: Number(amount) }
					: {}),
			},
			{
				onSuccess: (data) => {
					setJob({
						label: `${label} → ${status === "running" ? "start" : "stop"}`,
						jobId: data.job_id,
					});
					setConfirming(false);
				},
			},
		);
	};

	const pick = (id, name) => {
		setCampaign({ id, name });
		setConfirming(false);
		setBudget("");
	};

	const startConfirm = () => {
		setBudget(
			selected?.daily_budget != null ? String(selected.daily_budget) : "",
		);
		setConfirming(true);
	};

	const conflict = activate.error?.status === 409;
	const busy = activate.isPending || !campaign.id;

	return (
		<Card title="Start or stop a campaign">
			<p className="mb-3 text-sm text-content-muted">
				Turn a campaign on or off immediately — no schedule needed.
			</p>

			<div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
				<label className="flex flex-col gap-1">
					<span className={LABEL}>Campaign</span>
					<CampaignPicker
						value={campaign.id}
						name={campaign.name}
						onChange={pick}
					/>
				</label>

				{!confirming && (
					<div className="flex items-center gap-2">
						<Button
							variant="secondary"
							disabled={busy || Boolean(blocked)}
							onClick={() => send("paused")}
						>
							Stop
						</Button>
						<Button
							disabled={busy || Boolean(blocked)}
							onClick={startConfirm}
						>
							Start
						</Button>
					</div>
				)}
			</div>

			{state && (
				<p className="mt-2 flex items-center gap-2 text-xs text-content-muted">
					<span
						className={`rounded-full px-2 py-0.5 font-medium ${state.tone}`}
					>
						{state.label}
					</span>
					as of the last dashboard sync
				</p>
			)}

			{blocked && <p className="mt-2 text-xs text-warning">{blocked}</p>}

			{confirming && (
				<div className="mt-4 rounded-lg border border-border bg-muted/40 p-3">
					<p className="text-sm font-medium text-content">
						Start {campaign.name || `campaign ${campaign.id}`}?
					</p>
					<p className="mt-1 text-xs text-content-muted">
						Blinkit restarts a campaign by re-submitting it, so its
						budget is set as part of starting it. Its keywords, bids
						and products are carried over unchanged.
					</p>
					<div className="mt-3 flex flex-wrap items-end gap-3">
						<label className="flex flex-col gap-1">
							<span className={LABEL}>Daily budget (₹)</span>
							<input
								type="number"
								min="1"
								value={budget}
								onChange={(e) => setBudget(e.target.value)}
								placeholder="current"
								className={FIELD}
							/>
						</label>
						<Button
							disabled={activate.isPending}
							onClick={() => send("running", budget)}
						>
							Start campaign
						</Button>
						<Button
							variant="ghost"
							onClick={() => setConfirming(false)}
						>
							Cancel
						</Button>
					</div>
					<p className="mt-2 text-xs text-content-subtle">
						Leave blank to keep the budget it was last running at.
					</p>
				</div>
			)}

			{conflict && (
				<p className="mt-3 text-xs text-danger">
					An activation job is already running for this client — wait
					for it to finish.
				</p>
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
