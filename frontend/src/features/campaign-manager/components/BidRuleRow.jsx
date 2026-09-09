import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { AutomateBidForm } from "./AutomateBidForm";
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
import { DateWindow, WhenSummary, timingOf } from "./TimingDisplay";
import { describeTiming } from "./TimingFields";

const Detail = ({ label, children }) => (
	<div className="min-w-0">
		<dt className="text-[10px] font-medium tracking-wide text-content-subtle uppercase">
			{label}
		</dt>
		<dd className="mt-0.5 text-sm wrap-break-word text-content">
			{children}
		</dd>
	</div>
);

/**
 * A bid automation as one wide row: the keyword it chases, the position it targets, the
 * bid range it may spend inside, and when it runs. Expanding shows where position is
 * measured and the rule's date bounds, plus edit and the pause/reset/delete controls.
 *
 * ⚠️ **Pause does not lower the bid.** Freezing the automation stops it deciding; the
 * keyword keeps whatever bid it last climbed to until Reset, or until the next window
 * opens at the floor. The footer says so, because it is the one thing about these controls
 * that costs money if you assume otherwise.
 */
export const BidRuleRow = ({ rule, onAction, onReset, onDelete, resetJob }) => {
	const [open, setOpen] = useState(false);
	const [editing, setEditing] = useState(false);
	const [error, setError] = useState(null);
	const t = timingOf(rule);

	// Every action reports its own refusal. The API answers 409 with a sentence written
	// for the person reading it ("This automation is running right now — pause it first…"),
	// and axios normalises that into `error.message`, so showing it verbatim is both the
	// simplest and the most informative thing this row can do.
	const guard = { onError: (e) => setError(e.message) };
	const act = (action) => {
		setError(null);
		onAction(rule.id, action, guard);
	};
	const running = rule.status === "running";

	const openEdit = () => {
		setOpen(true);
		setEditing(true);
	};

	// Collapsing the row cancels the edit form, so reopening it shows the rule's details
	// rather than resuming a form you thought you had dismissed.
	const toggle = () => {
		if (open) setEditing(false);
		setOpen(!open);
	};

	const range = rule.max_bid
		? `₹${rule.min_bid} – ₹${rule.max_bid}`
		: `₹${rule.min_bid}+`;

	return (
		<RowShell
			onToggle={toggle}
			header={
				<>
					<Identity
						className="lg:col-span-4"
						badge={<StatusBadge status={rule.status} />}
						title={`“${rule.keyword}”`}
						subtitle={`${rule.campaign_name} · #${rule.campaign_id}`}
					/>
					<span className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:contents">
						<Fact
							className="lg:col-span-1"
							label="Target"
							value={`#${rule.target_position}`}
							hint={rule.match_type?.toLowerCase()}
						/>
						<Fact
							className="lg:col-span-2"
							label="Bid range"
							value={range}
							hint={rule.max_bid ? "per click" : "no ceiling set"}
						/>
						<Fact
							className="lg:col-span-2"
							label="Runs"
							value={<WhenSummary rule={rule} />}
						/>
					</span>
				</>
			}
			actions={
				<>
					{rule.state === "paused" && (
						<Button
							size="sm"
							variant="secondary"
							onClick={() => act("resume")}
						>
							Resume
						</Button>
					)}
					{rule.state === "active" && (
						<Button
							size="sm"
							variant="secondary"
							onClick={() => act("pause")}
						>
							Pause
						</Button>
					)}
					<Button size="sm" variant="ghost" onClick={openEdit}>
						Edit
					</Button>
					<Chevron
						open={open}
						onClick={toggle}
						label={open ? "Hide details" : "Show details"}
					/>
				</>
			}
		>
			{open &&
				(editing ? (
					<AutomateBidForm
						editing={rule}
						onDone={() => setEditing(false)}
					/>
				) : (
					<>
						<dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
							<Detail label="Measured at">
								{rule.location_name || "—"}
							</Detail>
							<Detail label="Active between">
								{t.type === "once" ? (
									<span className="text-content-muted">
										One-time rule
									</span>
								) : (
									<DateWindow
										from={t.start_date}
										to={t.end_date}
									/>
								)}
							</Detail>
							<Detail label="Match type">
								{rule.match_type}
							</Detail>
							<Detail label="Schedule">
								<span title={describeTiming(rule)}>
									{describeTiming(rule)}
								</span>
							</Detail>
						</dl>

						<div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-border/70 pt-3">
							<Action tone="primary" onClick={openEdit}>
								Edit rule
							</Action>
							<Action
								disabled={running}
								title={
									running
										? "Pause it first — the next check would bid it straight back up."
										: `Put the bid back to its ₹${rule.min_bid} floor`
								}
								onClick={() => {
									setError(null);
									onReset(rule.id, guard);
								}}
							>
								Reset bid to floor
							</Action>
							{resetJob?.ruleId === rule.id && (
								<JobStatus jobId={resetJob.jobId} />
							)}
							<span className="ml-auto">
								<ConfirmDelete
									onConfirm={() => {
										setError(null);
										onDelete(
											{ ruleId: rule.id, reset: false },
											guard,
										);
									}}
									onConfirmAlt={() => {
										setError(null);
										onDelete(
											{ ruleId: rule.id, reset: true },
											guard,
										);
									}}
									altLabel="Reset & delete"
								>
									Delete rule
								</ConfirmDelete>
							</span>
						</div>

						{error && (
							<p className="mt-2 text-xs text-danger">{error}</p>
						)}

						<p className="mt-2 text-[11px] text-content-subtle">
							Pausing freezes the automation but leaves the bid
							where it is — use “Reset bid to floor” to bring it
							back down.
						</p>
					</>
				))}
		</RowShell>
	);
};
