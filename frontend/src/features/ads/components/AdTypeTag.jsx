/** Small pills naming the Zepto ad types a row's spend came from.
 *
 * Rows combine ad types by default, so without these a client cannot tell
 * whether a SKU's spend was Sponsored Products or Sponsored Brands. Genuinely
 * plural in practice: Cheese ran under both.
 *
 * Colour-coded rather than plain grey so the distinction reads at a glance in a
 * dense table, and shortened — the full "Sponsored Products" is too long for a
 * cell that already carries a product name.
 */
const TAGS = {
	sponsored_products: {
		label: "Products",
		className: "bg-brand/10 text-brand",
	},
	sponsored_brands: {
		label: "Brands",
		className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
	},
	sponsored_display: {
		label: "Display",
		className: "bg-amber-500/10 text-amber-600 dark:text-amber-500",
	},
};

export const AdTypeTag = ({ types = [] }) => {
	if (!types.length) return null;
	return (
		<span className="inline-flex flex-wrap gap-1">
			{types.map((t) => {
				const tag = TAGS[t] ?? { label: t, className: "bg-muted text-content-muted" };
				return (
					<span
						key={t}
						title={t.replace(/_/g, " ")}
						className={`rounded px-1.5 py-0.5 text-[10px] font-medium leading-none ${tag.className}`}
					>
						{tag.label}
					</span>
				);
			})}
		</span>
	);
};
