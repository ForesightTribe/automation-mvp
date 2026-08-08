/**
 * SKU health pill. Mirrors the server-derived `status` from product_service
 * (out_of_stock / low_cover / no_sales / healthy). Unknown values fall back to a
 * neutral chip so the table never breaks on a new status.
 */
const STYLES = {
	out_of_stock: { label: "Out of stock", cls: "bg-danger-soft text-danger" },
	low_cover: { label: "Low cover", cls: "bg-warning-soft text-warning" },
	no_sales: { label: "No sales", cls: "bg-warning-soft text-warning" },
	healthy: { label: "Healthy", cls: "bg-success-soft text-success" },
};

export const StatusBadge = ({ status }) => {
	const s = STYLES[status] ?? {
		label: status ?? "—",
		cls: "bg-muted text-content-muted",
	};
	return (
		<span
			className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${s.cls}`}
		>
			{s.label}
		</span>
	);
};

/** Filter options for the status dropdown ("" = all). */
export const STATUS_OPTIONS = [
	{ value: "", label: "All statuses" },
	{ value: "out_of_stock", label: "Out of stock" },
	{ value: "low_cover", label: "Low cover" },
	{ value: "no_sales", label: "No sales" },
	{ value: "healthy", label: "Healthy" },
];
