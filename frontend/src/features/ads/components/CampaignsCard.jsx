import { useEffect, useMemo, useState } from "react";
import { useCampaigns } from "../hooks";
import { CampaignStatusBadge } from "./CampaignStatusBadge";
import { Card } from "../../../components/ui/Card";
import { Pagination } from "../../../components/ui/Pagination";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { useDateRange } from "../../../context/DateRangeContext";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { formatCompactCurrency, formatNumber } from "../../../lib/format";

const LIMIT = 20;

const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;

/** Sortable, paginated campaign table. Header cells for spend/sales/impressions/
 * RoAS click-to-sort: clicking the active column flips direction, a new column
 * starts descending. Sort `roas` doubles as the RoAS leaderboard (asc = worst
 * spenders). Status filter is derived from the rows currently loaded. */
export const CampaignsCard = () => {
	const [sort, setSort] = useState("spend");
	const [order, setOrder] = useState("desc");
	const [status, setStatus] = useState("");
	const [page, setPage] = useState(1);

	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	useEffect(() => {
		setPage(1);
	}, [sort, order, status, range, selected]);

	const { data, isLoading, error, refetch, isFetching } = useCampaigns({
		page,
		limit: LIMIT,
		status,
		sort,
		order,
	});
	const rows = data?.items ?? [];

	// Distinct statuses seen so far populate the filter (self-correcting as you page).
	const statuses = useMemo(
		() => [
			...new Set(
				(data?.items ?? []).map((r) => r.status).filter(Boolean),
			),
		],
		[data],
	);

	const onSort = (key) => {
		if (key === sort) {
			setOrder((o) => (o === "desc" ? "asc" : "desc"));
		} else {
			setSort(key);
			setOrder("desc");
		}
	};

	const SortHead = ({ label, sortKey }) => {
		const active = sort === sortKey;
		const arrow = active ? (order === "asc" ? "▲" : "▼") : "";
		return (
			<th className="px-3 py-2 text-right">
				<button
					type="button"
					onClick={() => onSort(sortKey)}
					className={`inline-flex items-center gap-1 font-medium hover:text-content ${
						active ? "text-content" : "text-content-subtle"
					}`}
				>
					{label}
					<span className="text-[10px]" aria-hidden>
						{arrow}
					</span>
				</button>
			</th>
		);
	};

	return (
		<Card
			title="Campaigns"
			actions={
				<select
					value={status}
					onChange={(e) => setStatus(e.target.value)}
					className="rounded-md border border-border bg-card px-2.5 py-1 text-sm text-content focus:outline-none focus:ring-2 focus:ring-primary/30"
				>
					<option value="">All statuses</option>
					{statuses.map((s) => (
						<option key={s} value={s}>
							{s}
						</option>
					))}
				</select>
			}
		>
			{isLoading && <Loading label="Loading campaigns…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(rows.length === 0 ? (
					<EmptyState message="No campaigns match these filters in this window." />
				) : (
					<div
						className={
							isFetching ? "opacity-60 transition-opacity" : ""
						}
					>
						<div className="overflow-auto">
							<table className="w-full border-collapse text-sm">
								<thead className="sticky top-0 z-10 bg-card">
									<tr className="border-b border-border">
										<th className="px-3 py-2 text-left font-medium text-content-subtle">
											Campaign
										</th>
										<th className="px-3 py-2 text-left font-medium text-content-subtle">
											Type
										</th>
										<SortHead
											label="Spend"
											sortKey="spend"
										/>
										<SortHead
											label="Impressions"
											sortKey="impressions"
										/>
										<SortHead
											label="Ad revenue"
											sortKey="sales"
										/>
										<SortHead label="RoAS" sortKey="roas" />
										<th className="px-3 py-2 text-left font-medium text-content-subtle">
											Status
										</th>
									</tr>
								</thead>
								<tbody>
									{rows.map((r) => (
										<tr
											key={r.campaign_id}
											className="border-b border-border/60 last:border-0 hover:bg-muted/50"
										>
											<td className="px-3 py-2">
												<div className="font-medium text-content">
													{r.name ||
														`#${r.campaign_id}`}
												</div>
											</td>
											<td className="px-3 py-2 text-content-muted">
												{r.type || "—"}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatCompactCurrency(
													r.budget_consumed,
												)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatNumber(r.impressions)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatCompactCurrency(
													r.ad_sales,
												)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatRoas(r.roas)}
											</td>
											<td className="px-3 py-2">
												<CampaignStatusBadge
													status={r.status}
												/>
											</td>
										</tr>
									))}
								</tbody>
							</table>
						</div>
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
