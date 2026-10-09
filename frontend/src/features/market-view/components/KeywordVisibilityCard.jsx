import { useKeywordPresence } from "../hooks";
import { useMarketView } from "../viewContext";
import { Card } from "../../../components/ui/Card";
import { DataTable } from "../../../components/ui/DataTable";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { PresenceBar } from "./PresenceBar";
import { formatNumber } from "../../../lib/format";

const rank = (v) => (v == null ? "—" : `#${Number(v).toFixed(1)}`);

/**
 * Visibility per search term, and the control that drives the rest of the page.
 *
 * `found / searched` is the honest denominator: winning a term in three stores
 * out of four is a different fact from three out of four hundred, and an
 * average rank alone hides both. Rank and share are "when found" — averaging a
 * missing listing as rank 0 would invent a number the scrape never saw.
 *
 * Clicking a row selects that keyword for the store explorer and SKU table.
 */
export const KeywordVisibilityCard = () => {
	const { data, isLoading, error, refetch } = useKeywordPresence();
	const { keyword, setKeyword } = useMarketView();
	const rows = data?.rows ?? [];

	const columns = [
		{
			key: "keyword",
			label: "Keyword",
			// The marker lives in the cell rather than on the row: DataTable is
			// shared with every other table and has no selected-row state.
			render: (r) => (
				<span className="flex items-center gap-2">
					<span className={r.keyword === keyword ? "font-semibold text-content" : ""}>
						{r.keyword}
					</span>
					{r.keyword === keyword && (
						<span className="rounded bg-brand/10 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-brand uppercase">
							selected
						</span>
					)}
				</span>
			),
		},
		{
			key: "stores",
			label: "Stores found",
			align: "right",
			render: (r) => `${formatNumber(r.stores_found)} / ${formatNumber(r.stores_searched)}`,
		},
		{ key: "presence_pct", label: "Presence", render: (r) => <PresenceBar pct={r.presence_pct} /> },
		{ key: "avg_rank", label: "Avg rank (when found)", align: "right", render: (r) => rank(r.avg_rank) },
		{ key: "best_rank", label: "Best", align: "right", render: (r) => (r.best_rank == null ? "—" : `#${r.best_rank}`) },
		{
			key: "avg_sov_pct",
			label: "Share of results",
			align: "right",
			render: (r) => (r.avg_sov_pct == null ? "—" : `${r.avg_sov_pct}%`),
		},
	];

	return (
		<Card title="Visibility by search term">
			{isLoading ? (
				<Loading label="Loading keywords…" />
			) : error ? (
				<ErrorState message={error.message} onRetry={refetch} />
			) : rows.length === 0 ? (
				<EmptyState message="No keyword results in this window." />
			) : (
				<>
					<DataTable
						columns={columns}
						rows={rows}
						rowKey={(r) => r.keyword}
						onRowClick={(r) =>
							setKeyword(r.keyword === keyword ? null : r.keyword)
						}
					/>
					<p className="px-4 pb-3 pt-1 text-xs text-content-muted">
						{keyword
							? `Showing “${keyword}” below. Click the row again to clear.`
							: "Pick a term to narrow the store explorer and SKU table below."}
					</p>
				</>
			)}
		</Card>
	);
};
