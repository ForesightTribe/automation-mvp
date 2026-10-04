import {
	Pencil,
	Trash2,
	ScrollText,
	RotateCcw,
	Play,
	Pause,
} from "lucide-react";
import { DataTable } from "../../../components/ui/DataTable";
import { Tooltip } from "./Tooltip";
import { SchedulePopover } from "./SchedulePopover";
import { ChannelBadge } from "./ChannelBadge";
import { ActionsSummaryPills } from "./ActionsSummaryPills";
import { budgetScheduleTags, bidRuleTags } from "../automation";

/**
 * `disabled` keeps a control visible but inert. Tooltip listens on its wrapper span
 * rather than on the button, so a disabled one still explains itself on hover — a
 * disabled button emits no mouse events of its own.
 */
const IconButton = ({ icon: Icon, label, onClick, danger, disabled }) => (
	<Tooltip label={label}>
		<button
			type="button"
			aria-label={label}
			disabled={disabled}
			onClick={onClick}
			className={`rounded-md p-1.5 text-content-subtle transition-colors disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-content-subtle ${
				danger ? "hover:text-danger" : "hover:text-brand"
			} hover:bg-muted`}
		>
			<Icon size={14} />
		</button>
	</Tooltip>
);

/**
 * One row per automation, campaign schedules and keyword bid rules unified.
 * No row-selection checkboxes — bulk actions across campaigns/keywords isn't
 * built yet, so no UI implies it works. "Last Modified" stays off the table
 * too: neither BudgetScheduleOut nor BidRuleOut carries an updated-at, and
 * cross-referencing a partial history page would show a date that's
 * sometimes just wrong — worse than omitting it.
 */
export const AutomationsTable = ({
	rows,
	onEdit,
	onDelete,
	onToggle,
	onViewLog,
	onReset,
	onOpenCampaign,
	activeActionFor,
	// Pause, resume, reset, edit and delete all change live budgets and bids, so
	// they are admin-only. Execution logs and the campaign link stay available.
	canWrite = true,
}) => {
	const adminHint = canWrite
		? null
		: "Admin access required — ask an admin on your account.";
	const columns = [
		{
			key: "name",
			label: "Name",
			// The campaign name opens everything this account knows about that campaign. It is a
			// button rather than a row click so the row's own switches and icons stay reachable.
			render: (r) => (
				<button
					type="button"
					onClick={() => onOpenCampaign(r.campaign_id)}
					className="group/name text-left"
				>
					<div className="text-sm font-semibold text-content group-hover/name:text-brand">
						{r.kind === "campaign"
							? r.name || r.campaign_name
							: r.keyword}
					</div>
					<div className="text-xs text-content-subtle group-hover/name:underline">
						{r.campaign_name}
					</div>
				</button>
			),
		},
		{
			key: "platform",
			label: "Channel",
			render: (r) => <ChannelBadge platform={r.platform} />,
		},
		{
			key: "kind",
			label: "Type",
			render: (r) => (
				<span className="rounded-full border border-border px-2 py-0.5 text-xs font-medium text-content-muted">
					{r.kind === "campaign" ? "Campaign" : "Keyword"}
				</span>
			),
		},
		{
			key: "status",
			label: "Status",
			render: (r) => <SchedulePopover row={r} />,
		},
		{
			key: "summary",
			label: "Actions Summary",
			render: (r) => (
				<ActionsSummaryPills
					tags={
						r.kind === "campaign"
							? budgetScheduleTags(r)
							: bidRuleTags(r)
					}
				/>
			),
		},
		{
			key: "controls",
			label: "Controls",
			align: "right",
			render: (r) => {
				// An action of yours already running against this row. While one is, the
				// controls that would collide with it are inert rather than hidden — a
				// vanishing button reads as a bug, a disabled one that explains itself reads
				// as "wait". Edit and Execution logs stay live: neither writes to the
				// marketplace, and the logs are exactly what you want while waiting.
				const busy = activeActionFor?.(r);
				const busyLabel = busy
					? `${busy.label || "An action"} is ${busy.status === "pending" ? "queued" : "running"} for this — please wait`
					: null;
				return (
					<div className="flex justify-end gap-1">
						{busy && (
							<span
								title={busyLabel}
								aria-label={busyLabel}
								className="mr-1 inline-flex items-center"
							>
								<span className="h-3 w-3 animate-spin rounded-full border-2 border-border border-t-primary" />
							</span>
						)}
						{/* Every one of these opens a confirmation first. They act on the
					    AUTOMATION, never on the campaign: a campaign pause is something you
					    set up inside the automation, on a window's end. Calling both "pause"
					    without saying which is the most confusing thing on this screen, so
					    each label names what it touches.

					    Pause and resume are keyword-only because the engine has them only
					    for bid rules. A budget schedule is active or stopped, and Reset is
					    what stops it.

					    Neither shows on an automation whose windows have all passed. Nothing
					    will fire for it again, so there is nothing to freeze, and the engine
					    refuses the call. Reset stays available there on purpose: a rule
					    paused across its window end never got its de-escalation and its bid
					    is still sitting high. */}
						{r.kind === "keyword" && r.status !== "ended" && (
							<IconButton
								icon={r.status === "paused" ? Play : Pause}
								disabled={!canWrite}
								label={
									adminHint ??
									(r.status === "paused"
										? "Resume this automation"
										: "Pause this automation, the campaign keeps running")
								}
								onClick={() =>
									onToggle(
										r,
										r.status === "paused"
											? "resume"
											: "pause",
									)
								}
							/>
						)}
						{/* Reset means the same thing on both kinds: undo what the engine did and
					    put the value back where it started. On a campaign that is the default
					    budget and the automation stops for good; on a keyword it is the rule's
					    minimum bid and the rule stays. */}
						{!(r.kind === "campaign" && r.status === "stopped") && (
							<IconButton
								icon={RotateCcw}
								label={
									adminHint ??
									(busy
										? busyLabel
										: r.kind === "campaign"
											? "Stop and put the budget back"
											: "Put the bid back to the minimum")
								}
								disabled={Boolean(busy) || !canWrite}
								onClick={() => onReset(r)}
							/>
						)}
						{/* No campaign on/off and no "Set budget now" here. Both write to the live
					    account the moment they are clicked, and every row in this table acts on a
					    SCHEDULE instead. Keeping the two kinds apart is what stops an immediate
					    write sitting one mis-click away from a row someone is only reading; the
					    immediate ones live on the One-time ops page. */}
						<IconButton
							icon={Pencil}
							label={adminHint ?? "Edit"}
							disabled={!canWrite}
							onClick={() => onEdit(r)}
						/>
						<IconButton
							icon={ScrollText}
							label="Execution logs"
							onClick={() => onViewLog(r)}
						/>
						<IconButton
							icon={Trash2}
							label={adminHint ?? (busy ? busyLabel : "Delete")}
							danger
							disabled={Boolean(busy) || !canWrite}
							onClick={() => onDelete(r)}
						/>
					</div>
				);
			},
		},
	];

	return (
		<DataTable
			headClass="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-content-subtle"
			columns={columns}
			rows={rows}
			rowKey={(r) => `${r.kind}-${r.id}`}
			maxHeight={520}
			minWidth={900}
		/>
	);
};
