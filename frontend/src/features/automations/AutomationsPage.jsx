import { useMemo, useState } from "react";
import { ScrollText, RefreshCw } from "lucide-react";
import { Loading } from "../../components/feedback/Loading";
import { ErrorState } from "../../components/feedback/ErrorState";
import { Button } from "../../components/ui/Button";
import { AutomationsFilterBar } from "./components/AutomationsFilterBar";
import { StatusSummary } from "./components/StatusSummary";
import { CampaignDetailDrawer } from "./components/CampaignDetailDrawer";
import { AutomationsTable } from "./components/AutomationsTable";
import { AutomationWizard } from "./components/AutomationWizard";
import { ChangeLogsModal } from "./components/ChangeLogsModal";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { formatCurrency, formatMeasuredAt } from "../../lib/format";
import {
	useBudgetSchedules,
	useBidRules,
	useSetBidState,
	useSetActivationNow,
	useDeleteBudgetSchedule,
	useDeleteBidRule,
	useResetBudgetSchedule,
	useResetBidRule,
	useRefreshCampaigns,
	useRecentActions,
	useActiveActionFor,
	ACTIVE_JOB_STATUSES,
} from "./hooks";

const confirmCopy = (action, row) => {
	const who =
		row.kind === "campaign"
			? row.name || row.campaign_name
			: `“${row.keyword}” on ${row.campaign_name}`;

	if (action === "pause")
		return {
			title: "Pause this automation?",
			confirmLabel: "Pause",
			body: (
				<>
					{who} stops being checked. The campaign keeps running and
					the bid stays where it is now, so nothing about the ad
					changes until you resume or reset it.
				</>
			),
		};

	if (action === "resume")
		return {
			title: "Resume this automation?",
			confirmLabel: "Resume",
			body: (
				<>
					{who} starts being checked again at the next run. Everything
					the engine learned before the pause is discarded, and if a
					window closed while it was paused the bid it missed lowering
					is put back first.
				</>
			),
		};

	if (action === "reset" && row.kind === "campaign")
		return {
			title: "Stop this automation and put the budget back?",
			confirmLabel: "Stop and reset",
			body: (
				<>
					{who} goes back to {formatCurrency(row.default_budget)} a
					day and this automation stops for good. It stays in the list
					with its history, but it will not run again.
					{row.stop_after_window
						? " The campaign is switched back on as part of this, in case the automation had stopped it."
						: ""}
				</>
			),
		};

	if (action === "reset")
		return {
			title: "Put the bid back to the minimum?",
			confirmLabel: "Reset bid",

			blocked:
				row.status === "running"
					? "This automation is running right now. Pause it first, or the next check will bid it straight back up."
					: null,
			body: (
				<>
					{who} goes back to {formatCurrency(row.min_bid)}. The
					automation itself is left alone, so it will bid up again the
					next time its window opens.
				</>
			),
		};

	return {
		title: "Delete this automation?",
		confirmLabel: "Delete",
		danger: true,
		body:
			row.kind === "campaign" ? (
				<>
					{who} will stop running and can't be recovered. The campaign
					keeps whatever budget it is on right now, so reset it first
					if it should go back to {formatCurrency(row.default_budget)}{" "}
					a day.
				</>
			) : (
				<>{who} will stop running and can't be recovered.</>
			),
	};
};

/**
 * Why an action could not even be QUEUED, in the reader's words.
 *
 * 409 is the expected answer, not an error: the campaign lanes hold ONE job each, and the
 * queue refuses a second of the same kind for the same client rather than letting two
 * writes race. So it is reported as a wait, not a failure — the first one is still running
 * and will finish.
 *
 * Anything else keeps the server's own message, which is more specific than a generic
 * sentence would be.
 */
const conflictMessage = (err, what) =>
	err?.response?.status === 409
		? `Another action is already running, so this one was not queued. Wait for it to finish, then try to ${what} again.`
		: (err?.message ?? `Could not ${what}.`);

/**
 * Automations — a new, independently-built management experience over the
 * same Campaign Manager v2 backend (budget schedules + bid rules), styled
 * after Dcluttr's Automations screen: a header with its own
 * Create/Change-Logs actions, a rank-automation promo, channel pills +
 * underlined type tabs, a list with an inline on/off toggle and icon
 * controls, and a full-screen change-log overlay. Campaign Manager's own
 * page is untouched; this is a second, first-class way to reach the same
 * automations. No row-selection/bulk actions — that isn't built yet.
 */
export const AutomationsPage = () => {
	const {
		data: schedules,
		isLoading: loadingSchedules,
		error: schedulesError,
	} = useBudgetSchedules();
	const {
		data: bidRules,
		isLoading: loadingBidRules,
		error: bidRulesError,
	} = useBidRules();

	const [channel, setChannel] = useState("");
	const [type, setType] = useState("");
	const [status, setStatus] = useState("");
	const [wizardKind, setWizardKind] = useState(null); // null | "campaign" | "keyword"
	const [editRow, setEditRow] = useState(null);
	const [logRow, setLogRow] = useState(null); // null = the unfiltered overlay
	const [logsOpen, setLogsOpen] = useState(false);
	// Pause, resume, reset and delete all run through one dialog: { action, row }.
	// A single slot is right because they are all row actions and only one row is ever
	// being acted on.
	const [confirm, setConfirm] = useState(null);
	const [confirmError, setConfirmError] = useState(null);
	// Delete-a-keyword-rule offers to put the bid back first. It defaults to ON because
	// the alternative leaves a bid the optimizer raised with no rule left to lower it.
	const [resetBidOnDelete, setResetBidOnDelete] = useState(true);
	const [detailCampaign, setDetailCampaign] = useState(null);
	// The most recent action this page enqueued. It is NOT how the page reports progress
	// any more — that is `useRecentActions`, which reads the queue from the server and so
	// survives a reload and covers several actions at once, where this single slot could
	// do neither.
	//
	// It is kept for one job only: the campaign toggle inside the wizard. That toggle sits
	// behind a full-screen overlay, so its result has to be rendered inside the wizard, and
	// the wizard needs the id to do it. The id alone is enough — the job carries a `run_id`
	// and the outcome is read from the history rows filed under it.
	const [actionJob, setActionJob] = useState(null);
	// Why the last action could not even be QUEUED — distinct from what an action did once
	// it ran, which the activity list reports. Nothing reaches the VM in this case, so
	// there is no job and no run log row to read it from.
	const [actionError, setActionError] = useState(null);

	const setBidState = useSetBidState();
	const setActivationNow = useSetActivationNow();
	const deleteSchedule = useDeleteBudgetSchedule();
	const deleteBid = useDeleteBidRule();
	const resetSchedule = useResetBudgetSchedule();
	const resetBid = useResetBidRule();
	const refreshCampaigns = useRefreshCampaigns();
	// In-flight actions, from the server rather than from component state — so the count
	// survives a reload, and a job someone started in another tab still shows here.
	const { data: recentActions } = useRecentActions();
	const activeActionFor = useActiveActionFor();
	const runningCount = (recentActions ?? []).filter((a) =>
		ACTIVE_JOB_STATUSES.has(a.status),
	).length;

	/**
	 * A campaign id to the name a person recognises. The activity list gets ids (that is
	 * what the job carries), and "Campaign budget change · 637511" tells a reader nothing.
	 * Read off the automations already loaded for the table, so it costs no extra request.
	 */
	const campaignNameOf = (id) =>
		schedules?.find((x) => x.campaign_id === id)?.campaign_name ??
		bidRules?.find((x) => x.campaign_id === id)?.campaign_name ??
		null;

	const rows = useMemo(() => {
		const campaignRows = (schedules ?? []).map((s) => ({
			...s,
			kind: "campaign",
		}));
		const keywordRows = (bidRules ?? []).map((b) => ({
			...b,
			kind: "keyword",
		}));
		return [...campaignRows, ...keywordRows].filter((r) => {
			if (channel && r.platform !== channel) return false;
			if (type && r.kind !== type) return false;
			if (status && r.status !== status) return false;
			return true;
		});
	}, [schedules, bidRules, channel, type, status]);

	// Cheap enough to derive on every render, and it keeps the header honest as rows change.
	const total = (schedules?.length ?? 0) + (bidRules?.length ?? 0);
	const typeCounts = {
		"": total,
		campaign: schedules?.length ?? 0,
		keyword: bidRules?.length ?? 0,
	};

	const platformOf = (campaignId) =>
		schedules?.find((s) => s.campaign_id === campaignId)?.platform ??
		bidRules?.find((b) => b.campaign_id === campaignId)?.platform;

	/**
	 * The store a bid rule measures position at, looked up from the rules already
	 * fetched for the table.
	 *
	 * ⚠️ Only bid rules have one, and it is the single most load-bearing fact about
	 * a bid row: rank is checked at ONE dark store, so "position 5" means position 5
	 * there. The run log carries no location field, so it is joined here rather than
	 * left off. Trimmed, because the value arrives with trailing whitespace from the
	 * scrape ("Financial District\r\n").
	 *
	 * WITH the city, because the store label alone does not locate anything: "Block C"
	 * and "Sector 110" name a neighbourhood in a city the reader has to already know.
	 */
	const locationOf = (campaignId, keyword) => {
		const rule = bidRules?.find(
			(b) =>
				b.campaign_id === campaignId &&
				(!keyword || b.keyword === keyword),
		);
		return rule
			? formatMeasuredAt(rule.location_name, rule.city_name)
			: null;
	};

	const isLoading = loadingSchedules || loadingBidRules;
	const error = schedulesError || bidRulesError;

	// Nothing on a row happens on the click itself. Each control only opens the dialog;
	// `runConfirm` is the single place that talks to the engine.
	const ask = (action, row) => {
		setConfirmError(null);
		setResetBidOnDelete(true);
		setConfirm({ action, row });
	};

	// The campaign's state, which is a different thing entirely — enqueued the same way
	// Campaign Manager v2 does it, and reported through the shared job line.
	const handleActivate = async (row, status) => {
		// ⚠️ This used to have no error path at all. The endpoint answers 409 when an
		// activation for this client is already active — a normal, expected outcome on a
		// single-slot lane — and the rejection went nowhere: no message, no console entry a
		// user would see, just a click that appeared to do nothing.
		try {
			const res = await setActivationNow.mutateAsync({
				campaignId: row.campaign_id,
				status,
			});
			setActionJob(res.job_id);
			setActionError(null);
		} catch (err) {
			setActionError(conflictMessage(err, "start or stop a campaign"));
		}
	};

	/**
	 * Carry out whatever the dialog was confirming.
	 *
	 * The engine refuses some of these outright — resetting a rule that is running comes
	 * back a 409 with a sentence explaining why. That sentence is the best copy available
	 * for the situation, so it is shown in the dialog and the dialog stays open, rather
	 * than closing on a failure the user never sees.
	 */
	const runConfirm = async () => {
		const { action, row } = confirm;
		setConfirmError(null);
		try {
			if (action === "pause" || action === "resume") {
				await setBidState.mutateAsync({ ruleId: row.id, action });
			} else if (action === "reset") {
				const res =
					row.kind === "campaign"
						? await resetSchedule.mutateAsync(row.id)
						: await resetBid.mutateAsync(row.id);
				setActionJob(res.job_id);
			} else if (action === "delete") {
				if (row.kind === "campaign") {
					await deleteSchedule.mutateAsync(row.id);
				} else {
					await deleteBid.mutateAsync({
						ruleId: row.id,
						reset: resetBidOnDelete,
					});
				}
			}
			setConfirm(null);
		} catch (err) {
			setConfirmError(err.message);
		}
	};

	const handleRefreshCampaigns = async () => {
		try {
			const res = await refreshCampaigns.mutateAsync();
			setActionJob(res.job_id);
			setActionError(null);
		} catch (err) {
			setActionError(conflictMessage(err, "refresh the campaign list"));
		}
	};

	return (
		// Vertical rhythm: 24px is the within-section gap, so the three top-level blocks —
		// header, the create CTAs, and the list — get a wider one to read as separate
		// sections rather than a single stack of cards.
		<div className="space-y-6">
			<header className="flex flex-wrap items-center justify-between gap-3">
				<div>
					<h1 className="font-display text-2xl font-semibold tracking-tight text-content">
						Automations
					</h1>
					<p className="text-sm text-content-muted">
						Budget and bid automations across channels.
					</p>
				</div>
				<div className="flex items-center gap-2">
					{/* Current status: one line, detail behind a click. It carries what the table cannot show:
					    i.e. whether anything is inside a window now, when the next one opens, and
					    what the engine last actually did. */}
					<StatusSummary
						schedules={schedules ?? []}
						bidRules={bidRules ?? []}
					/>
					<Button
						variant="secondary"
						size="sm"
						disabled={refreshCampaigns.isPending}
						onClick={handleRefreshCampaigns}
						title="Re-read the campaign list from Blinkit"
					>
						<RefreshCw size={14} /> Refresh Campaigns
					</Button>
					{/* The one signal that has to live OUTSIDE the logs modal: without it a
					    click would have no visible consequence at all until you thought to
					    open something. A count rather than a word — it stays meaningful when
					    two things are queued, which "Applying…" never was. */}
					<Button
						variant="secondary"
						size="sm"
						onClick={() => {
							setLogRow(null);
							setLogsOpen(true);
						}}
						title={
							runningCount
								? `${runningCount} action${runningCount > 1 ? "s" : ""} in progress`
								: "What the automations have been doing"
						}
					>
						<ScrollText size={14} /> Execution logs
						{runningCount > 0 && (
							<span className="ml-1.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1.5 text-[11px] font-semibold text-on-primary">
								{runningCount}
							</span>
						)}
					</Button>
				</div>
			</header>

			{/* A refusal to QUEUE, which is different from a write that was refused: nothing
			    reached the marketplace, so there is no run to look up and the activity list
			    will show nothing. Dismissible, and cleared by the next successful action. */}
			{actionError && (
				<div className="flex items-start justify-between gap-3 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm text-content">
					<span>{actionError}</span>
					<button
						type="button"
						onClick={() => setActionError(null)}
						className="shrink-0 cursor-pointer text-xs text-content-muted underline hover:text-content"
					>
						Dismiss
					</button>
				</div>
			)}

			{/* Two CTAs instead of one generic button plus a promo banner: the kind of
			    automation is the first real decision, so it is made here rather than on the
			    first screen of the wizard. The wizard then opens already knowing which it is. */}
			<div className="mt-10 grid gap-4 sm:grid-cols-2">
				{[
					{
						kind: "campaign",
						title: "Campaign / Budget Automation",
						cta: "Create Campaign Automation",
						blurb: "Raise or lower a campaign's daily budget on chosen days and hours. It starts for the window and stops when the window ends.",
					},
					{
						kind: "keyword",
						title: "Keyword Automation",
						cta: "Create Keyword Automation",
						blurb: "Hold a keyword's search position. The optimizer moves its bid within the limits you set to reach the rank you want and defend it.",
					},
				].map((c) => (
					// The card describes; the button acts. A whole card that is itself a button
					// gives no target to aim at and no way to read it without arming it.
					<div
						key={c.kind}
						className="group flex flex-col items-start gap-4 rounded-xl border border-border bg-card p-5 transition-all duration-150 hover:border-content-subtle hover:shadow-sm"
					>
						<div>
							<p className="font-display text-base font-semibold tracking-tight text-content">
								{c.title}
							</p>
							<p className="mt-1.5 text-sm leading-relaxed text-content-muted">
								{c.blurb}
							</p>
						</div>
						<Button
							variant="brandSolid"
							size="md"
							className="mt-auto"
							onClick={() => setWizardKind(c.kind)}
						>
							{c.cta}
						</Button>
					</div>
				))}
			</div>

			{/* The list is one section: its filters and its table belong together, and the
			    section as a whole sits well clear of the create CTAs above it. */}
			<section className="mt-10 space-y-4">
				<AutomationsFilterBar
					channel={channel}
					onChannel={setChannel}
					type={type}
					onType={setType}
					status={status}
					onStatus={setStatus}
					counts={typeCounts}
				/>

				{isLoading && <Loading label="Loading automations…" />}
				{error && <ErrorState message={error.message} />}
				{/* The table needs its own ground. `DataTable` paints no surface, so on the page's
				    cream the rows showed the background through while the sticky header was
				    white — the table read as loose rows rather than as one object. White inside
				    a hairline border is the same treatment every other table on the product
				    gets, and `overflow-hidden` keeps the table's own scroll box inside the
				    rounded corners. */}
				{!isLoading && !error && (
					<div className="overflow-hidden rounded-xl border border-border bg-card">
						<AutomationsTable
							activeActionFor={activeActionFor}
							rows={rows}
							onEdit={setEditRow}
							onDelete={(row) => ask("delete", row)}
							onToggle={(row, action) => ask(action, row)}
							onReset={(row) => ask("reset", row)}
							onOpenCampaign={setDetailCampaign}
							onViewLog={(row) => {
								setLogRow(row);
								setLogsOpen(true);
							}}
						/>
					</div>
				)}
			</section>

			<CampaignDetailDrawer
				open={detailCampaign != null}
				campaignId={detailCampaign}
				onClose={() => setDetailCampaign(null)}
				schedules={schedules ?? []}
				bidRules={bidRules ?? []}
			/>

			<AutomationWizard
				open={wizardKind !== null || editRow !== null}
				editRow={editRow}
				initialKind={wizardKind ?? "campaign"}
				/* The picker's start/stop acts on the CAMPAIGN, so it goes through the same
				   handler and the same job feedback as the toggle on the list below. */
				onActivateCampaign={handleActivate}
				/* The toggle lives inside this overlay, so its result has to be reported
				   inside it too — the page behind is not visible while it is open. */
				activationJobId={actionJob}
				onClose={() => {
					setWizardKind(null);
					setEditRow(null);
				}}
			/>
			<ChangeLogsModal
				open={logsOpen}
				onClose={() => setLogsOpen(false)}
				focusRow={logRow}
				platformOf={platformOf}
				locationOf={locationOf}
				campaignNameOf={campaignNameOf}
			/>

			<ConfirmDialog
				open={Boolean(confirm)}
				{...(confirm
					? confirmCopy(confirm.action, confirm.row)
					: { title: "", body: null })}
				pending={
					setBidState.isPending ||
					resetSchedule.isPending ||
					resetBid.isPending ||
					deleteSchedule.isPending ||
					deleteBid.isPending
				}
				error={confirmError}
				onCancel={() => setConfirm(null)}
				onConfirm={runConfirm}
			>
				{/* Deleting a keyword rule is the one action with a second decision in it:
				    the bid does not come down on its own once the rule is gone. */}
				{confirm?.action === "delete" &&
					confirm.row.kind === "keyword" && (
						<label className="mb-4 flex items-start gap-2 text-sm text-content">
							<input
								type="checkbox"
								checked={resetBidOnDelete}
								onChange={(e) =>
									setResetBidOnDelete(e.target.checked)
								}
								className="mt-0.5 accent-brand"
							/>
							<span>
								Put the bid back to{" "}
								{formatCurrency(confirm.row.min_bid)} first.
								Without this it stays wherever the automation
								left it.
							</span>
						</label>
					)}
			</ConfirmDialog>
		</div>
	);
};
