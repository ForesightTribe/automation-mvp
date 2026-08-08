import { useState } from "react";
import { Card } from "../../../components/ui/Card";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { Loading } from "../../../components/feedback/Loading";
import { formatCurrency } from "../../../lib/format";
import {
	useBidRules,
	useBudgetSchedules,
	useDeleteBidRule,
	useDeleteBudgetRule,
	useDeleteBudgetSchedule,
	useResetBudgetSchedule,
	useSetBidState,
} from "../hooks";
import { AddBudgetRuleForm } from "./AddBudgetRuleForm";
import { AutomateBidForm } from "./AutomateBidForm";
import { EditBudgetScheduleForm } from "./EditBudgetScheduleForm";
import { JobStatus } from "./JobStatus";
import { StatusBadge } from "./StatusBadge";
import { describeTiming } from "./TimingFields";

// A uniform small text-action so every footer reads the same.
const Action = ({ onClick, disabled, tone = "muted", children }) => {
	const tones = {
		muted: "text-content-muted hover:text-content",
		primary: "text-primary hover:text-primary-hover",
		danger: "text-content-subtle hover:text-danger",
	};
	return (
		<button
			type="button"
			onClick={onClick}
			disabled={disabled}
			className={`text-xs font-medium transition-colors disabled:opacity-40 ${tones[tone]}`}
		>
			{children}
		</button>
	);
};

const ConfirmDelete = ({ onConfirm }) => {
	const [armed, setArmed] = useState(false);
	if (!armed)
		return (
			<Action tone="danger" onClick={() => setArmed(true)}>
				Delete
			</Action>
		);
	return (
		<span className="inline-flex items-center gap-2">
			<button
				type="button"
				onClick={onConfirm}
				className="text-xs font-semibold text-danger hover:underline"
			>
				Confirm delete
			</button>
			<Action onClick={() => setArmed(false)}>cancel</Action>
		</span>
	);
};

const Chevron = ({ open }) => (
	<span
		className={`text-content-subtle transition-transform ${open ? "rotate-90" : ""}`}
	>
		›
	</span>
);

// A collapsed row: status + title on the left, a value chip + chevron on the right, and a
// muted one-line summary beneath. Clicking the header toggles the detail.
const Row = ({ status, title, chip, subtitle, open, onToggle, children }) => (
	<li className="rounded-lg border border-border bg-surface">
		<button
			type="button"
			onClick={onToggle}
			className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left"
		>
			<StatusBadge status={status} />
			<span className="min-w-0 flex-1">
				<span className="block truncate text-sm font-semibold text-content">
					{title}
				</span>
				<span className="block truncate text-xs text-content-muted">
					{subtitle}
				</span>
			</span>
			{chip && (
				<span className="shrink-0 text-xs font-medium text-content">
					{chip}
				</span>
			)}
			<Chevron open={open} />
		</button>
		{open && (
			<div className="border-t border-border/70 px-3.5 py-3">
				{children}
			</div>
		)}
	</li>
);

// ── Budget automation ────────────────────────────────────────────────────────

const BudgetItem = ({
	schedule,
	onReset,
	resetJob,
	onDelete,
	onDeleteRule,
}) => {
	const [open, setOpen] = useState(false);
	const [mode, setMode] = useState(null); // "schedule" | "add" | rule.id (editing a window)

	const done = () => setMode(null);
	const summary = `#${schedule.campaign_id} · ${schedule.rules.length} window${schedule.rules.length === 1 ? "" : "s"}`;
	// Campaign activation is a property of the automation, so it reads as one more fact
	// about it rather than a separate thing on the page.
	const onOff = schedule.stop_after_window ? " · on/off" : "";

	return (
		<Row
			status={schedule.status}
			title={schedule.name || schedule.campaign_name}
			chip={
				<span className="inline-flex items-center gap-1.5">
					{schedule.stop_after_window && (
						<span
							title="The campaign is stopped when a window ends and started again at the next one."
							className="rounded-full bg-primary-soft px-1.5 py-0.5 text-[10px] font-semibold text-primary"
						>
							ON/OFF
						</span>
					)}
					{`${formatCurrency(schedule.default_budget)} default`}
				</span>
			}
			subtitle={`${schedule.campaign_name} · ${summary}${onOff}`}
			open={open}
			onToggle={() => setOpen((v) => !v)}
		>
			{mode === "schedule" ? (
				<EditBudgetScheduleForm schedule={schedule} onDone={done} />
			) : (
				<>
					<ul className="space-y-1.5">
						{schedule.rules.length === 0 && (
							<li className="text-xs text-content-subtle">
								No windows — always the everyday budget.
							</li>
						)}
						{schedule.rules.map((r) =>
							mode === r.id ? (
								<li key={r.id}>
									<AddBudgetRuleForm
										scheduleId={schedule.id}
										editing={r}
										onDone={done}
									/>
								</li>
							) : (
								<li
									key={r.id}
									className="flex items-center justify-between gap-2 rounded-md bg-card px-2.5 py-1.5 text-xs"
								>
									<span className="flex min-w-0 items-center gap-2">
										<StatusBadge status={r.status} />
										<span className="min-w-0 truncate text-content">
											<span className="font-semibold">
												{formatCurrency(r.budget)}
											</span>
											<span className="text-content-muted">
												{" "}
												· {describeTiming(r)}
											</span>
										</span>
									</span>
									<span className="flex shrink-0 items-center gap-2.5">
										<Action
											tone="primary"
											onClick={() => setMode(r.id)}
										>
											edit
										</Action>
										<Action
											tone="danger"
											onClick={() => onDeleteRule(r.id)}
										>
											remove
										</Action>
									</span>
								</li>
							),
						)}
					</ul>

					{mode === "add" ? (
						<div className="mt-2">
							<AddBudgetRuleForm
								scheduleId={schedule.id}
								onDone={done}
							/>
						</div>
					) : (
						<div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border/70 pt-2.5">
							<Action
								tone="primary"
								onClick={() => setMode("add")}
							>
								+ Window
							</Action>
							<Action onClick={() => setMode("schedule")}>
								Edit
							</Action>
							<Action
								onClick={() => onReset(schedule.id)}
								disabled={schedule.state !== "active"}
							>
								Reset
							</Action>
							<ConfirmDelete
								onConfirm={() => onDelete(schedule.id)}
							/>
						</div>
					)}

					{resetJob?.scheduleId === schedule.id && (
						<div className="mt-2">
							<JobStatus jobId={resetJob.jobId} />
						</div>
					)}
				</>
			)}
		</Row>
	);
};

// ── Bid automation ───────────────────────────────────────────────────────────

const BidItem = ({ rule, onAction, onDelete }) => {
	const [open, setOpen] = useState(false);
	const [editing, setEditing] = useState(false);

	return (
		<Row
			status={rule.status}
			title={rule.keyword}
			chip={`→ #${rule.target_position}`}
			subtitle={`${rule.campaign_name} · #${rule.campaign_id} · ${describeTiming(rule)}`}
			open={open}
			onToggle={() => setOpen((v) => !v)}
		>
			{editing ? (
				<AutomateBidForm
					editing={rule}
					onDone={() => setEditing(false)}
				/>
			) : (
				<>
					<dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
						<dt className="text-content-subtle">Bid range</dt>
						<dd className="text-content">
							₹{rule.min_bid}–{rule.max_bid}
						</dd>
						<dt className="text-content-subtle">Measured at</dt>
						<dd className="truncate text-content">
							{rule.location_name || "—"}
						</dd>
						<dt className="text-content-subtle">When</dt>
						<dd className="truncate text-content">
							{describeTiming(rule)}
						</dd>
					</dl>
					<div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border/70 pt-2.5">
						<Action tone="primary" onClick={() => setEditing(true)}>
							Edit
						</Action>
						{rule.state === "paused" && (
							<Action onClick={() => onAction(rule.id, "resume")}>
								Resume
							</Action>
						)}
						{rule.state === "active" && (
							<Action onClick={() => onAction(rule.id, "pause")}>
								Pause
							</Action>
						)}
						{rule.state !== "stopped" && (
							<Action onClick={() => onAction(rule.id, "stop")}>
								Stop
							</Action>
						)}
						<ConfirmDelete onConfirm={() => onDelete(rule.id)} />
					</div>
				</>
			)}
		</Row>
	);
};

// ── The pane ─────────────────────────────────────────────────────────────────

const Section = ({ title, count, children }) => (
	<div>
		<h3 className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide text-content-muted uppercase">
			{title}
			<span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-content-muted">
				{count}
			</span>
		</h3>
		{children}
	</div>
);

/** Right-hand pane: everything scheduled, as compact collapsible rows. Each row shows a
 *  computed status (Running / Scheduled / Ended / Paused / Stopped); expand for windows,
 *  details, edit, and lifecycle controls. */
export const ScheduledPane = () => {
	const budgets = useBudgetSchedules();
	const bids = useBidRules();
	const delSchedule = useDeleteBudgetSchedule();
	const delRule = useDeleteBudgetRule();
	const reset = useResetBudgetSchedule();
	const delBid = useDeleteBidRule();
	const setBidState = useSetBidState();
	const [resetJob, setResetJob] = useState(null);

	const doReset = (scheduleId) =>
		reset.mutate(scheduleId, {
			onSuccess: (data) =>
				setResetJob({ scheduleId, jobId: data.job_id }),
		});

	const loading = budgets.isLoading || bids.isLoading;
	const error = budgets.error || bids.error;
	const empty = !budgets.data?.length && !bids.data?.length;

	return (
		<Card title="Scheduled" className="lg:sticky lg:top-6">
			{loading ? (
				<Loading />
			) : error ? (
				<ErrorState
					message={error?.message}
					onRetry={() => {
						budgets.refetch();
						bids.refetch();
					}}
				/>
			) : empty ? (
				<p className="rounded-lg border border-dashed border-border bg-surface p-6 text-center text-sm text-content-muted">
					Nothing scheduled yet. Create a budget or bid automation to
					see it here.
				</p>
			) : (
				<div className="space-y-5 lg:max-h-[calc(100vh-8rem)] lg:overflow-y-auto lg:pr-1">
					<Section title="Budget" count={budgets.data?.length ?? 0}>
						{budgets.data?.length ? (
							<ul className="space-y-2">
								{budgets.data.map((s) => (
									<BudgetItem
										key={s.id}
										schedule={s}
										onReset={doReset}
										resetJob={resetJob}
										onDelete={(id) =>
											delSchedule.mutate(id)
										}
										onDeleteRule={(id) =>
											delRule.mutate(id)
										}
									/>
								))}
							</ul>
						) : (
							<p className="text-xs text-content-subtle">
								No budget automations.
							</p>
						)}
					</Section>

					<Section title="Bidding" count={bids.data?.length ?? 0}>
						{bids.data?.length ? (
							<ul className="space-y-2">
								{bids.data.map((r) => (
									<BidItem
										key={r.id}
										rule={r}
										onAction={(ruleId, action) =>
											setBidState.mutate({
												ruleId,
												action,
											})
										}
										onDelete={(id) => delBid.mutate(id)}
									/>
								))}
							</ul>
						) : (
							<p className="text-xs text-content-subtle">
								No bid automations.
							</p>
						)}
					</Section>
				</div>
			)}
		</Card>
	);
};
