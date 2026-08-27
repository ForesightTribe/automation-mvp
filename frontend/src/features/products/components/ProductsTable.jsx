import { useNavigate } from "react-router-dom";
import { StatusBadge } from "./StatusBadge";
import { formatCurrency, formatNumber } from "../../../lib/format";

// Fixed sort direction per column (backend sorts each key one way: bigger-better
// for money/units, smaller-first for cover so the at-risk SKUs surface).
const DIRECTION = {
	revenue: "desc",
	units: "desc",
	price: "desc",
	cover: "asc",
};

const coverLabel = (v) => (v === null || v === undefined ? "—" : `${v}d`);

/** Every column except Product is right-aligned, header and cell together. */
const CELL =
	"px-1.5 py-2 text-right lg:px-3 lg:py-3 2xl:px-4 2xl:py-4";
const HEAD = `${CELL} font-medium text-content-subtle`;

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
			<th className={CELL}>
				{/* The arrow is absolutely positioned so it takes no width: the
				    label keeps the same right edge as the numbers below it whether
				    or not this column is the active sort. */}
				<button
					type="button"
					onClick={() => onSort(sortKey)}
					className={`relative inline-flex items-center font-medium hover:text-content ${
						active ? "text-content" : "text-content-subtle"
					}`}
				>
					{label}
					{arrow && (
						<span
							className="absolute top-1/2 -right-3 -translate-y-1/2 text-[10px]"
							aria-hidden
						>
							{arrow}
						</span>
					)}
				</button>
			</th>
		);
	};

	return (
		<div className="overflow-auto">
			<table className="w-full min-w-225 table-fixed border-collapse text-xs lg:text-[13px] 2xl:text-sm">
				{/* Widths are declared once here rather than left to the content,
				    so a long SKU name or a six-figure number can't shift every
				    column. Percentages keep it fluid; `min-w` on the table makes it
				    scroll instead of crushing on narrow screens. */}
				<colgroup>
					<col className="w-[26%]" />
					<col className="w-[16%]" />
					<col className="w-[9%]" />
					<col className="w-[10%]" />
					<col className="w-[9%]" />
					<col className="w-[14%]" />
					<col className="w-[8%]" />
					<col className="w-[8%]" />
				</colgroup>
				<thead className="sticky top-0 z-10 bg-card">
					<tr className="border-b border-border">
						<th className="px-1.5 py-2 text-left font-medium text-content-subtle lg:px-3 lg:py-3 2xl:px-4 2xl:py-4">
							Product
						</th>
						<th className={HEAD}>Category</th>
						<SortHead label="Units" sortKey="units" />
						<SortHead label="Revenue" sortKey="revenue" />
						<SortHead label="Avg. Price" sortKey="price" />
						<th className={HEAD}>Stock (FE/BE)</th>
						<SortHead label="Cover" sortKey="cover" />
						<th className={HEAD}>Status</th>
					</tr>
				</thead>
				<tbody>
					{rows.map((r) => (
						<tr
							key={r.item_id}
							onClick={() => navigate(`/products/${r.item_id}`)}
							className="cursor-pointer border-b border-border/60 last:border-0 hover:bg-muted/50"
						>
							<td className="px-1.5 py-2 text-left lg:px-3 lg:py-3 2xl:px-4 2xl:py-4">
								<div className="truncate font-medium text-content">
									{r.item_name || r.item_id}
								</div>
								<div className="truncate text-xs text-content-subtle">
									{r.item_id}
								</div>
							</td>
							<td className={`${CELL} text-content-muted`}>
								{r.category || "—"}
							</td>
							<td className={`${CELL} tabular-nums text-content`}>
								{formatNumber(r.units_sold)}
							</td>
							<td className={`${CELL} tabular-nums text-content`}>
								{formatCurrency(r.revenue)}
							</td>
							<td className={`${CELL} tabular-nums text-content`}>
								{formatCurrency(r.avg_price)}
							</td>
							<td className={`${CELL} tabular-nums text-content`}>
								{formatNumber(r.frontend_qty)}
								<span className="text-content-subtle">
									{" "}
									/ {formatNumber(r.backend_qty)}
								</span>
							</td>
							<td className={`${CELL} tabular-nums text-content`}>
								{coverLabel(r.days_of_cover)}
							</td>
							<td className={CELL}>
								<StatusBadge status={r.status} />
							</td>
						</tr>
					))}
				</tbody>
			</table>
		</div>
	);
};
