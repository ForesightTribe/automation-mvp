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
import { JobStatus } from "./JobStatus";
import { StateBadge } from "./StateBadge";
import { describeTiming } from "./TimingFields";

// A uniform small text-action, so every card footer reads the same.
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
			className={`text-xs font-medium transition-colors disabled:opacity-40 disabled:hover:text-content-muted ${tones[tone]}`}
		>
			{children}
		</button>
	);
};

// Two-step delete so a stray click can't nuke a schedule (relevant while a run is live).
const ConfirmDelete = ({ onConfirm }) => {
	const [armed, setArmed] = useState(false);
	if (!armed) {
		return (
			<Action tone="danger" onClick={() => setArmed(true)}>
				Delete
			</Action>
		);
	}
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

const Footer = ({ children }) => (
	<div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border/70 pt-2.5">
		{children}
	</div>
);

const CampaignLine = ({ name, id }) => (
	<p className="truncate text-xs text-content-muted">
		{name || `campaign ${id}`} <span className="text-content-subtle">· #{id}</span>
	</p>
);

// ── Budget automation row ────────────────────────────────────────────────────

const BudgetItem = ({ schedule, onReset, resetJob, onDelete, onDeleteRule }) => {
	const [addWindow, setAddWindow] = useState(false);
	return (
		<li className="rounded-lg border border-border bg-surface p-3.5">
			<div className="flex items-start justify-between gap-2">
				<div className="min-w-0">
					<div className="flex items-center gap-2">
						<span className="truncate text-sm font-semibold text-content">
							{schedule.name || schedule.campaign_name}
						</span>
						<StateBadge state={schedule.state} />
					</div>
					<CampaignLine name={schedule.campaign_name} id={schedule.campaign_id} />
				</div>
				<span className="shrink-0 rounded-md bg-card px-2 py-1 text-xs font-medium text-content">
					{formatCurrency(schedule.default_budget)}
					<span className="ml-1 text-content-subtle">default</span>
				</span>
			</div>

			{schedule.rules.length > 0 && (
				<ul className="mt-2.5 space-y-1">
					{schedule.rules.map((r) => (
						<li
							key={r.id}
							className="flex items-center justify-between gap-2 rounded-md bg-card px-2.5 py-1.5 text-xs"
						>
							<span className="min-w-0 truncate text-content">
								<span className="font-semibold">{formatCurrency(r.budget)}</span>
								<span className="text-content-muted"> · {describeTiming(r)}</span>
							</span>
							<Action tone="danger" onClick={() => onDeleteRule(r.id)}>
								remove
							</Action>
						</li>
					))}
				</ul>
			)}

			{resetJob?.scheduleId === schedule.id && (
				<div className="mt-2">
					<JobStatus jobId={resetJob.jobId} />
				</div>
			)}

			{addWindow ? (
				<div className="mt-3">
					<AddBudgetRuleForm scheduleId={schedule.id} onDone={() => setAddWindow(false)} />
				</div>
			) : (
				<Footer>
					<Action tone="primary" onClick={() => setAddWindow(true)}>
						+ Window
					</Action>
					<Action onClick={() => onReset(schedule.id)} disabled={schedule.state !== "active"}>
						Reset
					</Action>
					<ConfirmDelete onConfirm={() => onDelete(schedule.id)} />
				</Footer>
			)}
		</li>
	);
};

// ── Bid automation row ───────────────────────────────────────────────────────

const BidItem = ({ rule, onAction, onDelete }) => (
	<li className="rounded-lg border border-border bg-surface p-3.5">
		<div className="flex items-start justify-between gap-2">
			<div className="min-w-0">
				<div className="flex items-center gap-2">
					<span className="truncate text-sm font-semibold text-content">{rule.keyword}</span>
					<StateBadge state={rule.state} />
				</div>
				<CampaignLine name={rule.campaign_name} id={rule.campaign_id} />
			</div>
			<span className="shrink-0 rounded-md bg-card px-2 py-1 text-xs font-medium text-content">
				→ #{rule.target_position}
			</span>
		</div>

		<p className="mt-1.5 text-xs text-content-subtle">
			₹{rule.min_bid}–{rule.max_bid}
			{rule.location_name ? ` · ${rule.location_name}` : ""} · {describeTiming(rule)}
		</p>

		<Footer>
			{rule.state === "paused" && (
				<Action tone="primary" onClick={() => onAction(rule.id, "resume")}>
					Resume
				</Action>
			)}
			{rule.state === "active" && (
				<Action onClick={() => onAction(rule.id, "pause")}>Pause</Action>
			)}
			{rule.state !== "stopped" && (
				<Action onClick={() => onAction(rule.id, "stop")}>Stop</Action>
			)}
			<ConfirmDelete onConfirm={() => onDelete(rule.id)} />
		</Footer>
	</li>
);

// ── The pane ─────────────────────────────────────────────────────────────────

const Section = ({ title, count, children }) => (
	<div>
		<h3 className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide text-content-muted uppercase">
			{title}
			<span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-content-muted">{count}</span>
		</h3>
		{children}
	</div>
);

/** Right-hand pane: everything currently scheduled — budget automations and bid
 *  automations — each with its inline controls (reset / pause / resume / stop / delete).
 *  Mutations are optimistic (see hooks), so rows update the instant you click. */
export const ScheduledPane = () => {
	const budgets = useBudgetSchedules();
	const bids = useBidRules();
	const delSchedule = useDeleteBudgetSchedule();
	const delRule = useDeleteBudgetRule();
	const reset = useResetBudgetSchedule();
	const delBid = useDeleteBidRule();
	const setBidState = useSetBidState();
	const [resetJob, setResetJob] = useState(null); // { scheduleId, jobId }

	const doReset = (scheduleId) =>
		reset.mutate(scheduleId, {
			onSuccess: (data) => setResetJob({ scheduleId, jobId: data.job_id }),
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
					Nothing scheduled yet. Create a budget or bid automation to see it here.
				</p>
			) : (
				<div className="space-y-5 lg:max-h-[calc(100vh-8rem)] lg:overflow-y-auto lg:pr-1">
					<Section title="Budget" count={budgets.data?.length ?? 0}>
						{budgets.data?.length ? (
							<ul className="space-y-2.5">
								{budgets.data.map((s) => (
									<BudgetItem
										key={s.id}
										schedule={s}
										onReset={doReset}
										resetJob={resetJob}
										onDelete={(id) => delSchedule.mutate(id)}
										onDeleteRule={(id) => delRule.mutate(id)}
									/>
								))}
							</ul>
						) : (
							<p className="text-xs text-content-subtle">No budget automations.</p>
						)}
					</Section>

					<Section title="Bidding" count={bids.data?.length ?? 0}>
						{bids.data?.length ? (
							<ul className="space-y-2.5">
								{bids.data.map((r) => (
									<BidItem
										key={r.id}
										rule={r}
										onAction={(ruleId, action) => setBidState.mutate({ ruleId, action })}
										onDelete={(id) => delBid.mutate(id)}
									/>
								))}
							</ul>
						) : (
							<p className="text-xs text-content-subtle">No bid automations.</p>
						)}
					</Section>
				</div>
			)}
		</Card>
	);
};
