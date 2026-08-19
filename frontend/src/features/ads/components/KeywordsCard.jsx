import { useEffect, useState } from "react";
import { useKeywords } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { Pagination } from "../../../components/ui/Pagination";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { formatCompactCurrency, formatNumber } from "../../../lib/format";

const LIMIT = 20;

const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;

const TARGET_OPTIONS = [
	{ value: "", label: "All targets" },
	{ value: "keyword", label: "Keywords" },
	{ value: "recommendation", label: "Recommendations" },
];

/** Keyword / asset performance from the latest detail snapshot per campaign.
 * Sortable by spend/sales/RoAS/impressions; filterable by target type. Shows the
 * per-keyword RoAS that campaign-level metrics can't. */
export const KeywordsCard = () => {
	const [sort, setSort] = useState("spend");
	const [order, setOrder] = useState("desc");
	const [targetType, setTargetType] = useState("");
	const [page, setPage] = useState(1);

	const { selected } = useMarketplaces();
	useEffect(() => {
		setPage(1);
	}, [sort, order, targetType, selected]);

	const { data, isLoading, error, refetch, isFetching } = useKeywords({
		page,
		limit: LIMIT,
		targetType,
		sort,
		order,
	});
	const rows = data?.items ?? [];

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
			title="Keyword & asset performance"
			actions={
				<select
					value={targetType}
					onChange={(e) => setTargetType(e.target.value)}
					className="rounded-md border border-border bg-card px-2.5 py-1 text-sm text-content focus:outline-none focus:ring-2 focus:ring-brand/30"
				>
					{TARGET_OPTIONS.map((o) => (
						<option key={o.value} value={o.value}>
							{o.label}
						</option>
					))}
				</select>
			}
		>
			{isLoading && <Loading label="Loading keywords…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(rows.length === 0 ? (
					<EmptyState message="No keyword data captured yet." />
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
											Target
										</th>
										<th className="px-3 py-2 text-left font-medium text-content-subtle">
											Match
										</th>
										<SortHead
											label="Impressions"
											sortKey="impressions"
										/>
										<SortHead
											label="Spend"
											sortKey="spend"
										/>
										<SortHead
											label="Sales"
											sortKey="sales"
										/>
										<SortHead label="RoAS" sortKey="roas" />
									</tr>
								</thead>
								<tbody>
									{rows.map((r) => (
										<tr
											key={`${r.campaign_id}-${r.target}-${r.match_type ?? ""}`}
											className="border-b border-border/60 last:border-0 hover:bg-muted/50"
										>
											<td className="px-3 py-2">
												<div className="font-medium text-content">
													{r.target}
												</div>
												<div className="text-xs text-content-subtle">
													{r.target_type}
												</div>
											</td>
											<td className="px-3 py-2 text-content-muted">
												{r.match_type || "—"}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatNumber(r.impressions)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatCompactCurrency(
													r.budget_consumed,
												)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatCompactCurrency(
													r.direct_sales +
														r.indirect_sales,
												)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-content">
												{formatRoas(r.total_roas)}
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
