import {
	Pencil,
	Trash2,
	ScrollText,
	IndianRupee,
	CircleStop,
	Play,
	Pause,
} from "lucide-react";
import { DataTable } from "../../../components/ui/DataTable";
import { Tooltip } from "./Tooltip";
import { SchedulePopover } from "./SchedulePopover";
import { ChannelBadge } from "./ChannelBadge";
import { ActionsSummaryPills } from "./ActionsSummaryPills";
import { budgetScheduleTags, bidRuleTags } from "../automation";

const ToggleSwitch = ({ on, onChange, title, disabled = false }) => (
	<Tooltip label={title}>
		<button
			type="button"
			role="switch"
			aria-checked={on}
			aria-disabled={disabled}
			disabled={disabled}
			onClick={onChange}
			className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
				on ? "bg-success" : "bg-muted"
			} ${disabled ? "cursor-not-allowed opacity-45" : ""}`}
		>
			<span
				className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-card shadow-sm transition-transform ${
					on ? "translate-x-5" : "translate-x-0"
				}`}
			/>
		</button>
	</Tooltip>
);

const IconButton = ({ icon: Icon, label, onClick, danger }) => (
	<Tooltip label={label}>
		<button
			type="button"
			aria-label={label}
			onClick={onClick}
			className={`rounded-md p-1.5 text-content-subtle transition-colors hover:bg-muted ${
				danger ? "hover:text-danger" : "hover:text-brand"
			}`}
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
	onSetBudget,
	onStop,
	onActivate,
	campaignStatusOf,
	onOpenCampaign,
}) => {
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
			render: (r) => (
				<div className="flex justify-end gap-1">
					{/* Budget-only actions: a bid rule has no default budget to restore and
					    no one-off budget to push, so they'd be dead controls on a keyword row. */}
					{/* Pause / resume, and Stop. All three are real bid-rule verbs in the engine;
					    a budget schedule has none of them, which is why the on/off column is gone
					    and these are keyword-only. Stop ends the rule for good, whereas a pause resumes. */}
					{r.kind === "keyword" && (
						<IconButton
							icon={r.status === "paused" ? Play : Pause}
							label={
								r.status === "paused"
									? "Resume this automation"
									: "Pause this automation, the campaign keeps running"
							}
							onClick={() =>
								onToggle(
									r,
									r.status === "paused" ? "resume" : "pause",
								)
							}
						/>
					)}
					{/* These act on the AUTOMATION, not on the campaign. A campaign pause is set up
					    inside the automation, on a window's end. Naming both "pause" without saying
					    which is the single most confusing thing on this screen. */}
					{r.kind === "keyword" && r.status !== "stopped" && (
						<IconButton
							icon={CircleStop}
							label="Stop this automation permanently"
							onClick={() => onStop(r)}
						/>
					)}
					{/* Budget-only, and just the one: "Set budget now" is a deliberate push, whereas
					    "Reset to default" was a second budget verb sitting next to it doing almost
					    the same thing. Six icons per row was the noise. */}
					{r.kind === "campaign" && (
						<>
							{/* The CAMPAIGN's own on/off, showing the campaign's actual state rather
							    than the automation's. Unknown status (a campaign the list no longer
							    returns) locks the switch instead of guessing a direction, because flipping
							    the wrong way would stop a live campaign. */}
							{(() => {
								const st = campaignStatusOf?.(r.campaign_id);
								const live = st === "ACTIVE";
								return (
									<span className="mr-1 flex items-center gap-1.5">
										<span className="text-[11px] text-content-subtle">
											Campaign
										</span>
										<ToggleSwitch
											on={live}
											disabled={!st}
											title={
												!st
													? "Campaign state unknown. Use Refresh Campaigns"
													: live
														? "Stop this campaign now"
														: "Start this campaign now"
											}
											onChange={() =>
												onActivate(
													r,
													live ? "paused" : "running",
												)
											}
										/>
									</span>
								);
							})()}
							<IconButton
								icon={IndianRupee}
								label="Set budget now"
								onClick={() => onSetBudget(r)}
							/>
						</>
					)}
					<IconButton
						icon={Pencil}
						label="Edit"
						onClick={() => onEdit(r)}
					/>
					<IconButton
						icon={ScrollText}
						label="Execution logs"
						onClick={() => onViewLog(r)}
					/>
					<IconButton
						icon={Trash2}
						label="Delete"
						danger
						onClick={() => onDelete(r)}
					/>
				</div>
			),
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
