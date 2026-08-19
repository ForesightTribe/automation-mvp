import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Card } from "../../../components/ui/Card";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { Loading } from "../../../components/feedback/Loading";
import { useClient } from "../../../context/ClientContext";
import {
	useBidRules,
	useBudgetSchedules,
	useCampaigns,
	useRefreshCampaigns,
	useSetActivationNow,
	useSetBudgetNow,
} from "../hooks";
import { CampaignRow } from "./CampaignRow";
import { FilterBar } from "./FilterBar";
import { JobStatus } from "./JobStatus";

// Blinkit's own campaign states, mapped to what the toggle may do.
//
// `on` is what the switch reads, NOT whether it can be clicked — the two come apart for
// ON_HOLD (live, but there is nothing to "start") and COMPLETED (terminal both ways).
// Blocked states carry their reason so the UI can explain itself instead of letting
// someone discover it as a failed job.
const STATE = {
	ACTIVE: {
		on: true,
		tone: "bg-success-soft text-success",
		label: "Running",
	},
	// Transient: for a minute or two after a restart Blinkit reports SCHEDULED before
	// settling to ACTIVE. It never showed up in the nightly scrape (too short-lived) but a
	// live refresh right after a start can absolutely catch it. It is live → stoppable.
	SCHEDULED: {
		on: true,
		tone: "bg-success-soft text-success",
		label: "Starting…",
	},
	STOPPED: {
		on: false,
		tone: "bg-muted text-content-muted",
		label: "Stopped",
	},
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
		blocked:
			"This campaign has ended. Completed campaigns can't be started or stopped.",
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
	["", "All"],
	["on", "Running"],
	["off", "Stopped"],
	["automated", "Automated"],
];

// Past this many rows the list gets its own scroll region. Below it the band just grows —
// a scrollbox around six rows is a worse page than six rows.
const SCROLL_AFTER = 12;

/**
 * The account's campaigns, with the two immediate actions on each: start/stop, and a
 * one-off budget push.
 *
 * A list rather than a search box because picking a campaign by typing its name is
 * exactly where this goes wrong: campaign names repeat across the account, so the client
 * wants to see what they have and flip it. Only campaigns present in the latest catalogue
 * sync are listed (see `getCampaigns`), which is what keeps a migrated-away account's dead
 * campaigns off this surface entirely.
 *
 * **Stopping is one click; starting opens a confirm step**, because on Blinkit a restart
 * is not a status flip: it re-submits the whole campaign and sets its budget, so the
 * number being written is shown to whoever is clicking rather than applied behind them.
 * Setting a budget confirms for the same reason.
 *
 * Statuses come from the last catalogue sync, so they steer the UI but never decide the
 * write — the real guardrails run on the VM against a live read. After any action the
 * band re-reads the account rather than optimistically flipping the row: a write can be
 * refused by a guardrail (or be a dry-run on an unarmed tenant), and a switch that lies
 * about a live campaign is worse than one that takes a moment to tell the truth.
 */
export const CampaignsSection = () => {
	const { data: campaigns = [], isLoading } = useCampaigns();
	const { data: schedules = [] } = useBudgetSchedules();
	const { data: bidRules = [] } = useBidRules();
	const activate = useSetActivationNow();
	const setBudgetNow = useSetBudgetNow();
	const refresh = useRefreshCampaigns();
	const qc = useQueryClient();
	const { activeClientId } = useClient();

	const [query, setQuery] = useState("");
	const [filter, setFilter] = useState("");
	const [panel, setPanel] = useState(null); // { id, kind: "start" | "budget" }
	const [budget, setBudget] = useState("");
	const [job, setJob] = useState(null); // { label, jobId, kind, campaignId }

	// A job is in flight — every control locks. Activation is one-job-per-client (the API
	// answers 409 on a second), and with a whole list on screen it is otherwise very easy
	// to fire three in a row and collect two errors.
	const busy =
		Boolean(job) ||
		activate.isPending ||
		setBudgetNow.isPending ||
		refresh.isPending;

	const scheduleFor = (id) => schedules.find((s) => s.campaign_id === id);
	const bidsFor = (id) => bidRules.filter((r) => r.campaign_id === id).length;

	const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
	const rows = campaigns
		.map((c) => ({
			...c,
			state: STATE[c.status] ?? unknownState(c.status),
		}))
		.filter((c) => {
			if (filter === "on" && !c.state.on) return false;
			if (filter === "off" && c.state.on) return false;
			if (filter === "automated")
				if (!scheduleFor(c.campaign_id) && !bidsFor(c.campaign_id))
					return false;
			if (!terms.length) return true;
			const hay = `${c.name || ""} ${c.campaign_id}`.toLowerCase();
			return terms.every((t) => hay.includes(t));
		});

	const filtering = Boolean(terms.length || filter);

	const startSync = () =>
		refresh.mutate(undefined, {
			onSuccess: (data) =>
				setJob({
					label: "Re-reading statuses",
					jobId: data.job_id,
					kind: "sync",
				}),
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

	const closePanel = () => {
		setPanel(null);
		setBudget("");
	};

	const onAction = (campaign, verb, data) => {
		const name = campaign.name || `campaign ${campaign.campaign_id}`;
		data.mutate(
			{ ...verb.body, campaignId: campaign.campaign_id },
			{
				onSuccess: (res) => {
					setJob({
						label: `${name} → ${verb.label}`,
						jobId: res.job_id,
						kind: "action",
						campaignId: campaign.campaign_id,
					});
					closePanel();
				},
			},
		);
	};

	const stop = (c) =>
		onAction(c, { label: "stop", body: { status: "paused" } }, activate);

	const start = (c) =>
		onAction(
			c,
			{
				label: "start",
				body: {
					status: "running",
					...(budget ? { budget: Number(budget) } : {}),
				},
			},
			activate,
		);

	const pushBudget = (c) => {
		const name = c.name || `campaign ${c.campaign_id}`;
		setBudgetNow.mutate(
			{ campaign_id: c.campaign_id, budget: Number(budget) },
			{
				onSuccess: (res) => {
					setJob({
						label: `${name} → ₹${budget}`,
						jobId: res.job_id,
						kind: "action",
						campaignId: c.campaign_id,
					});
					closePanel();
				},
			},
		);
	};

	const toggle = (c) => {
		if (c.state.on) return stop(c);
		setBudget(c.daily_budget != null ? String(c.daily_budget) : "");
		setPanel({ id: c.campaign_id, kind: "start" });
	};

	const openBudget = (c) => {
		setBudget(c.daily_budget != null ? String(c.daily_budget) : "");
		setPanel({ id: c.campaign_id, kind: "budget" });
	};

	const conflict =
		activate.error?.status === 409 ||
		setBudgetNow.error?.status === 409 ||
		refresh.error?.status === 409;
	const failure =
		(activate.error && activate.error.status !== 409 && activate.error) ||
		(setBudgetNow.error &&
			setBudgetNow.error.status !== 409 &&
			setBudgetNow.error);

	return (
		<Card title="Campaigns">
			{isLoading ? (
				<Loading />
			) : campaigns.length === 0 ? (
				<>
					<EmptyState
						title="No campaigns found"
						message="Nothing has been synced for this account yet. Refresh from Blinkit to pull the campaign list."
					/>
					<div className="mt-3 flex justify-center">
						<button
							type="button"
							onClick={startSync}
							disabled={busy}
							className="text-xs font-medium text-primary hover:text-primary-hover disabled:opacity-50"
						>
							↻ Refresh from Blinkit
						</button>
					</div>
				</>
			) : (
				<>
					<FilterBar
						query={query}
						onQuery={setQuery}
						placeholder="Search campaign or id…"
						options={FILTERS}
						value={filter}
						onValue={setFilter}
						active={filtering}
						onClear={() => {
							setQuery("");
							setFilter("");
						}}
						extra={
							<button
								type="button"
								onClick={startSync}
								disabled={busy}
								className="ml-2 text-xs font-medium text-content-muted hover:text-content disabled:cursor-not-allowed disabled:opacity-50"
							>
								↻ Refresh from Blinkit
							</button>
						}
					/>

					{rows.length === 0 ? (
						<p className="rounded-lg border border-dashed border-border px-4 py-5 text-center text-xs text-content-subtle">
							No campaigns match these filters.
						</p>
					) : (
						<ul
							className={`space-y-2.5 ${
								rows.length > SCROLL_AFTER
									? "max-h-[42rem] overflow-y-auto pr-1"
									: ""
							}`}
						>
							{rows.map((c) => (
								<CampaignRow
									key={c.campaign_id}
									campaign={c}
									state={c.state}
									schedule={scheduleFor(c.campaign_id)}
									bidCount={bidsFor(c.campaign_id)}
									busy={busy}
									pending={job?.campaignId === c.campaign_id}
									panel={
										panel?.id === c.campaign_id
											? panel.kind
											: null
									}
									budget={budget}
									onBudget={setBudget}
									onToggle={() => toggle(c)}
									onOpenBudget={() => openBudget(c)}
									onClosePanel={closePanel}
									onStart={() => start(c)}
									onSetBudget={() => pushBudget(c)}
								/>
							))}
						</ul>
					)}

					<p className="mt-3 text-xs text-content-subtle">
						Statuses come from the last catalogue sync, not live — a
						campaign changed elsewhere (or by an automation) shows
						its old state until you refresh.
					</p>
				</>
			)}

			{conflict && (
				<p className="mt-3 text-xs text-danger">
					A job is already running for this client — wait for it to
					finish.
				</p>
			)}
			{failure && (
				<p className="mt-3 text-xs text-danger">
					{failure.message ?? "That action could not be queued."}
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
