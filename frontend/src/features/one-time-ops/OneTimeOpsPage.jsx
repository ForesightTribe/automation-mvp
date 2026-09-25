import { useMemo, useState } from "react";
import { IndianRupee, RefreshCw, Search } from "lucide-react";
import { PageHeader } from "../../components/ui/PageHeader";
import { Button } from "../../components/ui/Button";
import { Select } from "../../components/ui/Select";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { CampaignStatusBadge } from "../../components/ui/CampaignStatusBadge";
import { DataTable } from "../../components/ui/DataTable";
import { Toggle } from "../../components/ui/Toggle";
import { Loading } from "../../components/feedback/Loading";
import { ErrorState } from "../../components/feedback/ErrorState";
import { EmptyState } from "../../components/feedback/EmptyState";
import { formatCurrency, formatNumber } from "../../lib/format";
import { CampaignDrawer } from "./components/CampaignDrawer";
import { useAutomationMarketplace } from "../../context/MarketplaceContext";
import {
	canWriteBudget,
	holdReason,
	isEndedState,
	isLiveState,
} from "../../lib/marketplaces";
import {
	useCampaigns,
	useLastVerdict,
	useSetBudget,
	useSetActivation,
	useRefreshCampaigns,
	useJob,
} from "./hooks";

/**
 * One-time operations — the immediate half of campaign control.
 *
 * Everything here happens the MOMENT it is confirmed. That is the whole distinction from
 * Ad Automation next door: an automation describes what should happen on a schedule and
 * can be paused before it ever fires, while a button on this page reaches the live ad
 * account straight away and there is no undo. Keeping the two apart is what stops an
 * immediate write sitting one mis-click away from a row someone is only reading.
 *
 * Three operations, all of them one-off: set a budget, start a campaign, stop a campaign.
 *
 * ⚠️ The engine is the authority on whether an operation is allowed. Terminal states,
 * budget bounds and rate limits are checked on the VM against a fresh read of the account,
 * not here — so this page enqueues and reports, and only refuses the cases that are
 * meaningless by definition (starting a campaign that has completed).
 */

/**
 * Every decision below reads `CampaignRow.state` — running / paused / held / ended / draft,
 * what the status MEANS — never the marketplace's raw word, which differs per marketplace
 * (ZC-E4). A HELD campaign (Blinkit ON_HOLD, Zepto out of budget or wallet) is still live:
 * it shows as on, can be stopped, and takes a budget — there is nothing to start.
 *
 * Budget writes: the same rule the scheduler applies (`can_write_budget` in budget.py). A
 * live campaign takes one everywhere; a PAUSED one only where the marketplace accepts it
 * (Zepto, ZC-C11). The one-off engine path attempts the write, takes the refusal and still
 * exits cleanly — the job reports success while the run log records `skip`. Refusing here
 * is the difference between "you cannot do that yet" and a change that silently never
 * happened.
 */
const STATUS_OPTIONS = [
	["", "All statuses"],
	["running", "Running"],
	["paused", "Stopped"],
	["held", "On hold"],
	["draft", "Draft"],
	["ended", "Ended"],
];

/**
 * What a job is doing, and then what it actually DID.
 *
 * ⚠️ Two different questions. `status: success` says the job ran; whether the write
 * landed is the engine's verdict in the run log, and a refused write exits cleanly.
 * Reporting the first as though it answered the second is how a budget that never
 * changed reads as "Done".
 */
const JobLine = ({ job, mpName }) => {
	const { data: jobRow } = useJob(job?.id);
	const status = jobRow?.status ?? "pending";
	const settled = status === "success" || status === "failed";
	const { data: verdict } = useLastVerdict(job?.campaignId, settled);

	if (!job) return null;

	if (!settled)
		return (
			<span className="inline-flex items-center gap-2 text-xs text-content-muted">
				<span className="h-3 w-3 animate-spin rounded-full border-2 border-border border-t-brand" />
				{status === "running" ? "Applying…" : "Queued…"}
			</span>
		);

	if (status === "failed")
		return (
			<span className="text-xs text-danger">
				Failed{jobRow?.error ? `: ${jobRow.error}` : ""}
			</span>
		);

	// Settled, so the run log has the answer. Until it arrives, say nothing rather than
	// claim a result.
	if (!verdict)
		return <span className="text-xs text-content-muted">Checking…</span>;

	if (verdict.action === "apply")
		return (
			<span className="text-xs text-success">
				Applied
				{verdict.new_value != null
					? ` · now ${formatCurrency(verdict.new_value)}`
					: ""}
			</span>
		);

	return (
		<span className="text-xs text-warning">
			{mpName} did not accept this change, so nothing was altered.
		</span>
	);
};

export const OneTimeOpsPage = () => {
	const { data: campaigns, isLoading, error } = useCampaigns();
	// The one marketplace this page acts on — the navbar's choice (no "All" here).
	const {
		marketplace,
		name: mpName,
		minDailyBudget,
	} = useAutomationMarketplace();
	/**
	 * Why nothing on this row may be touched, or null. A campaign automations may not act on
	 * (Zepto Display / auto-bid, ZC-C3) is refused by the engine for one-off writes too, so
	 * the controls say so instead of queueing a write that comes back refused.
	 */
	const refusalOf = (c) =>
		c.automatable === false
			? c.not_automatable_reason ||
				`${mpName} campaigns of this type cannot be changed from here.`
			: null;
	const canSetBudget = (c) =>
		!refusalOf(c) && canWriteBudget(marketplace, c.state);
	const setBudget = useSetBudget();
	const setActivation = useSetActivation();
	const refresh = useRefreshCampaigns();

	const [query, setQuery] = useState("");
	const [status, setStatus] = useState("");
	const [confirm, setConfirm] = useState(null); // { op, row }
	const [amount, setAmount] = useState("");
	const [confirmError, setConfirmError] = useState(null);
	// The campaign travels with the job id: the verdict is read per campaign, and "which
	// campaign did I just act on" is not recoverable from the job alone.
	const [job, setJob] = useState(null);
	const [detail, setDetail] = useState(null);

	const rows = useMemo(() => {
		const q = query.trim().toLowerCase();
		return (campaigns ?? []).filter((c) => {
			if (status && c.state !== status) return false;
			if (!q) return true;
			return (
				c.name?.toLowerCase().includes(q) ||
				String(c.campaign_id).includes(q)
			);
		});
	}, [campaigns, query, status]);

	// Shared by the table and the drawer, so both reach the same confirmation.
	const canAct = (c) => !isEndedState(c.state) && !refusalOf(c) && c.state;

	const ask = (op, row) => {
		setConfirmError(null);
		// The budget field opens on what the campaign is already on, so the common edit is
		// a correction rather than typing a number from nothing.
		setAmount(op === "budget" ? String(row.daily_budget ?? "") : "");
		setConfirm({ op, row });
	};

	const run = async () => {
		const { op, row } = confirm;
		setConfirmError(null);
		try {
			const res =
				op === "budget"
					? await setBudget.mutateAsync({
							campaignId: row.campaign_id,
							budget: Number(amount),
						})
					: await setActivation.mutateAsync({
							campaignId: row.campaign_id,
							status: op === "start" ? "running" : "paused",
						});
			setJob({ id: res.job_id, campaignId: row.campaign_id });
			setConfirm(null);
		} catch (err) {
			setConfirmError(err.message);
		}
	};

	const onRefresh = async () => {
		try {
			const res = await refresh.mutateAsync();
			setJob({ id: res.job_id, campaignId: null });
		} catch (err) {
			setConfirmError(err.message);
		}
	};

	const columns = [
		{
			key: "name",
			label: "Campaign",
			// A button, not a row click: the row also carries a switch that writes to the
			// live account, and a click target the size of the row is how the wrong one
			// gets hit.
			render: (c) => (
				<button
					type="button"
					onClick={() => setDetail(c)}
					title="Open campaign details"
					className="group min-w-0 cursor-pointer text-left"
				>
					<div className="truncate font-medium text-content group-hover:text-brand group-hover:underline">
						{c.name || `Campaign ${c.campaign_id}`}
					</div>
					<div className="text-xs text-content-subtle">
						ID {c.campaign_id}
					</div>
				</button>
			),
		},
		{
			key: "status",
			label: "Status",
			render: (c) => <CampaignStatusBadge status={c.status} />,
		},
		{
			key: "daily_budget",
			label: "Daily budget",
			align: "right",
			// Unset sorts as 0 rather than sorting as text, so the 14 campaigns that
			// actually carry a budget group together at one end.
			sortValue: (c) => c.daily_budget ?? 0,
			// ⚠️ Blinkit reports a daily_budget for only a fraction of campaigns. "Not set"
			// is the honest reading of a missing one; rendering ₹0 would say the campaign is
			// capped at nothing, which is the opposite of what it means.
			render: (c) =>
				c.daily_budget ? (
					<span className="tabular-nums text-content">
						{formatCurrency(c.daily_budget)}
					</span>
				) : (
					<span className="text-xs text-content-subtle">Not set</span>
				),
		},
		{
			key: "budget_consumed",
			label: "Spend",
			align: "right",
			render: (c) => (
				<span className="tabular-nums text-content-muted">
					{formatCurrency(c.budget_consumed ?? 0)}
				</span>
			),
		},
		{
			key: "impressions",
			label: "Impressions",
			align: "right",
			render: (c) => (
				<span className="tabular-nums text-content-muted">
					{formatNumber(c.impressions ?? 0)}
				</span>
			),
		},
		{
			key: "ad_sales",
			label: "Ad sales",
			align: "right",
			render: (c) => (
				<span className="tabular-nums text-content-muted">
					{formatCurrency(c.ad_sales ?? 0)}
				</span>
			),
		},
		{
			key: "atc",
			label: "Adds to cart",
			align: "right",
			render: (c) => (
				<span className="tabular-nums text-content-muted">
					{formatNumber(c.atc ?? 0)}
				</span>
			),
		},
		{
			key: "quantities_sold",
			label: "Units",
			align: "right",
			render: (c) => (
				<span className="tabular-nums text-content-muted">
					{formatNumber(c.quantities_sold ?? 0)}
				</span>
			),
		},
		{
			key: "roas",
			label: "ROAS",
			align: "right",
			render: (c) => (
				<span className="tabular-nums text-content-muted">
					{c.roas ? `${c.roas.toFixed(2)}x` : "—"}
				</span>
			),
		},
		{
			key: "ops",
			label: "One-time actions",
			align: "right",
			sortable: false,
			// One switch rather than two buttons: running or not is a single state, and a
			// pair of buttons implies two independent things you could do to it. The
			// switch also shows the current state without being read, which the buttons
			// only did by omission.
			render: (c) => {
				const live = isLiveState(c.state);
				const refused = refusalOf(c);
				const blocked =
					refused ??
					(isEndedState(c.state)
						? `This campaign has ended. ${mpName} treats that as final, so it cannot be started again.`
						: !c.state
							? "Campaign state unknown"
							: null);
				const held =
					c.state === "held" ? holdReason(c.status, mpName) : null;
				return (
					<div className="flex items-center justify-end gap-3">
						{/* Stays clickable even when the platform will not accept the change.
						    A disabled control can only hint, and the reason here is worth a
						    sentence: the dialog says why and offers the way forward, rather
						    than leaving a dead button and a tooltip. */}
						<Button
							size="xs"
							variant="secondary"
							disabled={Boolean(refused)}
							title={refused ?? undefined}
							onClick={() => ask("budget", c)}
						>
							<IndianRupee size={12} /> Set budget
						</Button>
						{/* The title sits on a wrapper: a disabled button fires no mouse
						    events, so a tooltip on the switch itself would be invisible in
						    exactly the case that needs explaining. */}
						<span
							className="inline-flex"
							title={
								blocked ??
								(held
									? `${held} Stop it now to halt it completely.`
									: live
										? "Stop this campaign now"
										: "Start this campaign now")
							}
						>
							<Toggle
								on={live}
								disabled={Boolean(blocked)}
								aria-label={
									live
										? "Stop this campaign"
										: "Start this campaign"
								}
								onChange={() => ask(live ? "stop" : "start", c)}
							/>
						</span>
					</div>
				);
			},
		},
	];

	const copy = () => {
		if (!confirm) return { title: "", body: null };
		const { op, row } = confirm;
		const who = row.name || `Campaign ${row.campaign_id}`;
		if (op === "budget") {
			const amount_ = Number(amount);
			const valid =
				amount > "" && Number.isFinite(amount_) && amount_ > 0;
			// The marketplace's published minimum (Zepto ₹500); the API refuses below it.
			const belowMin =
				valid && minDailyBudget != null && amount_ < minDailyBudget;
			return {
				title: "Set this budget now?",
				confirmLabel: "Set budget",
				// Blocked, not hidden: the reader came here to do something, and being told
				// what stands in the way — and what to do about it — beats a control that
				// simply does not respond.
				blocked: refusalOf(row)
					? refusalOf(row)
					: !canSetBudget(row)
						? `${who} is ${row.state === "ended" ? "ended" : "not running"}. ${mpName} only accepts a budget change on a campaign that is running${
								canWriteBudget(marketplace, "paused")
									? " or paused"
									: ""
							}, so this would be refused and nothing would change.${
								row.state === "ended"
									? ""
									: " Start the campaign first, then set its budget."
							}`
						: !valid
							? "Enter a daily budget above zero."
							: belowMin
								? `${mpName} does not accept a daily budget below ${formatCurrency(minDailyBudget)}.`
								: null,
				body: !canSetBudget(row) ? (
					<>Changing the daily budget for {who}.</>
				) : valid ? (
					<>
						{who} goes to {formatCurrency(amount_)} a day,
						immediately
						{row.state === "paused"
							? " — it stays stopped; the new budget applies when it is started"
							: ""}
						. This is a one-off push: any budget automation on this
						campaign will still move it at its next window.
					</>
				) : (
					<>
						Sets a new daily budget for {who}, applied immediately.
						A budget automation on this campaign will still move it
						at its next window.
					</>
				),
			};
		}
		if (op === "start")
			return {
				title: "Start this campaign now?",
				confirmLabel: "Start campaign",
				body: (
					<>
						{who} starts serving ads again on {mpName} and will
						begin spending. It keeps the budget it is already on.
					</>
				),
			};
		return {
			title: "Stop this campaign now?",
			confirmLabel: "Stop campaign",
			danger: true,
			body: (
				<>
					{who} stops serving ads on {mpName} immediately. Nothing
					else about it changes, and you can start it again from this
					page.
				</>
			),
		};
	};

	return (
		<div className="space-y-6">
			<PageHeader
				title="One-time operations"
				subtitle={`Change a budget, or start and stop a campaign on ${mpName}, right now. Every action here applies immediately. Switch marketplace in the bar above.`}
				actions={
					<div className="flex items-center gap-3">
						<JobLine job={job} mpName={mpName} />
						<Button
							size="sm"
							variant="secondary"
							disabled={refresh.isPending}
							onClick={onRefresh}
							title={`Re-read the campaign list from ${mpName}`}
						>
							<RefreshCw size={14} />
							{refresh.isPending
								? "Refreshing…"
								: "Refresh campaigns"}
						</Button>
					</div>
				}
			/>

			{/* Count left, controls right — the same shape as the Insights cards, so the
			    search box is in the place the reader has already learned. */}
			<div className="flex flex-wrap items-center justify-between gap-3">
				<span className="text-xs text-content-subtle">
					{rows.length} of {campaigns?.length ?? 0} campaigns
				</span>
				<div className="flex flex-wrap items-center gap-3">
					<Select
						value={status}
						options={STATUS_OPTIONS}
						onChange={setStatus}
						ariaLabel="Filter by status"
					/>
					<div className="relative">
						<Search
							size={14}
							className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-content-subtle"
						/>
						<input
							value={query}
							onChange={(e) => setQuery(e.target.value)}
							placeholder="Search name or ID"
							aria-label="Search campaigns"
							className="w-64 rounded-md border border-border bg-card py-1.5 pr-3 pl-8 text-sm text-content placeholder:text-content-subtle focus:border-brand focus:outline-none"
						/>
					</div>
				</div>
			</div>

			{isLoading && <Loading label="Loading campaigns…" />}
			{error && <ErrorState error={error} />}
			{!isLoading && !error && rows.length === 0 && (
				<EmptyState
					title="No campaigns match"
					message="Try a different search or status."
				/>
			)}
			{!isLoading && !error && rows.length > 0 && (
				<div className="overflow-hidden rounded-xl border border-border bg-card">
					<DataTable
						headClass="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-content-subtle"
						columns={columns}
						rows={rows}
						rowKey={(c) => c.campaign_id}
						maxHeight={560}
						minWidth={1240}
						pinLast
						defaultSort="budget_consumed"
					/>
				</div>
			)}

			<CampaignDrawer
				open={detail != null}
				campaign={detail}
				onClose={() => setDetail(null)}
				onAct={ask}
				canAct={canAct}
				canSetBudget={canSetBudget}
				refusalOf={refusalOf}
			/>

			<ConfirmDialog
				open={Boolean(confirm)}
				{...copy()}
				pending={setBudget.isPending || setActivation.isPending}
				error={confirmError}
				onCancel={() => setConfirm(null)}
				onConfirm={run}
			>
				{confirm?.op === "budget" && canSetBudget(confirm.row) && (
					<label className="mb-4 block">
						<span className="mb-1 block text-xs text-content-muted">
							Daily budget (₹)
							{minDailyBudget != null &&
								` · min ${formatCurrency(minDailyBudget)}`}
						</span>
						<input
							type="number"
							min="1"
							value={amount}
							onChange={(e) => setAmount(e.target.value)}
							className="w-40 rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-content focus:border-brand focus:outline-none"
						/>
					</label>
				)}
			</ConfirmDialog>
		</div>
	);
};
