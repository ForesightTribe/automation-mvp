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
import { JobLine } from "./components/JobLine";
import {
	useBudgetSchedules,
	useBidRules,
	useCampaignNames,
	useSetBidState,
	useSetActivationNow,
	useDeleteBudgetSchedule,
	useDeleteBidRule,
	useSetBudgetNow,
	useRefreshCampaigns,
} from "./hooks";

/**
 * Automations — a new, independently-built management experience over the
 * same Campaign Manager v2 backend (budget schedules + bid rules), styled
 * after Dcluttr's Automations screen: a beta-tagged header with its own
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
	const [deleteRow, setDeleteRow] = useState(null);
	const [detailCampaign, setDetailCampaign] = useState(null);
	const [budgetRow, setBudgetRow] = useState(null); // set-budget-now target
	const [budgetAmount, setBudgetAmount] = useState("");
	// Reset / set-budget / refresh all enqueue a VM job and return its id; one slot is
	// enough because they are one-at-a-time actions and the line reports the latest.
	const [actionJob, setActionJob] = useState(null);

	// Campaign status for the Controls switch. Deliberately the NAMES query (recent_only
	// off): a campaign hidden from the selectable list can still own an automation, and a
	// missing status locks the switch rather than defaulting it to "off".
	const { data: allCampaigns } = useCampaignNames();
	const campaignStatusOf = (id) =>
		(allCampaigns ?? []).find((c) => c.campaign_id === id)?.status;

	const setBidState = useSetBidState();
	const setActivationNow = useSetActivationNow();
	const deleteSchedule = useDeleteBudgetSchedule();
	const deleteBid = useDeleteBidRule();
	const setBudgetNow = useSetBudgetNow();
	const refreshCampaigns = useRefreshCampaigns();

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
	 */
	const locationOf = (campaignId, keyword) =>
		bidRules
			?.find(
				(b) =>
					b.campaign_id === campaignId &&
					(!keyword || b.keyword === keyword),
			)
			?.location_name?.trim() || null;

	const isLoading = loadingSchedules || loadingBidRules;
	const error = schedulesError || bidRulesError;

	// The switch column is the AUTOMATION's own state, which only bid rules have.
	const handleToggle = (row, action) =>
		setBidState.mutate({ ruleId: row.id, action });

	// The campaign's state, which is a different thing entirely — enqueued the same way
	// Campaign Manager v2 does it, and reported through the shared job line.
	const handleActivate = async (row, status) => {
		const res = await setActivationNow.mutateAsync({
			campaignId: row.campaign_id,
			status,
		});
		setActionJob(res.job_id);
	};

	// Ends a keyword rule for good (engine state "stopped"), as distinct from pausing it.
	// Deleting removes the row; stopping keeps it and its history.
	const handleStop = (row) =>
		setBidState.mutate({ ruleId: row.id, action: "stop" });

	const handleDelete = (row) => {
		if (row.kind === "campaign") {
			deleteSchedule.mutate(row.id);
		} else {
			deleteBid.mutate(row.id);
		}
		setDeleteRow(null);
	};

	const handleSetBudget = async () => {
		const res = await setBudgetNow.mutateAsync({
			campaign_id: budgetRow.campaign_id,
			budget: Number(budgetAmount),
		});
		setActionJob(res.job_id);
		setBudgetRow(null);
		setBudgetAmount("");
	};

	const handleRefreshCampaigns = async () => {
		const res = await refreshCampaigns.mutateAsync();
		setActionJob(res.job_id);
	};

	return (
		// Vertical rhythm: 24px is the within-section gap, so the three top-level blocks —
		// header, the create CTAs, and the list — get a wider one to read as separate
		// sections rather than a single stack of cards.
		<div className="space-y-6">
			<header className="flex flex-wrap items-center justify-between gap-3">
				<div>
					<div className="flex items-center gap-2">
						<h1 className="font-display text-2xl font-semibold tracking-tight text-content">
							Automations
						</h1>
						<span className="rounded-full bg-warning-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warning">
							Beta
						</span>
					</div>
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
					<JobLine jobId={actionJob} />
					<Button
						variant="secondary"
						size="sm"
						disabled={refreshCampaigns.isPending}
						onClick={handleRefreshCampaigns}
						title="Re-read the campaign list from Blinkit"
					>
						<RefreshCw size={14} /> Refresh Campaigns
					</Button>
					<Button
						variant="secondary"
						size="sm"
						onClick={() => {
							setLogRow(null);
							setLogsOpen(true);
						}}
					>
						<ScrollText size={14} /> Execution logs
					</Button>
				</div>
			</header>

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
							rows={rows}
							onEdit={setEditRow}
							onDelete={setDeleteRow}
							onToggle={handleToggle}
							onActivate={handleActivate}
							campaignStatusOf={campaignStatusOf}
							onOpenCampaign={setDetailCampaign}
							onViewLog={(row) => {
								setLogRow(row);
								setLogsOpen(true);
							}}
							onStop={handleStop}
							onSetBudget={(row) => {
								setBudgetRow(row);
								setBudgetAmount(
									String(row.default_budget ?? ""),
								);
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
			/>

			{budgetRow && (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
					<div className="w-full max-w-sm rounded-lg border border-border bg-card p-5">
						<h3 className="mb-2 font-display text-base font-semibold text-content">
							Set budget now
						</h3>
						<p className="mb-3 text-sm text-content-muted">
							Pushes a budget to {budgetRow.campaign_name}{" "}
							immediately. The schedule keeps running, and its
							next window will override this.
						</p>
						<label className="mb-1 block text-xs text-content-muted">
							Budget (₹)
						</label>
						<input
							type="number"
							value={budgetAmount}
							onChange={(e) => setBudgetAmount(e.target.value)}
							className="mb-4 w-40 rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-content"
						/>
						<div className="flex justify-end gap-2">
							<Button
								variant="secondary"
								size="sm"
								onClick={() => setBudgetRow(null)}
							>
								Cancel
							</Button>
							<Button
								variant="brand"
								size="sm"
								disabled={
									!budgetAmount || setBudgetNow.isPending
								}
								onClick={handleSetBudget}
							>
								Set budget
							</Button>
						</div>
					</div>
				</div>
			)}

			{deleteRow && (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
					<div className="w-full max-w-sm rounded-lg border border-border bg-card p-5">
						<h3 className="mb-2 font-display text-base font-semibold text-content">
							Delete this automation?
						</h3>
						<p className="mb-4 text-sm text-content-muted">
							{deleteRow.kind === "campaign"
								? deleteRow.name || deleteRow.campaign_name
								: `${deleteRow.keyword} · ${deleteRow.campaign_name}`}{" "}
							will stop running and can't be recovered.
						</p>
						<div className="flex justify-end gap-2">
							<Button
								variant="secondary"
								size="sm"
								onClick={() => setDeleteRow(null)}
							>
								Cancel
							</Button>
							<Button
								variant="danger"
								size="sm"
								onClick={() => handleDelete(deleteRow)}
							>
								Delete
							</Button>
						</div>
					</div>
				</div>
			)}
		</div>
	);
};
