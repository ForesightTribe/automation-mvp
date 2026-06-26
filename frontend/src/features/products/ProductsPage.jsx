import { useEffect, useState } from "react";
import { useProducts } from "./hooks";
import { ProductsKpiStrip } from "./components/ProductsKpiStrip";
import { ProductsTable } from "./components/ProductsTable";
import { STATUS_OPTIONS } from "./components/StatusBadge";
import { Card } from "../../components/ui/Card";
import { Pagination } from "../../components/ui/Pagination";
import { Loading } from "../../components/feedback/Loading";
import { ErrorState } from "../../components/feedback/ErrorState";
import { EmptyState } from "../../components/feedback/EmptyState";
import { useDateRange } from "../../context/DateRangeContext";
import { useMarketplaces } from "../../context/MarketplaceContext";

const LIMIT = 20;

/** Debounce a fast-changing value (the search box) so we don't fire a query per
 * keystroke. */
const useDebounced = (value, delay = 300) => {
	const [debounced, setDebounced] = useState(value);
	useEffect(() => {
		const t = setTimeout(() => setDebounced(value), delay);
		return () => clearTimeout(t);
	}, [value, delay]);
	return debounced;
};

/**
 * Products — "per-SKU deep dive". Composition root for the list view: a KPI strip
 * (catalogue size, revenue, attention counts) over a filterable, sortable,
 * paginated SKU table. One `useProducts` call feeds both — the response carries
 * `summary` (window-scoped) and `products` (the page). Rows link to Product 360.
 */
export const ProductsPage = () => {
	const [searchInput, setSearchInput] = useState("");
	const search = useDebounced(searchInput);
	const [status, setStatus] = useState("");
	const [sort, setSort] = useState("revenue");
	const [page, setPage] = useState(1);

	// Reset to page 1 whenever the result set changes shape.
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	useEffect(() => {
		setPage(1);
	}, [search, status, sort, range, selected]);

	const { data, isLoading, error, refetch, isFetching } = useProducts({
		page,
		limit: LIMIT,
		sort,
		status,
		search,
	});

	const rows = data?.products?.items ?? [];

	const onSort = (key) => {
		setSort(key);
	};

	return (
		<div className="flex flex-col gap-6">
			<div>
				<h1 className="font-display text-xl font-bold text-content">
					Products
				</h1>
				<p className="text-sm text-content-muted">
					Per-SKU deep dive — sales, stock, and days of cover.
				</p>
			</div>

			<ProductsKpiStrip summary={data?.summary} />

			<Card
				title="SKUs"
				actions={
					<div className="flex items-center gap-2">
						<input
							type="search"
							value={searchInput}
							onChange={(e) => setSearchInput(e.target.value)}
							placeholder="Search SKU…"
							className="w-44 rounded-md border border-border bg-card px-2.5 py-1 text-sm text-content placeholder:text-content-subtle focus:outline-none focus:ring-2 focus:ring-primary/30"
						/>
						<select
							value={status}
							onChange={(e) => setStatus(e.target.value)}
							className="rounded-md border border-border bg-card px-2.5 py-1 text-sm text-content focus:outline-none focus:ring-2 focus:ring-primary/30"
						>
							{STATUS_OPTIONS.map((o) => (
								<option key={o.value} value={o.value}>
									{o.label}
								</option>
							))}
						</select>
					</div>
				}
			>
				{isLoading && <Loading label="Loading products…" />}
				{error && (
					<ErrorState message={error.message} onRetry={refetch} />
				)}
				{!isLoading &&
					!error &&
					(rows.length === 0 ? (
						<EmptyState message="No SKUs match these filters in this window." />
					) : (
						<div
							className={
								isFetching
									? "opacity-60 transition-opacity"
									: ""
							}
						>
							<ProductsTable
								rows={rows}
								sort={sort}
								onSort={onSort}
							/>
							<Pagination
								page={data.products.page}
								pages={data.products.pages}
								total={data.products.total}
								limit={data.products.limit}
								onChange={setPage}
							/>
						</div>
					))}
			</Card>
		</div>
	);
};
