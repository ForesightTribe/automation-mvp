import { formatDateTime } from "../../../lib/format";
import { ACTIVE_JOB_STATUSES, useRecentActions } from "../hooks";

/**
 * What you recently asked for, above the record of what the engines did.
 *
 * ⚠️ A different SOURCE from the history below it, and that is the whole reason it exists.
 * History is the run log — written when a run ENDS. So it can never show you a change that
 * is still happening, and for the first seconds-to-minutes after you click something there
 * is simply nothing there to see. This reads the job queue instead, where a row exists from
 * the moment the action is queued.
 *
 * Person-triggered only (the server filters): the hourly engines and the reconciler are
 * excluded, so the one line you are waiting on is not buried under background work. That
 * work still appears in the history below — it is real, it is just not something you asked
 * for just now.
 *
 * Finished actions STAY here rather than disappearing, because not every job leaves a trace
 * below: a catalogue refresh never writes a history row, and an engine tick that changed
 * nothing deliberately does not either. A row that vanished into nothing would read as a
 * failure. Resolving in place says what happened instead.
 */

const TONE = {
	pending: "text-content-muted",
	running: "text-content-muted",
	success: "text-success",
	failed: "text-danger",
};

const WORD = {
	pending: "Queued",
	running: "Running",
	success: "Finished",
	failed: "Failed",
};

/** A campaign id is what the job carries; a name is what a person recognises. */
const subject = (action, nameOf) => {
	if (!action.campaign_id) return null;
	return nameOf?.(action.campaign_id) || `Campaign ${action.campaign_id}`;
};

export const ActivityList = ({ campaignNameOf }) => {
	const { data: actions } = useRecentActions();
	if (!actions?.length) return null;

	return (
		<section className="mb-5">
			<h3 className="mb-2 text-xs font-semibold tracking-wide text-content-subtle uppercase">
				Your recent actions
			</h3>
			<ul className="divide-y divide-border rounded-lg border border-border">
				{actions.map((a) => {
					const active = ACTIVE_JOB_STATUSES.has(a.status);
					const who = subject(a, campaignNameOf);
					return (
						<li
							key={a.id}
							className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
						>
							<div className="flex min-w-0 items-center gap-2">
								{active && (
									<span
										aria-hidden="true"
										className="h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-border border-t-primary"
									/>
								)}
								<span className="truncate text-content">
									{a.label || a.job_type}
									{who ? ` · ${who}` : ""}
								</span>
							</div>
							<div className="flex shrink-0 items-center gap-3">
								{/* The engine's own words when it failed. `error` is only set
								    when the process itself died; a write the marketplace
								    refused settles as "Finished", and its reason is in the
								    history rows filed under this action's run. */}
								{a.status === "failed" && a.error && (
									<span
										className="max-w-[18rem] truncate text-xs text-danger"
										title={a.error}
									>
										{a.error}
									</span>
								)}
								<span
									className={`text-xs ${TONE[a.status] ?? "text-content-muted"}`}
								>
									{WORD[a.status] ?? a.status}
								</span>
								<span className="text-xs text-content-subtle">
									{formatDateTime(a.created_at)}
								</span>
							</div>
						</li>
					);
				})}
			</ul>
		</section>
	);
};
