import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";

/**
 * Generic data table — the tabular counterpart to the charts, reused across the
 * dashboard (analytics now, products/inventory later). `columns` is
 * [{ key, label, align?, render?, sortValue?, sortable?, hint? }]; `render(row)` overrides the raw
 * value. `onRowClick(row)` makes each row a target — the row is the record, so the whole
 * row is the hit area rather than a link in one cell.
 * cell value (e.g. to format currency). Numbers should pass `align: "right"`. The body
 * scrolls within `maxHeight` with a sticky header, so long lists (e.g. all
 * cities) stay usable.
 *
 * Narrow viewports: `min-w` makes the table scroll sideways rather than crushing
 * its columns, and the first column is pinned so you can still tell which row
 * you are reading. Override `minWidth` for tables with unusually few columns.
 *
 * `pinLast` pins the LAST column too, for tables whose final column holds the row's
 * controls: scrolling sideways to read a number and then back again to act on it is how
 * the wrong row gets clicked.
 *
 * ⚠️ A pinned cell must carry its own opaque `bg-card`. The row's background does not
 * paint under a sticky cell, so without it the columns underneath show straight through
 * as they scroll past. The header's pinned cells sit a layer above the body's for the
 * same reason — where the sticky row and the sticky column cross, one of them has to
 * win, and it has to be the header.
 *
 * Sorting is on by default and needs no work at the call site: a column sorts on `row[key]`,
 * or on `sortValue(row)` where the raw value is not what the reader sees (a formatted date,
 * a rendered node). Set `sortable: false` on a column that genuinely has no order, or
 * `sortable={false}` on the table where the row order carries meaning of its own, such as a
 * chronological log or an already-ranked list.
 */
const Labelled = ({ column }) =>
	column.hint ? (
		<span className="cursor-help border-b border-dotted border-content-subtle/70">
			{column.label}
		</span>
	) : (
		column.label
	);

export const DataTable = ({
	columns,
	rows,
	rowKey,
	onRowClick,
	maxHeight = 360,
	minWidth = 640,
	pinLast = false,
	sortable = true,
	// The column key to start on. Without one the rows keep the order they arrived in,
	// which is usually the order the endpoint intended.
	defaultSort = null,
	defaultOrder = "desc",
	// Controlled sorting: pass all three to have the caller own the order.
	sortKey,
	sortOrder,
	onSortChange,
	// Optional override for the header row's type. The default is the house header style,
	// so a feature can ask for a different label treatment without changing the table
	// everywhere else.
	headClass = "px-3 py-2 font-medium whitespace-nowrap text-content-subtle",
}) => {
	const keyOf = rowKey ?? ((_, i) => i);
	const [localSort, setLocalSort] = useState(defaultSort);
	const [localOrder, setLocalOrder] = useState(defaultOrder);

	// Controlled when the caller owns the order. Paginated tables use this so a
	// header sorts the whole set through the API, not the page in hand.
	const controlled = Boolean(onSortChange);
	const sort = controlled ? sortKey : localSort;
	const order = controlled ? (sortOrder ?? "desc") : localOrder;

	const canSort = (c) => sortable && c.sortable !== false;
	const valueOf = (c, row) => (c.sortValue ? c.sortValue(row) : row[c.key]);

	const sorted = useMemo(() => {
		// Already ordered by the caller.
		if (controlled) return rows;
		const col = sort && columns.find((c) => c.key === sort);
		if (!col) return rows;
		const dir = order === "asc" ? 1 : -1;
		return [...rows].sort((a, b) => {
			const x = valueOf(col, a);
			const y = valueOf(col, b);
			// Blanks sink in both directions: a missing value is not a small one.
			if (x == null && y == null) return 0;
			if (x == null) return 1;
			if (y == null) return -1;
			return typeof x === "string" || typeof y === "string"
				? dir * String(x).localeCompare(String(y))
				: dir * (x - y);
		});
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [rows, columns, sort, order, controlled]);

	const onSort = (key) => {
		const next = key === sort && order === "desc" ? "asc" : "desc";
		if (controlled) {
			onSortChange(key, next);
			return;
		}
		setLocalSort(key);
		setLocalOrder(next);
	};

	return (
		<div className="overflow-auto" style={{ maxHeight }}>
			<table
				className="w-full border-collapse text-sm"
				style={{ minWidth }}
			>
				<thead className="sticky top-0 z-10 bg-card">
					<tr className="border-b border-border">
						{columns.map((c, i) => (
							<th
								key={c.key}
								aria-sort={
									sort === c.key
										? order === "asc"
											? "ascending"
											: "descending"
										: undefined
								}
								className={`${headClass} ${
									c.align === "right"
										? "text-right"
										: "text-left"
								} ${i === 0 ? "sticky left-0 z-30 bg-card" : ""} ${
									pinLast && i === columns.length - 1
										? "sticky right-0 z-30 border-l border-border bg-card"
										: ""
								}`}
							>
								{canSort(c) ? (
									<button
										type="button"
										title={c.hint}
										onClick={() => onSort(c.key)}
										className={`inline-flex items-center gap-1 transition-colors hover:text-content ${
											sort === c.key ? "text-content" : ""
										} ${c.align === "right" ? "flex-row-reverse" : ""}`}
									>
										<Labelled column={c} />
										{(() => {
											const active = sort === c.key;
											const Arrow = active
												? order === "asc"
													? ArrowUp
													: ArrowDown
												: ChevronsUpDown;
											return (
												<Arrow
													size={11}
													aria-hidden
													className={
														active
															? "text-brand"
															: "text-content-subtle/50"
													}
												/>
											);
										})()}
									</button>
								) : (
									<span title={c.hint}>
										<Labelled column={c} />
									</span>
								)}
							</th>
						))}
					</tr>
				</thead>
				<tbody>
					{sorted.map((row, i) => (
						<tr
							key={keyOf(row, i)}
							onClick={
								onRowClick ? () => onRowClick(row) : undefined
							}
							className={`border-b border-border/60 last:border-0 hover:bg-muted/50 ${
								onRowClick ? "cursor-pointer" : ""
							}`}
						>
							{columns.map((c, ci) => (
								<td
									key={c.key}
									className={`px-3 py-2 text-content ${
										c.align === "right"
											? "text-right tabular-nums"
											: "text-left"
									} ${ci === 0 ? "sticky left-0 z-20 bg-card" : ""} ${
										pinLast && ci === columns.length - 1
											? "sticky right-0 z-20 border-l border-border bg-card"
											: ""
									}`}
								>
									{c.render ? c.render(row) : row[c.key]}
								</td>
							))}
						</tr>
					))}
				</tbody>
			</table>
		</div>
	);
};
