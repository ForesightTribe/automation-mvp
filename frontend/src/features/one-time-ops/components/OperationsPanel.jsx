import { Modal } from "../../../components/ui/Modal";
import { Button } from "../../../components/ui/Button";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { Loading } from "../../../components/feedback/Loading";
import { formatDateTime } from "../../../lib/format";
import {
	describeOutcome,
	isActive,
	useActionHistory,
	useRunOutcome,
} from "../../../lib/actions";
import { KIND_LABEL, outcomeOf, resultOf } from "../../../lib/runLog";
import { ONE_TIME_OPS } from "../api";

/**
 * Every operation ever started from this page, as a table — laid out like Ad Automation's
 * Execution logs and worded by the same `lib/runLog.js`, so an operation reads the same way
 * whichever of the two you look at it in.
 *
 * ONE ROW PER OPERATION, not per history row. That is the difference from Execution logs, and
 * it is why this can say "Queued" and "In progress": a row here is a job, which exists from
 * the moment you click, where a history row exists only once the run is over. Once the job
 * finishes, its row is filled in from the history rows that run wrote (found by `run_id`).
 *
 * ONLY this page's own operations (the server filters on the source this page tags its writes
 * with), and NO time limit — "Load older" pages back through the whole history. Paged because
 * the newest page is re-read while something runs, and only while the panel is open.
 */

// What kind of operation a job is, in Execution logs' words.
const OPERATION = {
	"cm.set_budget": KIND_LABEL.budget,
	"cm.set_activation": KIND_LABEL.activation,
	"cm.set_bid": KIND_LABEL.bid,
	"cm.sync_campaigns": "Campaign list refresh",
};

// The same rendering Execution logs uses for a change.
const changeOf = (r) =>
	r && (r.old_value != null || r.new_value != null)
		? `${r.old_value ?? "—"} → ${r.new_value ?? "—"}`
		: "—";

const Spinner = () => (
	<span
		aria-hidden="true"
		className="h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-border border-t-brand"
	/>
);

const TH = "px-3 py-2 text-left font-medium text-content-subtle";

/**
 * One operation's row. A component rather than inline JSX because it reads its own outcome —
 * once the job has finished — and a hook cannot be called inside a `.map`.
 */
const OperationRow = ({ action, campaignNameOf }) => {
	const done = action.status === "success";
	const { data: rows } = useRunOutcome(action.run_id, done);
	const active = isActive(action);
	// Most operations write exactly one history row. Several (a start that also moved the
	// budget) are summarised; none means the run found nothing to change.
	const only = rows?.length === 1 ? rows[0] : null;

	const who = action.campaign_id
		? campaignNameOf?.(action.campaign_id) ||
			`Campaign ${action.campaign_id}`
		: "All campaigns";

	// ── What happened, and why — and the one-word Result beside it ──
	let what;
	let why = null;
	let result;
	if (active) {
		const word = action.status === "pending" ? "Queued" : "In progress";
		what = (
			<span className="inline-flex items-center gap-1.5">
				<Spinner /> {word}
			</span>
		);
		result = { label: word, tone: "text-content-subtle" };
	} else if (action.status === "failed") {
		// The job itself died (a crash, a timeout, an expired session) — distinct from a write
		// the platform refused, which finishes normally and is reported from its history.
		what = "Could not run";
		why = action.error;
		result = { label: "Error", tone: "text-danger" };
	} else if (!action.run_id) {
		// A catalogue refresh writes the catalogue, not the run log, so finishing is all there
		// is to report.
		what = "Campaign list refreshed";
		result = { label: "Done", tone: "text-success" };
	} else if (!rows) {
		what = <span className="text-content-muted">Checking…</span>;
		result = { label: "…", tone: "text-content-subtle" };
	} else if (rows.length === 0) {
		what = "Nothing needed changing";
		result = { label: "No change", tone: "text-content-subtle" };
	} else if (only) {
		what = outcomeOf(only);
		why = only.reason;
		result = resultOf(only);
	} else {
		const summary = describeOutcome(rows);
		what = summary.text;
		why = summary.detail;
		result = { label: summary.text, tone: summary.className };
	}

	return (
		<tr className="border-b border-border/60 align-top last:border-0 hover:bg-muted/50">
			<td
				className="px-3 py-2 whitespace-nowrap text-content"
				title={action.run_id ? `Run ${action.run_id}` : undefined}
			>
				{formatDateTime(action.created_at)}
			</td>
			<td className="px-3 py-2 text-content">
				<div className="max-w-[16rem] truncate font-medium" title={who}>
					{who}
				</div>
				<div className="text-xs text-content-subtle">
					{OPERATION[action.job_type] ??
						action.label ??
						action.job_type}
				</div>
			</td>
			{/* The reason is ON the row, not behind a hover — the same choice Execution logs
			    makes: it is the field that explains every other one. */}
			<td className="max-w-md px-3 py-2">
				<div className="font-medium text-content">{what}</div>
				{why && (
					<div className="text-xs leading-relaxed text-content-muted">
						{why}
					</div>
				)}
			</td>
			<td className="px-3 py-2 text-right whitespace-nowrap tabular-nums text-content">
				{changeOf(only)}
			</td>
			<td
				className={`px-3 py-2 whitespace-nowrap font-medium ${result.tone}`}
			>
				{result.label}
			</td>
		</tr>
	);
};

export const OperationsPanel = ({ open, onClose, campaignNameOf }) => {
	const { data, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } =
		// Only while OPEN: this component stays mounted when the panel is closed, and an
		// always-on history query polled alongside the page's own — a duplicate request.
		useActionHistory({ source: ONE_TIME_OPS, enabled: open });

	// A row can repeat across pages only in the instant a page is being re-derived; keying on
	// id keeps each operation listed once regardless.
	const seen = new Set();
	const actions = (data?.pages ?? [])
		.flatMap((p) => p?.items ?? [])
		.filter((a) => (seen.has(a.id) ? false : seen.add(a.id)));

	return (
		<Modal
			open={open}
			onClose={onClose}
			title="Recent operations"
			subtitle="Everything you changed from this page, newest first, and whether it took effect."
			size="xl"
			bleed
			footer={
				hasNextPage ? (
					<div className="flex justify-center">
						<Button
							size="sm"
							variant="secondary"
							disabled={isFetchingNextPage}
							onClick={() => fetchNextPage()}
						>
							{isFetchingNextPage ? "Loading…" : "Load older"}
						</Button>
					</div>
				) : null
			}
		>
			<div className="px-5 py-4">
				{isLoading && <Loading label="Loading operations…" />}
				{!isLoading && !actions.length && (
					<EmptyState
						title="No operations yet"
						message="Budget changes, starts, stops and refreshes made from this page will appear here."
					/>
				)}
				{!isLoading && actions.length > 0 && (
					<>
						<table className="w-full border-collapse text-sm">
							<thead className="sticky top-0 z-10 bg-card">
								<tr className="border-b border-border">
									<th className={TH}>Time</th>
									<th className={TH}>Campaign</th>
									<th className={TH}>
										What happened, and why
									</th>
									<th className={`${TH} text-right`}>
										Change
									</th>
									<th className={TH}>Result</th>
								</tr>
							</thead>
							<tbody>
								{actions.map((a) => (
									<OperationRow
										key={a.id}
										action={a}
										campaignNameOf={campaignNameOf}
									/>
								))}
							</tbody>
						</table>
						{!hasNextPage && (
							<p className="mt-3 text-center text-xs text-content-subtle">
								That is every operation made from this page.
							</p>
						)}
					</>
				)}
			</div>
		</Modal>
	);
};
