import { useState } from "react";
import { useRawAds } from "../hooks";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { Pagination } from "../../../components/ui/Pagination";
import { formatCurrency, formatDate, formatNumber } from "../../../lib/format";

/**
 * One of the workbook's raw sheets, on screen.
 *
 * Paginated rather than capped. These run to tens of thousands of rows, and a
 * page that quietly shows the first few hundred would misrepresent what the
 * download contains; paging says how many there are and lets you reach all of
 * them.
 *
 * The columns are the platform's own, in the platform's own order, because the
 * point of a raw sheet is that it matches the export somebody is used to —
 * which is why `columns` is a prop rather than fixed: Blinkit's and
 * Instamart's raw tables don't share a shape.
 */
const BLINKIT_COLS = [
	["date", "Date", "date"],
	["campaign_id", "Campaign ID", "id"],
	["campaign_name", "Campaign Name", "text"],
	["targeting_type", "Targeting Type", "text"],
	["targeting_value", "Targeting Value", "text"],
	["match_type", "Match Type", "text"],
	["most_viewed_position", "Most Viewed Position", "count"],
	["pacing_type", "Pacing Type", "text"],
	["cpm", "CPM", "money"],
	["impressions", "Impressions", "count"],
	["direct_atc", "Direct ATC", "count"],
	["indirect_atc", "Indirect ATC", "count"],
	["direct_quantities_sold", "Direct Qty Sold", "count"],
	["indirect_quantities_sold", "Indirect Qty Sold", "count"],
	["direct_sales", "Direct Sales", "money"],
	["indirect_sales", "Indirect Sales", "money"],
	["new_users_acquired", "New Users", "count"],
	["budget_consumed", "Budget Consumed", "money"],
	["direct_roas", "Direct RoAS", "ratio"],
	["total_roas", "Total RoAS", "ratio"],
];

export const INSTAMART_RAW_COLS = [
	["date", "Date", "date"],
	["campaign_id", "Campaign ID", "id"],
	["campaign_name", "Campaign Name", "text"],
	["candidate_id", "Product ID", "id"],
	["product_name", "Product Name", "text"],
	["spend", "Spend", "money"],
	["gmv", "Ad GMV", "money"],
	["roas", "RoAS", "ratio"],
	["impressions", "Impressions", "count"],
	["clicks", "Clicks", "count"],
	["add_to_cart_count", "Add to Cart", "count"],
];

const cell = (v, type) => {
	if (v === null || v === undefined || v === "") return "—";
	if (type === "money") return formatCurrency(v);
	if (type === "count") return formatNumber(v);
	if (type === "ratio") return `${Number(v).toFixed(2)}x`;
	if (type === "date") return formatDate(v);
	return String(v);
};

export const RawAdSheet = ({
	campaignType,
	active,
	marketplace = "blinkit",
	columns = BLINKIT_COLS,
}) => {
	const [page, setPage] = useState(1);
	const { data, isLoading, error, refetch } = useRawAds(
		campaignType,
		page,
		active,
		marketplace,
	);
	const COLS = columns;

	if (isLoading) return <Loading label="Loading rows…" />;
	if (error) return <ErrorState message={error.message} onRetry={refetch} />;
	if (!data?.items?.length)
		return <EmptyState message="No rows for this window." />;

	return (
		<div className="flex flex-col">
			<table className="w-full border-collapse text-sm">
				<thead className="sticky top-0 z-20">
					<tr>
						{COLS.map(([key, header, type], i) => (
							<th
								key={key}
								className={`border-b border-border bg-surface px-3 py-2 text-[11px] font-semibold tracking-[0.08em] whitespace-nowrap text-content-subtle uppercase ${
									type === "text" ||
									type === "date" ||
									type === "id"
										? "text-left"
										: "text-right"
								} ${i === 0 ? "sticky left-0 z-30 border-r border-border" : ""}`}
							>
								{header}
							</th>
						))}
					</tr>
				</thead>
				<tbody>
					{data.items.map((r, i) => (
						<tr
							key={i}
							className="border-b border-border/60 hover:bg-muted"
						>
							{COLS.map(([key, , type], ci) => (
								<td
									key={key}
									className={`px-3 py-1.5 whitespace-nowrap ${
										type === "text" ||
										type === "date" ||
										type === "id"
											? "text-left text-content"
											: "text-right tabular-nums text-content"
									} ${ci === 0 ? "sticky left-0 z-10 border-r border-border bg-card" : ""}`}
								>
									{cell(r[key], type)}
								</td>
							))}
						</tr>
					))}
				</tbody>
			</table>
			<div className="sticky bottom-0 border-t border-border bg-card px-3">
				<Pagination
					page={data.page}
					pages={data.pages}
					total={data.total}
					limit={data.limit}
					onChange={setPage}
				/>
			</div>
		</div>
	);
};
