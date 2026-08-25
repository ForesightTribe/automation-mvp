/** Shared ad-type filter for the Zepto cards.
 *
 * Zepto's own Analytics page splits Sponsored Products / Display / Brands into
 * top-level tabs. We combine them instead and offer this as a filter, because
 * the split is very lopsided in practice — one client ran 97% of spend through
 * Sponsored Products, 3% through Brands and nothing through Display, so three
 * tabs would mean two empty ones. Combining is safe: the tabs are disjoint, so
 * summing them double-counts nothing.
 */
export const AD_TYPE_OPTIONS = [
	{ value: "", label: "All ad types" },
	{ value: "sponsored_products", label: "Sponsored Products" },
	{ value: "sponsored_brands", label: "Sponsored Brands" },
	{ value: "sponsored_display", label: "Sponsored Display" },
];

export const AdTypeSelect = ({ value, onChange, options = AD_TYPE_OPTIONS }) => (
	<select
		value={value}
		onChange={(e) => onChange(e.target.value)}
		className="rounded-md border border-border bg-card px-2.5 py-1 text-sm text-content focus:outline-none focus:ring-2 focus:ring-brand/30"
	>
		{options.map((o) => (
			<option key={o.value} value={o.value}>
				{o.label}
			</option>
		))}
	</select>
);
