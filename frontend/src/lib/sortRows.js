/**
 * Order rows by one accessor, ascending or descending.
 *
 * Shared because two features sort tables the same way, and a second copy of a comparator
 * is a second set of tie-breaking and blank-handling rules that drift apart silently.
 *
 * ⚠️ Blanks sink to the bottom in BOTH directions. A missing number is not a small one, and
 * floating them to the top of an ascending sort buries the rows somebody actually wants to
 * read. Strings compare with `localeCompare`, so accented and non-English names order the
 * way a reader expects rather than by code point.
 */
export const sortRows = (rows, pick, order = "desc") => {
	if (typeof pick !== "function") return rows;
	const dir = order === "asc" ? 1 : -1;
	return [...rows].sort((a, b) => {
		const x = pick(a);
		const y = pick(b);
		if (x == null && y == null) return 0;
		if (x == null) return 1;
		if (y == null) return -1;
		return typeof x === "string" ? dir * x.localeCompare(y) : dir * (x - y);
	});
};
