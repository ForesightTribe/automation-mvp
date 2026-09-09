import { useMemo, useState } from "react";
import { Download, X, ScrollText } from "lucide-react";
import { Pagination } from "../../../components/ui/Pagination";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { ChannelBadge } from "./ChannelBadge";
import { useHistory } from "../hooks";
import { Select } from "../../../components/ui/Select";
import { HoverHint } from "../../../components/ui/HoverHint";

const KIND_LABEL = {
	budget: "Budget change",
	bid: "Bid change",
	activation: "Start / stop",
};

const TYPE_OPTIONS = [
	["", "All types"],
	["budget", "Budget change"],
	["bid", "Bid change"],
	["activation", "Start / stop"],
];

const STATUS_OPTIONS = [
	["", "All statuses"],
	["success", "Success"],
	["failed", "Failed"],
];

/**
 * The rank the engine was looking at, pulled out of the reason line.
 *
 * ⚠️ Read from prose, because the run log has no rank column: the bid engine writes lines
 * like "raising to ₹658 (+₹112) because position 5 is worse than target 1". Roughly a third
 * of bid rows carry one, and the rest legitimately have none (an error, a skip, a window
 * opening). Blank means "not stated", never "position zero".
 */
const rankOf = (row) => {
	if (row.kind !== "bid" || !row.reason) return null;
	const at = row.reason.match(/position (\d+)/i);
	const target = row.reason.match(/target (\d+)/i);
	if (!at && !target) return null;
	return { at: at?.[1] ?? null, target: target?.[1] ?? null };
};

/**
 * What the row actually did, in three or four words.
 *
 * The engine's own `action` is a verb from its vocabulary — drift, no-op, recover, open —
 * which is precise and means nothing to a reader. This maps it onto the outcome.
 */
const OUTCOME = {
	"budget:apply": "Budget changed",
	"budget:skip": "No change needed",
	"bid:apply": "Bid raised",
	"bid:drift": "Cost trimmed",
	"bid:no-op": "Rank held",
	"bid:open": "Window opened",
	"bid:reset": "Window closed",
	"bid:recover": "Bid restored",
	"bid:skip": "Skipped",
	"bid:error": "Could not check",
	"activation:apply": "Campaign started or paused",
	"activation:skip": "Already in that state",
};

const outcomeOf = (r) => OUTCOME[`${r.kind}:${r.action}`] ?? r.action;

/** "7 Sept 2026, 4:00 pm" — a log without a time answers half the question. */
const stamp = (ts) => {
	const d = new Date(ts);
	return Number.isNaN(d.getTime())
		? String(ts)
		: d.toLocaleString("en-IN", {
				day: "numeric",
				month: "short",
				year: "numeric",
				hour: "numeric",
				minute: "2-digit",
				hour12: true,
			});
};

const toCsv = (rows, platformOf, locationOf) => {
	const header = [
		"Time",
		"Channel",
		"Campaign",
		"Keyword",
		"Measured at",
		"Type",
		"What happened",
		"Change",
		"Position seen",
		"Status",
		"Reason",
	];
	const lines = rows.map((r) => {
		const campaign = r.campaign_name || "";
		const change =
			r.old_value != null || r.new_value != null
				? `${r.old_value ?? ""} -> ${r.new_value ?? ""}`
				: "";
		const status = r.dry_run
			? "test mode"
			: r.success
				? "applied"
				: "failed";
		const rank = rankOf(r);
		return [
			stamp(r.timestamp),
			platformOf(r.campaign_id) ?? "",
			campaign,
			r.keyword ?? "",
			locationOf?.(r.campaign_id, r.keyword) ?? "",
			KIND_LABEL[r.kind] ?? r.kind,
			outcomeOf(r),
			change,
			rank
				? `${rank.at ?? ""}${rank.target ? ` (target ${rank.target})` : ""}`
				: "",
			status,
			r.reason ?? "",
		]
			.map((v) => `"${String(v).replace(/"/g, '""')}"`)
			.join(",");
	});
	return [header.join(","), ...lines].join("\n");
};

/**
 * The execution log — cm_run_log surfaced as a full-screen overlay: every time the engine
 * looked at an automation, what it decided, and whether the write landed. `dry_run` rows are shown plainly ("test mode")
 * rather than hidden, per docs/campaign-manager.md's philosophy that a held
 * rule should demonstrate the engine works, not look like nothing happened.
 * `platformOf(campaign_id)` looks Channel up from the already-fetched
 * schedules/bid-rules — RunLogOut itself carries no platform field.
 */
export const ChangeLogsModal = ({
	open,
	onClose,
	focusRow,
	platformOf,
	locationOf,
}) => {
	const [page, setPage] = useState(1);
	const [statusFilter, setStatusFilter] = useState("");
	const [typeFilter, setTypeFilter] = useState("");
	const { data, isLoading, error, refetch } = useHistory(page);

	const rows = useMemo(() => {
		let r = data?.items ?? [];
		if (focusRow) {
			r = r.filter(
				(x) =>
					x.campaign_id === focusRow.campaign_id &&
					(focusRow.kind !== "keyword" ||
						x.keyword === focusRow.keyword),
			);
		}
		if (typeFilter) r = r.filter((x) => x.kind === typeFilter);
		if (statusFilter === "success") r = r.filter((x) => x.success);
		if (statusFilter === "failed") r = r.filter((x) => !x.success);
		return r;
	}, [data, focusRow, statusFilter, typeFilter]);

	if (!open) return null;

	const exportCsv = () => {
		const blob = new Blob([toCsv(rows, platformOf, locationOf)], {
			type: "text/csv;charset=utf-8;",
		});
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = "automation-execution-logs.csv";
		a.click();
		URL.revokeObjectURL(url);
	};

	return (
		<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6">
			<div className="flex h-full max-h-[85vh] w-full max-w-5xl flex-col rounded-xl border border-border bg-card shadow-2xl">
				<header className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
					<div className="flex items-center gap-2">
						<ScrollText size={18} className="text-content-muted" />
						<h2 className="font-display text-base font-semibold text-content">
							Execution logs
						</h2>
						{focusRow && (
							<span className="rounded-full border border-content bg-muted px-2.5 py-0.5 text-xs font-medium text-content">
								{focusRow.kind === "campaign"
									? focusRow.name || focusRow.campaign_name
									: focusRow.keyword}
							</span>
						)}
					</div>
					<div className="flex items-center gap-3">
						<Select
							ariaLabel="Filter by type"
							value={typeFilter}
							onChange={setTypeFilter}
							options={TYPE_OPTIONS}
						/>
						<Select
							ariaLabel="Filter by status"
							value={statusFilter}
							onChange={setStatusFilter}
							options={STATUS_OPTIONS}
						/>
						<button
							type="button"
							onClick={exportCsv}
							className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-content hover:bg-muted"
						>
							<Download size={13} /> Export
						</button>
						<button
							type="button"
							aria-label="Close"
							onClick={onClose}
							className="rounded p-1 text-content-subtle hover:bg-muted hover:text-content"
						>
							<X size={18} />
						</button>
					</div>
				</header>

				<div className="flex-1 overflow-auto px-5 py-4">
					{isLoading && <Loading label="Loading history…" />}
					{error && (
						<ErrorState message={error.message} onRetry={refetch} />
					)}
					{!isLoading && !error && rows.length === 0 && (
						<EmptyState message="No automation activity yet." />
					)}
					{!isLoading && !error && rows.length > 0 && (
						<table className="w-full border-collapse text-sm">
							<thead className="sticky top-0 z-10 bg-card">
								<tr className="border-b border-border">
									<th className="px-3 py-2 text-left font-medium text-content-subtle">
										Time
									</th>
									<th className="px-3 py-2 text-left font-medium text-content-subtle">
										Channel
									</th>
									<th className="px-3 py-2 text-left font-medium text-content-subtle">
										Automation
									</th>
									<th className="px-3 py-2 text-right font-medium text-content-subtle">
										Change
									</th>
									<th className="px-3 py-2 text-right font-medium text-content-subtle">
										<HoverHint
											label="Bid rows only: the position the engine SAW when it checked, over the target it was holding to. Not the rank after the write, since where a bid lands is only known at the next check. Budget changes and start/stop rows have no position, so they read n/a. Hover any row for the engine's own reason."
											className="w-full justify-end"
											tabIndex={0}
										>
											<span className="cursor-help decoration-content-subtle/40 decoration-dotted underline-offset-4 hover:decoration-content-subtle hover:underline">
												Position seen
											</span>
										</HoverHint>
									</th>
									<th className="px-3 py-2 text-left font-medium text-content-subtle">
										Status
									</th>
								</tr>
							</thead>
							<tbody>
								{rows.map((r) => (
									<tr
										key={r.id}
										className="border-b border-border/60 last:border-0 hover:bg-muted/50"
									>
										<td className="px-3 py-2 whitespace-nowrap text-content">
											{stamp(r.timestamp)}
										</td>
										<td className="px-3 py-2">
											<ChannelBadge
												platform={platformOf(
													r.campaign_id,
												)}
											/>
										</td>
										<td className="px-3 py-2 text-content">
											{/* ⚠️ Campaign FIRST, with the store underneath. A bid row's rank is
											    checked at one dark store, so "position 5" means position 5 there;
											    a log line without it says where nothing. The keyword sits beside
											    the type, since it qualifies the rule rather than naming it. */}
											<div
												className="max-w-[20rem] truncate font-medium"
												title={r.campaign_name ?? ""}
											>
												{r.campaign_name || "—"}
											</div>
											<div className="text-xs text-content-subtle">
												{[
													KIND_LABEL[r.kind] ??
														r.kind,
													r.keyword
														? `“${r.keyword}”`
														: null,
													locationOf?.(
														r.campaign_id,
														r.keyword,
													),
												]
													.filter(Boolean)
													.join(" · ")}
											</div>
										</td>
										<td className="px-3 py-2 text-right tabular-nums text-content">
											{r.old_value != null ||
											r.new_value != null
												? `${r.old_value ?? "—"} → ${r.new_value ?? "—"}`
												: "—"}
										</td>
										{/* ⚠️ The reason hangs HERE, on every row, including the ones with no
										    position: a budget row's "window ended" has nowhere else to live now that
										    the reason has no column of its own. Our own hover panel rather than the
										    browser's title tooltip, so it matches the rest of these pages. */}
										<td className="px-3 py-2 text-right tabular-nums">
											<HoverHint
												label={r.reason ?? null}
												className="w-full justify-end"
											>
												{(() => {
													const rank = rankOf(r);
													const marked = r.reason
														? "cursor-help decoration-content-subtle/40 decoration-dotted underline-offset-4 hover:decoration-content-subtle hover:underline"
														: "";
													// ⚠️ Two different blanks. A budget change or a start/stop has no position
													// by nature, so it reads "n/a"; a BID row without one is a row the
													// engine did not state a position for, which is a gap in the record
													// rather than an inapplicable question, and reads "—".
													if (r.kind !== "bid")
														return (
															<span
																className={`text-content-subtle ${marked}`}
															>
																n/a
															</span>
														);
													if (!rank)
														return (
															<span
																className={`text-content-subtle ${marked}`}
															>
																—
															</span>
														);
													return (
														<span
															className={`text-content ${marked}`}
														>
															{rank.at
																? `#${rank.at}`
																: "—"}
															{rank.target && (
																<span className="text-content-subtle">
																	{" "}
																	/ #
																	{
																		rank.target
																	}
																</span>
															)}
														</span>
													);
												})()}
											</HoverHint>
										</td>
										<td className="px-3 py-2 whitespace-nowrap">
											<span
												className={
													r.success
														? "text-success"
														: "text-danger"
												}
											>
												{r.dry_run
													? "Test mode"
													: r.success
														? "Applied"
														: "Failed"}
											</span>
										</td>
									</tr>
								))}
							</tbody>
						</table>
					)}
				</div>

				{!focusRow && data && (
					<div className="border-t border-border px-5 py-3">
						<Pagination
							page={data.page}
							pages={data.pages}
							total={data.total}
							limit={data.limit}
							onChange={setPage}
						/>
					</div>
				)}
			</div>
		</div>
	);
};
