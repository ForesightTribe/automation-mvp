/**
 * Display formatters. The data is Indian-market (Blinkit), so money is INR and
 * large numbers read better in the Indian grouping (lakh/crore). Keep all
 * number/date formatting here so it stays consistent across every card.
 */

const inrCurrency = new Intl.NumberFormat("en-IN", {
	style: "currency",
	currency: "INR",
	maximumFractionDigits: 0,
});

const inrNumber = new Intl.NumberFormat("en-IN");

/** ₹1,23,456 — whole rupees. */
export const formatCurrency = (value) =>
	value === null || value === undefined ? "—" : inrCurrency.format(value);

/** 1,23,456 — Indian-grouped integer. */
export const formatNumber = (value) =>
	value === null || value === undefined ? "—" : inrNumber.format(value);

/**
 * Per-unit price with its basis suffix: ₹6.25 / 100 ml. The values are small
 * (≈₹6–₹311), so unlike formatCurrency (whole rupees) this keeps 2 decimals. `uom`
 * is the pack UOM from the API ("ml" | "g" | "pc"); the basis matches the backend
 * (₹ per 100 ml/g, ₹ per piece). Returns "—" when either input is missing.
 */
const UNIT_BASIS = { ml: "100 ml", g: "100 g", pc: "piece" };
export const formatUnitPrice = (value, uom) => {
	if (value === null || value === undefined || !uom) return "—";
	const basis = UNIT_BASIS[uom];
	if (!basis) return "—";
	return `₹${Number(value).toFixed(2)} / ${basis}`;
};

/** Compact money for KPI tiles: ₹1.2L, ₹3.4Cr. */
export const formatCompactCurrency = (value) => {
	if (value === null || value === undefined) return "—";
	if (value >= 1e7) return `₹${(value / 1e7).toFixed(1)}Cr`;
	if (value >= 1e5) return `₹${(value / 1e5).toFixed(1)}L`;
	if (value >= 1e3) return `₹${(value / 1e3).toFixed(1)}K`;
	return inrCurrency.format(value);
};

/** 0.42 -> "42%". */
export const formatPercent = (value, digits = 0) =>
	value === null || value === undefined
		? "—"
		: `${(value * 100).toFixed(digits)}%`;

/** ISO/Date -> "23 Jun 2026". */
export const formatDate = (value) => {
	if (!value) return "—";
	const d = value instanceof Date ? value : new Date(value);
	return Number.isNaN(d.getTime())
		? "—"
		: d.toLocaleDateString("en-IN", {
				day: "2-digit",
				month: "short",
				year: "numeric",
			});
};
