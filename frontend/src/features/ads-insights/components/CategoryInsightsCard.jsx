import { useMemo, useState } from "react";
import { Card } from "../../../components/ui/Card";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { HoverHint } from "../../../components/ui/HoverHint";
import { useSalesByCategory } from "../../analytics/hooks";
import { useDateRange } from "../../../context/DateRangeContext";
import { downloadCsv, exportName } from "../../../lib/exportTable";
import { formatCurrency, formatNumber } from "../../../lib/format";
import {
	ExportButton,
	LIFTED_L,
	NUM,
	NameCell,
	SectionExport,
	STICKY_HEAD,
	STICKY_NAME,
	SortHead,
	TD,
	useClientSort,
} from "./insightsTable";
import { CategoryDrawer } from "./CategoryDrawer";

/** What each column measures, in plain terms. Definitions, not platform notes. */
const ABOUT = {
	Category: "The category the product is sold under.",
	Revenue:
		"Total sales in the selected window for everything in this category.",
	Units: "How many units were sold.",
	AOV: "Average revenue per unit sold: revenue divided by units.",
	Share: "This category's share of total revenue. The bar shows the same number.",
};

/**
 * Category insights.
 */
export const CategoryInsightsCard = () => {
	const [scrolled, setScrolled] = useState(false);
	const [openRow, setOpenRow] = useState(null);
	const { range } = useDateRange();
	const { data, isLoading, error, refetch } = useSalesByCategory();

	const rows = useMemo(() => {
		const items = data ?? [];
		const total = items.reduce((s, r) => s + (r.revenue ?? 0), 0);
		return items.map((r) => ({
			...r,
			aov: r.units_sold ? r.revenue / r.units_sold : null,
			share: total ? (r.revenue / total) * 100 : null,
		}));
	}, [data]);

	const ACCESSORS = {
		category: (r) => r.category,
		revenue: (r) => r.revenue,
		units: (r) => r.units_sold,
		aov: (r) => r.aov,
		share: (r) => r.share,
	};
	const { sorted, sort, order, onSort } = useClientSort(
		rows,
		ACCESSORS,
		"revenue",
	);

	const columns = [
		{ header: "Category", value: (r) => r.category },
		{ header: "Revenue", value: (r) => r.revenue },
		{ header: "Units", value: (r) => r.units_sold },
		{
			header: "Revenue per unit",
			value: (r) => (r.aov == null ? "" : r.aov.toFixed(2)),
		},
		{
			header: "Share of revenue %",
			value: (r) => (r.share == null ? "" : r.share.toFixed(2)),
		},
	];

	const head = (label, key) => (
		<SortHead
			label={label}
			hint={ABOUT[label]}
			sortKey={key}
			sort={sort}
			order={order}
			onSort={onSort}
		/>
	);

	return (
		<div>
			<SectionExport>
				<ExportButton
					onExport={() =>
						downloadCsv(exportName("category-insights", range), [
							{
								title: `Category insights (sales), ${range.from} to ${range.to}`,
								columns,
								rows: sorted,
							},
						])
					}
					disabled={!sorted.length}
					hint="Exports category insights for the current filters."
				/>
			</SectionExport>
			<Card
				title="Category insights"
				actions={<div className="flex items-center gap-2"></div>}
			>
				{isLoading && <Loading label="Loading categories…" />}
				{error && (
					<ErrorState message={error.message} onRetry={refetch} />
				)}
				{!isLoading && !error && sorted.length === 0 && (
					<EmptyState message="No category sales in this window." />
				)}
				{!isLoading && !error && sorted.length > 0 && (
					<div
						onScroll={(e) =>
							setScrolled(e.currentTarget.scrollLeft > 0)
						}
						className="max-h-[70vh] overflow-auto"
					>
						<table
							className="w-full border-collapse"
							style={{ minWidth: 720 }}
						>
							<thead className="bg-card">
								<tr className="border-b border-border">
									<SortHead
										label="Category"
										hint={ABOUT.Category}
										sortKey="category"
										sort={sort}
										order={order}
										onSort={onSort}
										className={`${STICKY_NAME} ${STICKY_HEAD} ${scrolled ? LIFTED_L : ""} z-30`}
									/>
									{head("Revenue", "revenue")}
									{head("Units", "units")}
									{head("AOV", "aov")}
									{head("Share", "share")}
								</tr>
							</thead>
							<tbody>
								{sorted.map((r) => (
									<tr
										key={r.category}
										className="group border-b border-border/60 last:border-0 hover:bg-muted"
									>
										<NameCell
											name={r.category}
											scrolled={scrolled}
											width="16rem"
											onOpen={() => setOpenRow(r)}
										/>
										<td className={NUM}>
											{formatCurrency(r.revenue)}
										</td>
										<td className={NUM}>
											{formatNumber(r.units_sold)}
										</td>
										<td className={NUM}>
											{r.aov == null
												? "—"
												: formatCurrency(r.aov)}
										</td>
										<td className={`${TD} w-48`}>
											{/* The bar makes the ranking readable at a glance; the number stays,
										    because a bar alone cannot be read off precisely. */}
											<div className="flex items-center justify-end gap-2">
												<span className="tabular-nums">
													{r.share == null
														? "—"
														: `${r.share.toFixed(1)}%`}
												</span>
												<span className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
													<span
														className="block h-full rounded-full bg-brand"
														style={{
															width: `${Math.min(100, r.share ?? 0)}%`,
														}}
													/>
												</span>
											</div>
										</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>
				)}
				<CategoryDrawer
					row={openRow}
					range={range}
					open={Boolean(openRow)}
					onClose={() => setOpenRow(null)}
				/>
			</Card>
		</div>
	);
};
