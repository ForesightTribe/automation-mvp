import { useNavigate } from "react-router-dom";
import { StatusBadge } from "./StatusBadge";
import { formatCompactCurrency, formatNumber } from "../../../lib/format";

// Fixed sort direction per column (backend sorts each key one way: bigger-better
// for money/units, smaller-first for cover so the at-risk SKUs surface).
const DIRECTION = {
	revenue: "desc",
	units: "desc",
	price: "desc",
	cover: "asc",
};

const coverLabel = (v) => (v === null || v === undefined ? "—" : `${v}d`);

/**
 * The SKU table: window sales joined with current stock + days-of-cover + a
 * health badge. Money/unit/price/cover headers are click-to-sort (single key,
 * fixed direction — matches the API's `sort` param). Rows link to the Product 360
 * detail. Presentational: filter/sort/page state lives in ProductsPage.
 */
export const ProductsTable = ({ rows, sort, onSort }) => {
	const navigate = useNavigate();

	const SortHead = ({ label, sortKey }) => {
		const active = sort === sortKey;
		const arrow = active ? (DIRECTION[sortKey] === "asc" ? "▲" : "▼") : "";
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
		<div className="overflow-auto">
			<table className="w-full border-collapse text-sm">
				<thead className="sticky top-0 z-10 bg-card">
					<tr className="border-b border-border">
						<th className="px-3 py-2 text-left font-medium text-content-subtle">
							Product
						</th>
						<th className="px-3 py-2 text-left font-medium text-content-subtle">
							Category
						</th>
						<SortHead label="Units" sortKey="units" />
						<SortHead label="Revenue" sortKey="revenue" />
						<SortHead label="Avg price" sortKey="price" />
						<th className="px-3 py-2 text-right font-medium text-content-subtle">
							Stock (FE/BE)
						</th>
						<SortHead label="Cover" sortKey="cover" />
						<th className="px-3 py-2 text-left font-medium text-content-subtle">
							Status
						</th>
					</tr>
				</thead>
				<tbody>
					{rows.map((r) => (
						<tr
							key={r.item_id}
							onClick={() => navigate(`/products/${r.item_id}`)}
							className="cursor-pointer border-b border-border/60 last:border-0 hover:bg-muted/50"
						>
							<td className="px-3 py-2">
								<div className="font-medium text-content">
									{r.item_name || r.item_id}
								</div>
								<div className="text-xs text-content-subtle">
									{r.item_id}
								</div>
							</td>
							<td className="px-3 py-2 text-content-muted">
								{r.category || "—"}
							</td>
							<td className="px-3 py-2 text-right tabular-nums text-content">
								{formatNumber(r.units_sold)}
							</td>
							<td className="px-3 py-2 text-right tabular-nums text-content">
								{formatCompactCurrency(r.revenue)}
							</td>
							<td className="px-3 py-2 text-right tabular-nums text-content">
								{formatCompactCurrency(r.avg_price)}
							</td>
							<td className="px-3 py-2 text-right tabular-nums text-content">
								{formatNumber(r.frontend_qty)}
								<span className="text-content-subtle">
									{" "}
									/ {formatNumber(r.backend_qty)}
								</span>
							</td>
							<td className="px-3 py-2 text-right tabular-nums text-content">
								{coverLabel(r.days_of_cover)}
							</td>
							<td className="px-3 py-2">
								<StatusBadge status={r.status} />
							</td>
						</tr>
					))}
				</tbody>
			</table>
		</div>
	);
};
