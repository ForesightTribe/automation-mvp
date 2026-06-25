/**
 * Generic data table — the tabular counterpart to the charts, reused across the
 * dashboard (analytics now, products/inventory later). `columns` is
 * [{ key, label, align?, render? }]; `render(row)` overrides the raw cell value
 * (e.g. to format currency). Numbers should pass `align: "right"`. The body
 * scrolls within `maxHeight` with a sticky header, so long lists (e.g. all
 * cities) stay usable.
 */
export const DataTable = ({ columns, rows, rowKey, maxHeight = 360 }) => {
	const keyOf = rowKey ?? ((_, i) => i);
	return (
		<div className="overflow-auto" style={{ maxHeight }}>
			<table className="w-full border-collapse text-sm">
				<thead className="sticky top-0 z-10 bg-card">
					<tr className="border-b border-border">
						{columns.map((c) => (
							<th
								key={c.key}
								className={`px-3 py-2 font-medium text-content-subtle ${
									c.align === "right"
										? "text-right"
										: "text-left"
								}`}
							>
								{c.label}
							</th>
						))}
					</tr>
				</thead>
				<tbody>
					{rows.map((row, i) => (
						<tr
							key={keyOf(row, i)}
							className="border-b border-border/60 last:border-0 hover:bg-muted/50"
						>
							{columns.map((c) => (
								<td
									key={c.key}
									className={`px-3 py-2 text-content ${
										c.align === "right"
											? "text-right tabular-nums"
											: "text-left"
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
