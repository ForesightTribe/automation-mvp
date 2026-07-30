import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { Loading } from "../../../components/feedback/Loading";
import { formatCurrency } from "../../../lib/format";
import { useHistory } from "../hooks";

const ACTION_TONE = {
	apply: "text-success",
	error: "text-danger",
	skip: "text-content-muted",
	"no-op": "text-content-muted",
	hold: "text-warning",
	target: "text-info",
};

const time = (ts) =>
	new Date(ts).toLocaleString("en-IN", {
		day: "2-digit",
		month: "short",
		hour: "2-digit",
		minute: "2-digit",
	});

/** Slim run history from cm_run_log (what each automation run decided/did). */
export const HistoryCard = () => {
	const [page, setPage] = useState(1);
	const { data, isLoading } = useHistory(page);
	const rows = data?.items ?? [];

	return (
		<Card
			title="History"
			actions={
				data && data.pages > 1 ? (
					<div className="flex items-center gap-2 text-xs text-content-muted">
						<Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
							‹
						</Button>
						<span>
							{page} / {data.pages}
						</span>
						<Button size="sm" variant="ghost" disabled={page >= data.pages} onClick={() => setPage((p) => p + 1)}>
							›
						</Button>
					</div>
				) : null
			}
		>
			{isLoading ? (
				<Loading />
			) : !rows.length ? (
				<EmptyState title="No runs yet" message="Automation runs and manual actions will show here." icon="◷" />
			) : (
				<div className="overflow-x-auto">
					<table className="w-full text-sm">
						<thead>
							<tr className="border-b border-border text-left text-xs text-content-subtle">
								<th className="py-2 pr-3 font-medium">When</th>
								<th className="py-2 pr-3 font-medium">Kind</th>
								<th className="py-2 pr-3 font-medium">Target</th>
								<th className="py-2 pr-3 font-medium">Action</th>
								<th className="py-2 pr-3 font-medium">Change</th>
								<th className="py-2 font-medium"></th>
							</tr>
						</thead>
						<tbody>
							{rows.map((r) => (
								<tr key={r.id} className="border-b border-border/60 text-content">
									<td className="py-2 pr-3 whitespace-nowrap text-content-muted">{time(r.timestamp)}</td>
									<td className="py-2 pr-3 capitalize">{r.kind}</td>
									<td className="py-2 pr-3 text-content-muted">
										{r.campaign_id ? (
											<span>
												<span className="text-content">
													{r.campaign_name || `campaign ${r.campaign_id}`}
												</span>
												<span className="text-content-subtle"> #{r.campaign_id}</span>
												{r.keyword ? ` · ${r.keyword}` : ""}
											</span>
										) : (
											(r.keyword ?? "—")
										)}
									</td>
									<td className={`py-2 pr-3 font-medium capitalize ${ACTION_TONE[r.action] ?? ""}`}>{r.action}</td>
									<td className="py-2 pr-3 text-content-muted">
										{r.old_value != null || r.new_value != null
											? `${r.old_value != null ? formatCurrency(r.old_value) : "—"} → ${r.new_value != null ? formatCurrency(r.new_value) : "—"}`
											: "—"}
									</td>
									<td className="py-2">
										{r.dry_run && (
											<span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-content-muted">
												dry-run
											</span>
										)}
									</td>
								</tr>
							))}
						</tbody>
					</table>
				</div>
			)}
		</Card>
	);
};
