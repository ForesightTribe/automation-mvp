/**
 * The Availability page's export sections, defined once.
 *
 * The page-level export composes all of them; each card exports only its own.
 * One definition means a section's columns can never differ between the two.
 */
const pct = (v) => (v == null ? "" : Number(v).toFixed(1));

export const citySection = (cities, kind) => {
	const rows = cities?.cities ?? [];
	if (!rows.length) return null;
	return {
		title: `Availability by city (${kind})`,
		columns: [
			{ header: "City", value: (r) => r.city },
			{ header: "Stores", value: (r) => r.stores },
			{ header: "Out of stock", value: (r) => r.skus_out_of_stock },
			{ header: "Missing listings", value: (r) => r.skus_not_listed },
			{ header: "In stock %", value: (r) => pct(r.distribution_pct) },
		],
		rows,
	};
};

export const storeSection = (stores, kind) => {
	const rows = stores?.stores ?? [];
	if (!rows.length) return null;
	const range = stores?.active_range ?? 0;
	return {
		title: `Availability by store (${kind})`,
		columns: [
			{
				header: "Store",
				value: (r) => r.store_name || `Store ${r.merchant_id}`,
			},
			{ header: "Store id", value: (r) => r.merchant_id },
			{ header: "City", value: (r) => r.city },
			{ header: "Store type", value: (r) => r.merchant_type ?? "" },
			{ header: "On shelf", value: (r) => r.skus_listed },
			{ header: "Active range", value: () => range },
			{ header: "Out of stock", value: (r) => r.skus_out_of_stock },
			{ header: "Never stocked", value: (r) => r.skus_not_listed },
			{ header: "In stock %", value: (r) => pct(r.distribution_pct) },
		],
		rows,
	};
};

export const productSection = (products, stores, kind) => {
	const rows = products?.skus ?? [];
	if (!rows.length) return null;
	const scraped = stores?.stores_scraped ?? 0;
	return {
		title: `Availability by product (${kind})`,
		columns: [
			{
				header: "Product",
				value: (r) => r.product_name || r.platform_product_id,
			},
			{ header: "Stores carrying it", value: (r) => r.stores_listed },
			{ header: "Stores checked", value: () => scraped },
			{ header: "Store coverage %", value: (r) => pct(r.reach_pct) },
			{ header: "Out of stock", value: (r) => r.stores_out_of_stock },
			{ header: "In stock %", value: (r) => pct(r.distribution_pct) },
		],
		rows,
	};
};

export const historySection = (history) => {
	const rows = history?.points ?? [];
	if (!rows.length) return null;
	return {
		title: "Availability over time",
		columns: [
			{ header: "Week", value: (r) => r.week },
			{ header: "Available %", value: (r) => pct(r.availability_pct) },
			{ header: "Out of stock %", value: (r) => pct(r.oos_pct) },
			{ header: "Low stock %", value: (r) => pct(r.low_stock_pct) },
			{ header: "Stores sampled", value: (r) => r.stores },
		],
		rows,
	};
};

export const pricingSection = (pricing) => {
	const rows = pricing?.skus ?? [];
	if (!rows.length) return null;
	return {
		title: "Price across stores",
		columns: [
			{
				header: "Product",
				value: (r) => r.product_name || r.platform_product_id,
			},
			{ header: "Stores", value: (r) => r.stores },
			{ header: "Min price", value: (r) => r.min_price ?? "" },
			{ header: "Median price", value: (r) => r.median_price ?? "" },
			{ header: "Max price", value: (r) => r.max_price ?? "" },
			{ header: "Avg discount %", value: (r) => pct(r.avg_discount) },
		],
		rows,
	};
};

/**
 * Needs attention, for one tab. Exports the FULL ranked list, not the top 8 the
 * card shows — a worklist is only useful complete.
 */
export const needsAttentionSections = (products, cities, tab, scraped) => {
	const productKey = tab === "oos" ? "stores_out_of_stock" : "_missing";
	const cityKey = tab === "oos" ? "skus_out_of_stock" : "skus_not_listed";
	const what = tab === "oos" ? "Out of stock" : "Missing listings";

	const skus = (products?.skus ?? [])
		.map((s) => ({ ...s, _missing: scraped - s.stores_listed }))
		.filter((s) => s[productKey] > 0)
		.sort((a, b) => b[productKey] - a[productKey]);

	const places = (cities?.cities ?? [])
		.filter((c) => c[cityKey] > 0)
		.sort((a, b) => b[cityKey] - a[cityKey]);

	return [
		skus.length && {
			title: `${what} — worst products`,
			columns: [
				{
					header: "Product",
					value: (r) => r.product_name || r.platform_product_id,
				},
				{ header: "Stores affected", value: (r) => r[productKey] },
				{ header: "Stores carrying it", value: (r) => r.stores_listed },
				{ header: "Stores checked", value: () => scraped },
			],
			rows: skus,
		},
		places.length && {
			title: `${what} — worst cities`,
			columns: [
				{ header: "City", value: (r) => r.city },
				{ header: "Products affected", value: (r) => r[cityKey] },
				{ header: "Stores", value: (r) => r.stores },
				{ header: "In stock %", value: (r) => pct(r.distribution_pct) },
			],
			rows: places,
		},
	].filter(Boolean);
};
