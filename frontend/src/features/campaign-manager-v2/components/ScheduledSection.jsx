import { useEffect, useState } from "react";
import { Card } from "../../../components/ui/Card";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { Loading } from "../../../components/feedback/Loading";
import {
	useBidRules,
	useBudgetSchedules,
	useDeleteBidRule,
	useDeleteBudgetRule,
	useDeleteBudgetSchedule,
	useResetBudgetSchedule,
	useSetBidState,
} from "../hooks";
import { BidRuleRow } from "./BidRuleRow";
import { BudgetScheduleRow } from "./BudgetScheduleRow";
import { ScheduledFilters } from "./ScheduledFilters";

/** Everything one row can be found by: its label, its campaign, its keyword, its id. */
const haystack = (x) =>
	[x.name, x.campaign_name, x.keyword, String(x.campaign_id)]
		.filter(Boolean)
		.join(" ")
		.toLowerCase();

/** A collapsible group of rows, with its own count and a live "running now" read-out so a
 *  collapsed group still says whether anything is happening inside it. A group reopens
 *  itself when a filter is switched on — hiding a match behind a collapsed header is the
 *  one way a search can lie. */
const Group = ({ title, items, total, running, filtered, empty, children }) => {
	const [open, setOpen] = useState(true);

	useEffect(() => {
		if (filtered) setOpen(true);
	}, [filtered]);

	return (
		<section>
			<button
				type="button"
				onClick={() => setOpen((v) => !v)}
				aria-expanded={open}
				className="flex w-full items-center gap-2.5 border-b border-border pb-2 text-left"
			>
				<span
					className={`text-base leading-none text-content-subtle transition-transform ${open ? "rotate-90" : ""}`}
				>
					›
				</span>
				<span className="font-display text-sm font-semibold text-content">
					{title}
				</span>
				<span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-content-muted">
					{items}
					{items !== total && ` of ${total}`}
				</span>
				<span className="ml-auto text-xs text-content-muted">
					{running > 0
						? `${running} running now`
						: total > 0
							? "none running now"
							: ""}
				</span>
			</button>

			{open && (
				<div className="pt-3">
					{items === 0 ? (
						<p className="rounded-lg border border-dashed border-border px-4 py-5 text-center text-xs text-content-subtle">
							{empty}
						</p>
					) : (
						children
					)}
				</div>
			)}
		</section>
	);
};

/**
 * Everything currently scheduled — budget automations and bid rules — as two collapsible
 * groups of full-width rows, over one shared toolbar (search + status).
 *
 * This used to be a third-column pane, which on a laptop left each row about 290px: every
 * campaign name, weekday list and time window was truncated, and the edit forms rendered
 * inside that same sliver. It now spans the page below the on-demand cards, so a row can
 * afford aligned columns and its full names, and it grows into the extra width on a
 * monitor instead of pinning itself to a narrow column.
 */
export const ScheduledSection = () => {
	const budgets = useBudgetSchedules();
	const bids = useBidRules();
	const delSchedule = useDeleteBudgetSchedule();
	const delRule = useDeleteBudgetRule();
	const reset = useResetBudgetSchedule();
	const delBid = useDeleteBidRule();
	const setBidState = useSetBidState();
	const [resetJob, setResetJob] = useState(null);
	const [query, setQuery] = useState("");
	const [status, setStatus] = useState("");

	const doReset = (scheduleId) =>
		reset.mutate(scheduleId, {
			onSuccess: (data) =>
				setResetJob({ scheduleId, jobId: data.job_id }),
		});

	const loading = budgets.isLoading || bids.isLoading;
	const error = budgets.error || bids.error;

	const allBudgets = budgets.data ?? [];
	const allBids = bids.data ?? [];
	const empty = allBudgets.length === 0 && allBids.length === 0;

	// Every search term must match somewhere, so "cola 500" narrows rather than widens.
	const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
	const keep = (x) => {
		if (status && x.status !== status) return false;
		if (!terms.length) return true;
		const hay = haystack(x);
		return terms.every((t) => hay.includes(t));
	};

	const filtering = Boolean(terms.length || status);
	const shownBudgets = allBudgets.filter(keep);
	const shownBids = allBids.filter(keep);
	const running = (list) => list.filter((x) => x.status === "running").length;

	const clear = () => {
		setQuery("");
		setStatus("");
	};

	const noMatch = (what) =>
		filtering ? `No ${what} match these filters.` : `No ${what} yet.`;

	return (
		<Card title="Scheduled automations">
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
				<p className="rounded-lg border border-dashed border-border bg-surface p-8 text-center text-sm text-content-muted">
					Nothing scheduled yet. Create a budget or bid automation to
					see it here.
				</p>
			) : (
				<>
					<ScheduledFilters
						query={query}
						onQuery={setQuery}
						status={status}
						onStatus={setStatus}
						active={filtering}
						onClear={clear}
					/>

					<div className="space-y-6">
						<Group
							title="Budget schedules"
							items={shownBudgets.length}
							total={allBudgets.length}
							running={running(allBudgets)}
							filtered={filtering}
							empty={noMatch("budget automations")}
						>
							<ul className="space-y-2.5">
								{shownBudgets.map((s) => (
									<BudgetScheduleRow
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
						</Group>

						<Group
							title="Bidding rules"
							items={shownBids.length}
							total={allBids.length}
							running={running(allBids)}
							filtered={filtering}
							empty={noMatch("bid automations")}
						>
							<ul className="space-y-2.5">
								{shownBids.map((r) => (
									<BidRuleRow
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
						</Group>

						<p className="text-[11px] text-content-subtle">
							All times are IST.
						</p>
					</div>
				</>
			)}
		</Card>
	);
};
