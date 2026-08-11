/**
 * SKU health pill. Mirrors the server-derived `status` from product_service
 * (out_of_stock / low_cover / no_sales / healthy). Unknown values fall back to a
 * neutral chip so the table never breaks on a new status.
 */
// Exact palette values rather than the generic status tokens: these pills are
// spec'd per state, and `no_sales` deliberately shares `low_cover`'s amber.
const STYLES = {
	out_of_stock: {
		label: "Out of stock",
		cls: "bg-[#fff1f2] text-[#be123c]",
	},
	low_cover: { label: "Low cover", cls: "bg-[#fffbeb] text-[#b45309]" },
	no_sales: { label: "No sales", cls: "bg-[#fffbeb] text-[#b45309]" },
	healthy: { label: "Healthy", cls: "bg-[#f0fdf4] text-[#15803d]" },
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
