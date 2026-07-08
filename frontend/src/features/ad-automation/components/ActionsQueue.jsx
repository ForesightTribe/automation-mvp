import { useEffect, useState } from "react";
import { Card } from "../../../components/ui/Card";
import { Button } from "../../../components/ui/Button";
import { Pagination } from "../../../components/ui/Pagination";
import { DataTable } from "../../../components/ui/DataTable";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { ActionStatusBadge } from "./ActionStatusBadge";
import { useActions, useResolveAction } from "../hooks";

const LIMIT = 20;

/** Recommendation queue: pending items get Approve/Reject, approved items get
 * Mark complete once the user has made the change in Blinkit by hand —
 * Phase 1 never executes against Blinkit itself (see CLAUDE.md / plan notes). */
export const ActionsQueue = () => {
	const [status, setStatus] = useState("pending");
	const [page, setPage] = useState(1);
	useEffect(() => setPage(1), [status]);

	const { data, isLoading, error, refetch, isFetching } = useActions({
		status,
		page,
		limit: LIMIT,
	});
	const resolveAction = useResolveAction();
	const rows = data?.items ?? [];

	const columns = [
		{ key: "campaign", label: "Campaign", render: (r) => r.campaign_name || `#${r.campaign_id}` },
		{ key: "reasoning", label: "Why" },
		{ key: "status", label: "Status", render: (r) => <ActionStatusBadge status={r.status} /> },
		{
			key: "detected_at",
			label: "Detected",
			render: (r) => new Date(r.detected_at).toLocaleDateString(),
		},
		{
			key: "actions",
			label: "",
			align: "right",
			render: (r) => (
				<div className="flex justify-end gap-1.5">
					{r.status === "pending" && (
						<>
							<Button
								size="sm"
								onClick={() =>
									resolveAction.mutate({ actionId: r.id, status: "approved" })
								}
							>
								Approve
							</Button>
							<Button
								variant="secondary"
								size="sm"
								onClick={() =>
									resolveAction.mutate({ actionId: r.id, status: "rejected" })
								}
							>
								Reject
							</Button>
						</>
					)}
					{r.status === "approved" && (
						<Button
							variant="secondary"
							size="sm"
							onClick={() =>
								resolveAction.mutate({ actionId: r.id, status: "completed" })
							}
						>
							Mark complete
						</Button>
					)}
				</div>
			),
		},
	];

	return (
		<Card
			title="Recommended actions"
			actions={
				<select
					value={status}
					onChange={(e) => setStatus(e.target.value)}
					className="rounded-md border border-border bg-card px-2.5 py-1 text-sm text-content focus:outline-none focus:ring-2 focus:ring-primary/30"
				>
					<option value="pending">Pending</option>
					<option value="approved">Approved</option>
					<option value="rejected">Rejected</option>
					<option value="completed">Completed</option>
					<option value="">All</option>
				</select>
			}
		>
			{isLoading && <Loading label="Loading recommendations…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(rows.length === 0 ? (
					<EmptyState message="Nothing here. Click 'Check now' to evaluate your rules." />
				) : (
					<div className={isFetching ? "opacity-60 transition-opacity" : ""}>
						<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />
						<Pagination
							page={data.page}
							pages={data.pages}
							total={data.total}
							limit={data.limit}
							onChange={setPage}
						/>
					</div>
				))}
		</Card>
	);
};
