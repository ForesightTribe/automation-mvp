import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { Loading } from "../../../components/feedback/Loading";
import { useClient } from "../../../context/ClientContext";
import { useCampaigns, useRefreshCampaigns, useSetActivationNow } from "../hooks";
import { JobStatus } from "./JobStatus";

const FIELD =
	"rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-content focus:border-primary focus:outline-none";

// Blinkit's own campaign states, mapped to what the toggle may do.
//
// `on` is what the switch reads, NOT whether it can be clicked — the two come apart for
// ON_HOLD (live, but there is nothing to "start") and COMPLETED (terminal both ways).
// Blocked states carry their reason so the UI can explain itself instead of letting
// someone discover it as a failed job.
const STATE = {
	ACTIVE: { on: true, tone: "bg-success-soft text-success", label: "Running" },
	// Transient: for a minute or two after a restart Blinkit reports SCHEDULED before
	// settling to ACTIVE. It never showed up in the nightly scrape (too short-lived) but a
	// live refresh right after a start can absolutely catch it. It is live → stoppable.
	SCHEDULED: { on: true, tone: "bg-success-soft text-success", label: "Starting…" },
	STOPPED: { on: false, tone: "bg-muted text-content-muted", label: "Stopped" },
	DRAFT: { on: false, tone: "bg-info-soft text-info", label: "Draft" },
	// ON_HOLD = Blinkit paused delivery because the daily budget ran out. The campaign is
	// LIVE, so Stop applies; Start does not, because it was never stopped — raising its
	// budget is what revives it.
	ON_HOLD: {
		on: true,
		tone: "bg-warning-soft text-warning",
		label: "On hold",
		noStart:
			"Its daily budget is used up, so Blinkit has paused delivery. Raise the budget to revive it — there's nothing to restart.",
	},
	COMPLETED: {
		on: false,
		tone: "bg-muted text-content-subtle",
		label: "Completed",
		blocked: "This campaign has ended. Completed campaigns can't be started or stopped.",
	},
};

// An unrecognised status is shown as-is and left un-toggleable: we would be guessing at
// what the write means, and this is a real-money surface.
const unknownState = (status) => ({
	on: false,
	tone: "bg-muted text-content-muted",
	label: status || "Unknown",
	blocked: `Blinkit reports this campaign as "${status}", which we don't recognise — it can't be started or stopped from here.`,
});

const FILTERS = [
	{ key: "all", label: "All" },
	{ key: "on", label: "Running" },
	{ key: "off", label: "Stopped" },
];

// The knob is anchored with an explicit `left`: an absolutely-positioned element with no
// horizontal anchor falls back to its *static* position, which is whatever the button's
// own box happens to give it — so it rendered off-centre. Anchor first, then translate.
const Toggle = ({ on, disabled, onClick, label }) => (
	<button
		type="button"
		role="switch"
		aria-checked={on}
		aria-label={label}
		disabled={disabled}
		onClick={onClick}
		className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-0 p-0 transition-colors ${
			on ? "bg-success" : "bg-content-subtle"
		} ${disabled ? "cursor-not-allowed opacity-40" : "cursor-pointer hover:opacity-80"}`}
	>
		<span
			className={`pointer-events-none absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-card shadow-sm ring-1 ring-black/10 transition-transform ${
				on ? "translate-x-4" : "translate-x-0"
			}`}
		/>
	</button>
);

/**
 * Start or stop campaigns — the whole account listed, one toggle each.
 *
 * A list rather than a search box because picking a campaign by typing its name is
 * exactly where this goes wrong: campaign names repeat across the account, so the
 * client wants to see what they have and flip it. Only campaigns present in the latest
 * catalogue sync are listed (see `getCampaigns`), which is what keeps a migrated-away
 * account's dead campaigns off this surface entirely.
 *
 * **Stopping is one click; starting opens a confirm step**, because on Blinkit a restart
 * is not a status flip: it re-submits the whole campaign and sets its budget, so the
 * number being written is shown to whoever is clicking rather than applied behind them.
 *
 * Statuses come from the last catalogue sync, so they steer the UI but never decide the
 * write — the real guardrails run on the VM against a live read. After any action the
 * card re-reads the account rather than optimistically flipping the row: a write can be
 * refused by a guardrail (or be a dry-run on an unarmed tenant), and a switch that lies
 * about a live campaign is worse than one that takes a moment to tell the truth.
 */
export const ActivateNowCard = () => {
	const { data: campaigns = [], isLoading } = useCampaigns();
	const activate = useSetActivationNow();
	const refresh = useRefreshCampaigns();
	const qc = useQueryClient();
	const { activeClientId } = useClient();

	const [query, setQuery] = useState("");
	const [filter, setFilter] = useState("all");
	const [confirming, setConfirming] = useState(null); // campaign_id being started
	const [budget, setBudget] = useState("");
	const [job, setJob] = useState(null); // { label, jobId, kind: "action" | "sync" }

	const rows = useMemo(() => {
		const q = query.trim().toLowerCase();
		return campaigns
			.map((c) => ({ ...c, state: STATE[c.status] ?? unknownState(c.status) }))
			.filter((c) => {
				if (filter === "on" && !c.state.on) return false;
				if (filter === "off" && c.state.on) return false;
				if (!q) return true;
				return (
					(c.name || "").toLowerCase().includes(q) ||
					String(c.campaign_id).includes(q)
				);
			});
	}, [campaigns, query, filter]);

	// A job is in flight — every toggle locks. Activation is one-job-per-client (the API
	// answers 409 on a second), and with a whole list on screen it is otherwise very easy
	// to fire three in a row and collect two errors.
	const busy = Boolean(job) || activate.isPending || refresh.isPending;

	const startSync = () =>
		refresh.mutate(undefined, {
			onSuccess: (data) =>
				setJob({ label: "Re-reading statuses", jobId: data.job_id, kind: "sync" }),
			onError: () => setJob(null),
		});

	const onJobDone = (status) => {
		if (job?.kind === "action") {
			// Only worth re-reading if the job itself got that far; a failed job changed
			// nothing, and the error is already on screen.
			if (status === "success") startSync();
			else setJob(null);
			return;
		}
		qc.invalidateQueries({ queryKey: ["cm2-campaigns", activeClientId] });
		qc.invalidateQueries({ queryKey: ["cm2-history", activeClientId] });
		setJob(null);
	};

	const send = (campaign, status, amount) => {
		activate.mutate(
			{
				campaignId: campaign.campaign_id,
				status,
				...(status === "running" && amount ? { budget: Number(amount) } : {}),
			},
			{
				onSuccess: (data) => {
					setJob({
						label: `${campaign.name || `campaign ${campaign.campaign_id}`} → ${
							status === "running" ? "start" : "stop"
						}`,
						jobId: data.job_id,
						kind: "action",
					});
					setConfirming(null);
					setBudget("");
				},
			},
		);
	};

	const onToggle = (c) => {
		if (c.state.on) return send(c, "paused");
		setBudget(c.daily_budget != null ? String(c.daily_budget) : "");
		setConfirming(c.campaign_id);
	};

	const conflict = activate.error?.status === 409 || refresh.error?.status === 409;

	return (
		<Card
			title="Start or stop a campaign"
			actions={
				<button
					type="button"
					onClick={startSync}
					disabled={busy}
					className="text-xs font-medium text-content-muted hover:text-content disabled:cursor-not-allowed disabled:opacity-50"
				>
					↻ Refresh from Blinkit
				</button>
			}
		>
			<p className="mb-3 text-sm text-content-muted">
				Turn campaigns on or off immediately — no schedule needed.
			</p>

			<div className="mb-3 flex flex-wrap items-center gap-2">
				<input
					className={`${FIELD} min-w-0 flex-1`}
					value={query}
					onChange={(e) => setQuery(e.target.value)}
					placeholder="Filter by name or id…"
				/>
				<div className="flex rounded-md border border-border p-0.5">
					{FILTERS.map((f) => (
						<button
							key={f.key}
							type="button"
							onClick={() => setFilter(f.key)}
							className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
								filter === f.key
									? "bg-primary text-on-primary"
									: "text-content-muted hover:text-content"
							}`}
						>
							{f.label}
						</button>
					))}
				</div>
			</div>

			{isLoading && <Loading />}

			{!isLoading && campaigns.length === 0 && (
				<EmptyState
					title="No campaigns found"
					message="Nothing has been synced for this account yet. Refresh from Blinkit to pull the campaign list."
				/>
			)}

			{!isLoading && campaigns.length > 0 && rows.length === 0 && (
				<p className="py-6 text-center text-sm text-content-muted">
					No campaigns match that filter.
				</p>
			)}

			{rows.length > 0 && (
				<ul className="max-h-96 divide-y divide-border overflow-y-auto rounded-lg border border-border">
					{rows.map((c) => {
						const blocked = c.state.blocked ?? null;
						const noStart = c.state.noStart ?? null;
						// A row is toggleable unless the state forbids it outright, or
						// forbids the only direction the switch could move it.
						const locked = Boolean(blocked) || (!c.state.on && Boolean(noStart));
						return (
							<li key={c.campaign_id} className="px-3 py-2.5">
								<div className="flex items-center gap-3">
									<div className="min-w-0 flex-1">
										<p className="truncate text-sm text-content">
											{c.name || `campaign ${c.campaign_id}`}
										</p>
										<p className="mt-0.5 flex items-center gap-1.5 text-xs text-content-subtle">
											<span
												className={`rounded-full px-1.5 py-0.5 font-medium ${c.state.tone}`}
											>
												{c.state.label}
											</span>
											#{c.campaign_id}
										</p>
									</div>
									<Toggle
										on={c.state.on}
										disabled={busy || locked}
										onClick={() => onToggle(c)}
										label={`${c.state.on ? "Stop" : "Start"} ${
											c.name || `campaign ${c.campaign_id}`
										}`}
									/>
								</div>

								{(blocked || noStart) && (
									<p className="mt-1.5 text-xs text-warning">{blocked ?? noStart}</p>
								)}

								{confirming === c.campaign_id && (
									<div className="mt-3 rounded-lg border border-border bg-muted/40 p-3">
										<p className="text-sm font-medium text-content">
											Start {c.name || `campaign ${c.campaign_id}`}?
										</p>
										<p className="mt-1 text-xs text-content-muted">
											Blinkit restarts a campaign by re-submitting it, so its
											budget is set as part of starting it. Its keywords, bids
											and products are carried over unchanged.
										</p>
										<div className="mt-3 flex flex-wrap items-end gap-3">
											<label className="flex flex-col gap-1">
												<span className="text-xs font-medium text-content-muted">
													Daily budget (₹)
												</span>
												<input
													type="number"
													min="1"
													value={budget}
													onChange={(e) => setBudget(e.target.value)}
													placeholder="current"
													className={`${FIELD} w-28`}
												/>
											</label>
											<Button
												disabled={activate.isPending}
												onClick={() => send(c, "running", budget)}
											>
												Start campaign
											</Button>
											<Button variant="ghost" onClick={() => setConfirming(null)}>
												Cancel
											</Button>
										</div>
										<p className="mt-2 text-xs text-content-subtle">
											Leave blank to keep the budget it was last running at.
										</p>
									</div>
								)}
							</li>
						);
					})}
				</ul>
			)}

			{rows.length > 0 && (
				<p className="mt-2 text-xs text-content-subtle">
					Statuses come from the last catalogue sync, not live — a campaign changed
					elsewhere (or by an automation) shows its old state until you refresh.
				</p>
			)}

			{conflict && (
				<p className="mt-3 text-xs text-danger">
					A job is already running for this client — wait for it to finish.
				</p>
			)}
			{job && (
				<div className="mt-3 flex items-center gap-2 text-sm">
					<span className="text-content-muted">{job.label}:</span>
					<JobStatus jobId={job.jobId} onDone={onJobDone} />
				</div>
			)}
		</Card>
	);
};
