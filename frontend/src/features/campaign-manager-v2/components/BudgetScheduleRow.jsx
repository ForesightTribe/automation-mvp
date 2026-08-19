import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { formatCurrency } from "../../../lib/format";
import { AddBudgetRuleForm } from "./AddBudgetRuleForm";
import { EditBudgetScheduleForm } from "./EditBudgetScheduleForm";
import { JobStatus } from "./JobStatus";
import {
	Action,
	ConfirmDelete,
	Chevron,
	Fact,
	Identity,
	RowShell,
} from "./ScheduleRowParts";
import { StatusBadge } from "./StatusBadge";
import { DateWindow, TimeRange, WeekPills, timingOf } from "./TimingDisplay";
import { describeTiming } from "./TimingFields";

/** One scheduled window inside an automation: its budget, when it runs, and its bounds. */
const WindowRow = ({ rule, onEdit, onRemove }) => {
	const t = timingOf(rule);
	return (
		<li
			title={describeTiming(rule)}
			className="grid items-center gap-x-4 gap-y-2 rounded-lg bg-card px-3 py-2 md:grid-cols-[6.5rem_5.5rem_8.5rem_9rem_minmax(0,1fr)_auto]"
		>
			<StatusBadge status={rule.status} />
			<span className="text-sm font-semibold text-content tabular-nums">
				{formatCurrency(rule.budget)}
			</span>
			<span className="text-xs text-content">
				{t.type === "once" ? (
					<span className="text-content-muted">One-time</span>
				) : (
					<WeekPills days={t.days} />
				)}
			</span>
			<span className="text-xs text-content">
				<TimeRange start={t.start_time} end={t.end_time} />
			</span>
			<span className="text-xs text-content-muted">
				{t.type === "once" ? (
					<DateWindow from={t.date} to={null} />
				) : (
					<DateWindow from={t.start_date} to={t.end_date} />
				)}
			</span>
			<span className="flex shrink-0 items-center gap-3 md:justify-end">
				<Action tone="primary" onClick={onEdit}>
					Edit
				</Action>
				<Action tone="danger" onClick={onRemove}>
					Remove
				</Action>
			</span>
		</li>
	);
};

/**
 * A budget automation as one wide row: which campaign, the default budget, what the
 * windows are worth, and how many there are. Expanding shows every window in full — no
 * truncated day lists or clipped times — plus the schedule's own controls, and collapsing
 * cancels whatever form was open inside it.
 */
export const BudgetScheduleRow = ({
	schedule,
	onReset,
	resetJob,
	onDelete,
	onDeleteRule,
}) => {
	const [open, setOpen] = useState(false);
	const [mode, setMode] = useState(null); // null | "schedule" | "add" | rule.id

	const openWith = (next) => {
		setOpen(true);
		setMode(next);
	};
	const done = () => setMode(null);

	// Collapsing the row cancels whatever form was open in it. Without this the mode
	// outlives the collapse, so reopening the row dropped you straight back into a
	// half-filled edit form instead of the windows — the row looked stuck.
	const toggle = () => {
		if (open) setMode(null);
		setOpen(!open);
	};

	const active = schedule.rules.find((r) => r.status === "running");
	const count = schedule.rules.length;

	// What the windows are worth. Showing ONLY the live amount left the column reading "—"
	// on every row for most of the day — accurate, and useless. So it falls back to what
	// the windows hold (one amount, or the spread across several) and says "in force now"
	// only when a window is actually open. The "is it open" call stays server-side: the
	// API computes each rule's status in IST, which browser-local time can't be trusted to
	// reproduce.
	const amounts = schedule.rules.map((r) => r.budget);
	const low = amounts.length ? Math.min(...amounts) : null;
	const high = amounts.length ? Math.max(...amounts) : null;
	const windowBudget = active
		? formatCurrency(active.budget)
		: count === 0
			? "—"
			: low === high
				? formatCurrency(low)
				: `${formatCurrency(low)} – ${formatCurrency(high)}`;
	const windowHint = active
		? "in force right now"
		: count === 0
			? "no windows set"
			: count === 1
				? "while its window is open"
				: `across ${count} windows`;

	const label = schedule.name || schedule.campaign_name;
	const subtitle = schedule.name
		? `${schedule.campaign_name} · #${schedule.campaign_id}`
		: `#${schedule.campaign_id} · ${schedule.platform}`;

	return (
		<RowShell
			onToggle={toggle}
			header={
				<>
					<Identity
						className="lg:col-span-4"
						badge={<StatusBadge status={schedule.status} />}
						title={label}
						subtitle={subtitle}
					/>
					<span className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:contents">
						<Fact
							className="lg:col-span-2"
							label="Default budget"
							value={formatCurrency(schedule.default_budget)}
							hint="outside every window"
						/>
						<Fact
							className="lg:col-span-2"
							label="Budget during window"
							value={windowBudget}
							hint={windowHint}
						/>
						<Fact
							className="lg:col-span-1"
							label="Windows"
							value={count}
							hint={
								schedule.stop_after_window ? (
									<span
										title="The campaign is stopped when a window ends and started again at the next one."
										className="inline-block rounded-full bg-primary-soft px-1.5 py-px text-[10px] font-semibold text-primary"
									>
										ON/OFF
									</span>
								) : (
									"budget only"
								)
							}
						/>
					</span>
				</>
			}
			actions={
				<>
					<Button
						size="sm"
						variant="secondary"
						onClick={() => openWith("add")}
					>
						+ Window
					</Button>
					<Button
						size="sm"
						variant="ghost"
						onClick={() => openWith("schedule")}
					>
						Edit
					</Button>
					<Chevron
						open={open}
						onClick={toggle}
						label={open ? "Hide windows" : "Show windows"}
					/>
				</>
			}
		>
			{open &&
				(mode === "schedule" ? (
					<EditBudgetScheduleForm schedule={schedule} onDone={done} />
				) : (
					<>
						<p className="mb-2 text-[10px] font-semibold tracking-wide text-content-subtle uppercase">
							Windows
						</p>
						<ul className="space-y-1.5">
							{count === 0 && (
								<li className="rounded-lg bg-card px-3 py-2 text-xs text-content-subtle">
									No windows yet — the campaign always runs at
									its default budget.
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
									<WindowRow
										key={r.id}
										rule={r}
										onEdit={() => setMode(r.id)}
										onRemove={() => onDeleteRule(r.id)}
									/>
								),
							)}
						</ul>

						{mode === "add" && (
							<div className="mt-2.5">
								<AddBudgetRuleForm
									scheduleId={schedule.id}
									onDone={done}
								/>
							</div>
						)}

						<p className="mt-3 text-xs text-content-muted">
							Outside every window this campaign runs at its{" "}
							{formatCurrency(schedule.default_budget)} default
							budget.
							{schedule.stop_after_window
								? " ON/OFF is on, so it is stopped when a window ends and started again at the next one."
								: ""}
						</p>

						<div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-border/70 pt-3">
							<Action
								tone="primary"
								onClick={() => setMode("add")}
							>
								+ Window
							</Action>
							<Action onClick={() => setMode("schedule")}>
								Edit schedule
							</Action>
							<Action
								onClick={() => onReset(schedule.id)}
								disabled={schedule.state !== "active"}
							>
								Reset
							</Action>
							<span className="ml-auto">
								<ConfirmDelete
									onConfirm={() => onDelete(schedule.id)}
								>
									Delete automation
								</ConfirmDelete>
							</span>
						</div>

						{resetJob?.scheduleId === schedule.id && (
							<div className="mt-2.5">
								<JobStatus jobId={resetJob.jobId} />
							</div>
						)}
					</>
				))}
		</RowShell>
	);
};
