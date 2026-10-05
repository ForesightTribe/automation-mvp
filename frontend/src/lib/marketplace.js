/**
 * What each marketplace can and cannot report, so components stop hard-coding
 * `marketplace === "zepto"` in a dozen places and drifting apart as we add more.
 *
 * These are facts about the source data, not display preferences:
 *
 * - **Blinkit** has a warehouse tier feeding its stores, so stock splits into
 *   backend (in the warehouse) and frontend (on the shelf).
 * - **Zepto** reports one stock figure per SKU and no facility dimension at all.
 * - **Instamart** ships straight from the dark store: there is a per-store
 *   figure but no warehouse behind it, so a backend column would be a column of
 *   zeros — which reads as an empty back room rather than "no such thing".
 */

const BACKEND_STOCK_MARKETPLACES = new Set(["blinkit"]);

/** Does this marketplace report a backend/frontend stock split worth showing? */
export const hasBackendStock = (marketplace) =>
	BACKEND_STOCK_MARKETPLACES.has(marketplace ?? "blinkit");

/**
 * The header for a stock column: "Stock (FE/BE)" only means something where a
 * split exists. Takes the rows so a mixed list (several marketplaces selected)
 * keeps the split label as long as any row actually has one.
 */
export const stockColumnLabel = (rows = []) =>
	rows.length && rows.some((r) => hasBackendStock(r.marketplace))
		? "Stock (FE/BE)"
		: "Stock";

/**
 * Display name for a marketplace slug. Centralised because the alternative —
 * a ternary at each call site — silently mislabels every marketplace that is
 * not one of the two it was written for, and that mislabel is not cosmetic:
 * it sends the reader after the wrong mapping, the wrong portal, the wrong team.
 */
const NAMES = {
	blinkit: "Blinkit",
	zepto: "Zepto",
	instamart: "Instamart",
};

export const marketplaceName = (slug) =>
	NAMES[slug] ?? (slug ? slug[0].toUpperCase() + slug.slice(1) : "this marketplace");
