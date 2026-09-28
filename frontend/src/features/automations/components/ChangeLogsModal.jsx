import { useEffect, useState } from "react";
import { X, ScrollText } from "lucide-react";
import { Pagination } from "../../../components/ui/Pagination";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { ChannelBadge } from "./ChannelBadge";
import { useHistory } from "../hooks";
import { Select } from "../../../components/ui/Select";
import { ExportButton } from "../../../components/ui/ExportButton";
import { downloadCsv } from "../../../lib/exportTable";
import { HoverHint } from "../../../components/ui/HoverHint";
import { formatDateTime } from "../../../lib/format";
import { KIND_LABEL, outcomeOf, rankOf, resultOf } from "../../../lib/runLog";

const TYPE_OPTIONS = [
	["", "All types"],
	["budget", "Budget change"],
	["bid", "Bid change"],
	["activation", "Start / stop"],
	["wallet", "Ad wallet"],
];

/**
 * The result filter — which also carries what used to be a separate "Include checks with no
 * change" checkbox.
 *
 * Those two filter DIFFERENT things (whether a write worked; whether to show the ticks where
 * nothing needed changing), so they are not one-to-one. Of their combinations, these four are
 * the ones worth offering. The one dropped is "worked as intended AND no-change checks", which
 * is only "everything except failures".
 *
 * `success` on a row means "did what it meant to": a refused or failed write is false, a check
 * that rightly changed nothing is true.
 */
const STATUS_OPTIONS = [
	["", "All results"],
	["with-unchanged", "All results + no-change checks"],
	["success", "Worked as intended"],
	["failed", "Not applied / errors"],
];

// One automation's log already shows its no-change checks — "why has this not moved" is what
// it is opened to answer — so there the extra option would change nothing.
const FOCUS_STATUS_OPTIONS = STATUS_OPTIONS.filter(
	([value]) => value !== "with-unchanged",
);

/** The chosen result → the server query's `success` and `include_unchanged`. */
const resultQuery = (statusFilter, focused) => ({
	success:
		statusFilter === "failed"
			? false
			: statusFilter === "success"
				? true
				: undefined,
	includeUnchanged: focused || statusFilter === "with-unchanged",
});

/**
 * What one automation's log is, as a server query.
 *
 * A campaign automation's record is its budget changes AND the starts/stops it made — but
 * NOT the bid ticks of keyword automations on the same campaign, which outnumber them ~50:1
 * and used to bury them. A keyword automation's is its campaign + keyword rather than its
 * rule id: a Delete + reset writes its row after the rule is gone, and rows from before
 * 2026-09-04 carry no rule id at all — both still belong to the keyword.
 */
const focusQuery = (focusRow) => {
	if (!focusRow) return null;
	return focusRow.kind === "keyword"
		? {
				campaignId: focusRow.campaign_id,
				keyword: focusRow.keyword,
				kind: "bid",
			}
		: { campaignId: focusRow.campaign_id, kind: "budget,activation" };
};

const changeOf = (r) =>
	r.old_value != null || r.new_value != null
		? `${r.old_value ?? "—"} → ${r.new_value ?? "—"}`
		: "—";

/**
 * The log as export columns, for the shared CSV writer.
 *
 * Columns rather than pre-joined lines: `lib/exportTable` handles the quoting and writes
 * the BOM Excel needs to read the file as UTF-8, without which every ₹ in it arrives as
 * mojibake — which is exactly what the local writer this replaced did.
 *
 * `Run` groups the rows one engine run or one job wrote, and is the id to search for in
 * Cloud Logging when a reason is not enough.
 */
const exportColumns = (platformOf, locationOf) => [
	{ header: "Time", value: (r) => formatDateTime(r.timestamp) },
	{ header: "Channel", value: (r) => platformOf(r.campaign_id) ?? "" },
	{ header: "Campaign", value: (r) => r.campaign_name || "" },
	{ header: "Keyword", value: (r) => r.keyword ?? "" },
	{
		header: "Measured at",
		value: (r) => locationOf?.(r.campaign_id, r.keyword) ?? "",
	},
	{ header: "Type", value: (r) => KIND_LABEL[r.kind] ?? r.kind },
	{ header: "What happened", value: (r) => outcomeOf(r) },
	{ header: "Result", value: (r) => resultOf(r).label },
	{ header: "Why", value: (r) => r.reason ?? "" },
	{
		header: "Position seen",
		value: (r) => {
			const rank = rankOf(r);
			return rank
				? `${rank.at ?? ""}${rank.target ? ` (target ${rank.target})` : ""}`
				: "";
		},
	},
	{
		header: "Change",
		value: (r) =>
			r.old_value != null || r.new_value != null
				? `${r.old_value ?? ""} -> ${r.new_value ?? ""}`
				: "",
	},
	{ header: "Run", value: (r) => r.run_id ?? "" },
];

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

	/**
	 * Every filter is applied BY THE SERVER. Filtering one page client-side — as this did —
	 * showed a short page under a total that counted rows the filter had removed, and
	 * "Failed" only ever searched the newest twenty rows.
	 */
	const focus = focusQuery(focusRow);
	// The full list hides the ticks that changed nothing, or they would bury every real change;
	// "All results + no-change checks" opts in. One automation's list always shows them. A
	// choice made in the full list that means nothing in a focused one reads as "All results".
	const status =
		focus && statusFilter === "with-unchanged" ? "" : statusFilter;
	const result = resultQuery(status, Boolean(focus));
	const { data, isLoading, error, refetch } = useHistory(
		page,
		focus?.kind ?? (typeFilter || undefined),
		{
			campaignId: focus?.campaignId,
			keyword: focus?.keyword,
			success: result.success,
			includeUnchanged: result.includeUnchanged,
			enabled: open,
		},
	);
	const rows = data?.items ?? [];

	// Back to the first page whenever the question changes, so page 3 of one automation
	// (or of one filter) is never read as page 3 of the next.
	useEffect(() => {
		setPage(1);
	}, [focusRow?.campaign_id, focusRow?.id, statusFilter, typeFilter]);

	if (!open) return null;

	// Named after what was asked for: one automation's file should not be called the same
	// thing as the file holding every automation's history.
	const exportCsv = () => {
		const who = focusRow
			? (focusRow.kind === "campaign"
					? focusRow.name || focusRow.campaign_name
					: focusRow.keyword
				)
					?.toLowerCase()
					.replace(/[^a-z0-9]+/g, "-")
					.replace(/^-|-$/g, "")
			: null;
		downloadCsv(`automation-execution-logs${who ? `-${who}` : ""}.csv`, [
			{ columns: exportColumns(platformOf, locationOf), rows },
		]);
	};

	return (
		<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6">
			<div className="flex h-full max-h-[85vh] w-full max-w-6xl flex-col rounded-xl border border-border bg-card shadow-2xl">
				<header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
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
					<div className="flex flex-wrap items-center gap-3">
						{/* One automation is already one type, so its log has no type to pick. */}
						{!focusRow && (
							<Select
								ariaLabel="Filter by type"
								value={typeFilter}
								onChange={setTypeFilter}
								options={TYPE_OPTIONS}
							/>
						)}
						<Select
							ariaLabel="Filter by result"
							value={status}
							onChange={setStatusFilter}
							options={
								focusRow ? FOCUS_STATUS_OPTIONS : STATUS_OPTIONS
							}
						/>
						<ExportButton
							onExport={exportCsv}
							disabled={!rows.length}
						/>
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
						<EmptyState
							message={
								statusFilter || typeFilter
									? "Nothing matches these filters."
									: "No automation activity yet."
							}
						/>
					)}
					{!isLoading && !error && rows.length > 0 && (
						<table className="w-full border-collapse text-sm">
							<thead className="sticky top-0 z-10 bg-card">
								<tr className="border-b border-border">
									<th className="px-3 py-2 text-left font-medium text-content-subtle">
										Time
									</th>
									<th className="px-3 py-2 text-left font-medium text-content-subtle">
										Automation
									</th>
									<th className="px-3 py-2 text-left font-medium text-content-subtle">
										What happened, and why
									</th>
									<th className="px-3 py-2 text-right font-medium text-content-subtle">
										<HoverHint
											label="Bid rows only: the position the engine SAW when it checked, over the target it was holding to. Not the rank after the write, since where a bid lands is only known at the next check. Budget and start/stop rows have no position."
											className="w-full justify-end"
											tabIndex={0}
										>
											<span className="cursor-help decoration-content-subtle/40 decoration-dotted underline-offset-4 hover:decoration-content-subtle hover:underline">
												Position
											</span>
										</HoverHint>
									</th>
									<th className="px-3 py-2 text-right font-medium text-content-subtle">
										Change
									</th>
									<th className="px-3 py-2 text-left font-medium text-content-subtle">
										Result
									</th>
								</tr>
							</thead>
							<tbody>
								{rows.map((r) => {
									const rank = rankOf(r);
									const result = resultOf(r);
									return (
										<tr
											key={r.id}
											className="border-b border-border/60 align-top last:border-0 hover:bg-muted/50"
										>
											<td
												className="px-3 py-2 whitespace-nowrap text-content"
												title={
													r.run_id
														? `Run ${r.run_id}`
														: undefined
												}
											>
												{formatDateTime(r.timestamp)}
											</td>
											<td className="px-3 py-2 text-content">
												{/* ⚠️ Campaign FIRST, with the store underneath. A bid row's rank is
												    checked at one dark store, so "position 5" means position 5 there;
												    a log line without it says where nothing. */}
												<div className="flex items-center gap-1.5">
													<ChannelBadge
														platform={platformOf(
															r.campaign_id,
														)}
													/>
													<span
														className="max-w-[16rem] truncate font-medium"
														title={
															r.campaign_name ??
															""
														}
													>
														{r.campaign_name ||
															(r.campaign_id ==
															null
																? (KIND_LABEL[
																		r.kind
																	] ??
																	"Account")
																: `Campaign ${r.campaign_id}`)}
													</span>
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
											{/* The reason is ON the row, not behind a hover: it is the field that
											    explains every other one, and a hover cannot be scanned down a list. */}
											<td className="max-w-md px-3 py-2">
												<div className="font-medium text-content">
													{outcomeOf(r)}
												</div>
												{r.reason && (
													<div className="text-xs leading-relaxed text-content-muted">
														{r.reason}
													</div>
												)}
											</td>
											<td className="px-3 py-2 text-right whitespace-nowrap tabular-nums">
												{r.kind !== "bid" ? (
													<span className="text-content-subtle">
														n/a
													</span>
												) : !rank ? (
													<span className="text-content-subtle">
														—
													</span>
												) : (
													<span className="text-content">
														{rank.at != null
															? `#${rank.at}`
															: "—"}
														{rank.target !=
															null && (
															<span className="text-content-subtle">
																{" "}
																/ #{rank.target}
															</span>
														)}
													</span>
												)}
											</td>
											<td className="px-3 py-2 text-right whitespace-nowrap tabular-nums text-content">
												{changeOf(r)}
											</td>
											<td
												className={`px-3 py-2 whitespace-nowrap font-medium ${result.tone}`}
											>
												{result.label}
											</td>
										</tr>
									);
								})}
							</tbody>
						</table>
					)}
				</div>

				{data && (
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
