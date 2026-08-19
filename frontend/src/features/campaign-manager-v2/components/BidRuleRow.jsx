import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { AutomateBidForm } from "./AutomateBidForm";
import {
	Action,
	ConfirmDelete,
	Chevron,
	Fact,
	Identity,
	RowShell,
} from "./ScheduleRowParts";
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
 * measured and the rule's date bounds, plus edit and the pause/stop/delete controls.
 */
export const BidRuleRow = ({ rule, onAction, onDelete }) => {
	const [open, setOpen] = useState(false);
	const [editing, setEditing] = useState(false);
	const t = timingOf(rule);

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
						status={rule.status}
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
							onClick={() => onAction(rule.id, "resume")}
						>
							Resume
						</Button>
					)}
					{rule.state === "active" && (
						<Button
							size="sm"
							variant="secondary"
							onClick={() => onAction(rule.id, "pause")}
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
							{rule.state !== "stopped" && (
								<Action
									onClick={() => onAction(rule.id, "stop")}
								>
									Stop
								</Action>
							)}
							<span className="ml-auto">
								<ConfirmDelete
									onConfirm={() => onDelete(rule.id)}
								>
									Delete rule
								</ConfirmDelete>
							</span>
						</div>
					</>
				))}
		</RowShell>
	);
};
