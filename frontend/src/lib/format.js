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

/**
 * A server timestamp → epoch milliseconds, read as IST.
 *
 * ⚠️ The backend stores and returns NAIVE IST wall-clock values ("2026-09-22T11:56:47", no
 * offset — see `app/utils/time.now_ist`). `new Date(value)` reads a naive value as the
 * BROWSER's local time, so anything measuring elapsed time is wrong by the browser's offset
 * from IST: on a UTC machine a "5 minutes after it finished" rule would run for five and a
 * half hours. Use this wherever a duration is computed from a server time; a value that
 * already carries an offset or a `Z` is left as it is.
 */
export const parseIst = (value) => {
	if (!value) return null;
	const s = String(value);
	const withZone = /(Z|[+-]\d\d:?\d\d)$/.test(s) ? s : `${s}+05:30`;
	const ms = Date.parse(withZone);
	return Number.isNaN(ms) ? null : ms;
};

/**
 * ISO/Date -> "7 Sept 2026, 4:00 pm".
 *
 * Separate from `formatDate` because a LOG without a time answers half the question —
 * "did this happen before or after the change I made an hour ago" is the whole point of
 * reading one. Falls back to the raw value rather than "—": in a log, an unparseable
 * timestamp is evidence, and hiding it loses the only clue to what went wrong.
 */
export const formatDateTime = (value) => {
	if (!value) return "—";
	const d = value instanceof Date ? value : new Date(value);
	return Number.isNaN(d.getTime())
		? String(value)
		: d.toLocaleString("en-IN", {
				day: "numeric",
				month: "short",
				year: "numeric",
				hour: "numeric",
				minute: "2-digit",
				hour12: true,
			});
};

/**
 * A measurement store, said in full: `("Block C", "Kolkata")` -> "Block C, Kolkata".
 *
 * Store labels are sub-city names — "Block C", "Sector 110", "Financial District" — and they
 * repeat across the country, so a label on its own does not say where position was measured.
 * Either half may be missing: an unresolved city shows the label alone, and a store whose
 * label we never scraped shows the city alone rather than a dangling comma.
 */
export const formatMeasuredAt = (locationName, cityName) => {
	const store = (locationName ?? "").trim();
	const city = (cityName ?? "").trim();
	if (!store || !city) return store || city || null;
	// ⚠️ Skip the city when the label already carries it. 49 catalogue stores have no
	// `location_name` of their own and fall back to "<city>/<merchant_id>" (see
	// docs/darkstores.md), which would otherwise read "ahmednagar/41317, Ahmednagar".
	return store.toLowerCase().includes(city.toLowerCase())
		? store
		: `${store}, ${city}`;
};
