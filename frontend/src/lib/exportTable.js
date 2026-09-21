/**
 * Client-side table export.
 *
 * CSV rather than a real .xlsx: Excel opens it natively, it needs no dependency, and the
 * alternative (a bundled xlsx writer) adds ~1 MB to a dashboard for the sake of a file
 * format. The BOM is what makes Excel read it as UTF-8, without which ₹ and any Hindi text
 * arrive as mojibake.
 *
 * Sections exist because one download often needs to carry more than one table (a KPI
 * block, then the daily rows). Excel shows them stacked with a blank line between, which is
 * the honest shape of it: sheets would need a real workbook writer.
 */
const cell = (v) => {
	if (v == null) return "";
	const s = String(v);
	// Anything with a comma, quote or newline has to be quoted, and a quote inside doubled.
	return /[",\n\r]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
};

/** [{ title, columns: [{ header, value }], rows }] → one CSV string. */
export const toCsv = (sections) =>
	sections
		.map(({ title, columns, rows }) => {
			const head = columns.map((c) => cell(c.header)).join(",");
			const body = rows
				.map((r) => columns.map((c) => cell(c.value(r))).join(","))
				.join("\n");
			return [title ? cell(title) : null, head, body]
				.filter(Boolean)
				.join("\n");
		})
		.join("\n\n");

/** Hands the browser a file. Revokes the object URL, or the blob is held for the session. */
export const downloadCsv = (filename, sections) => {
	const blob = new Blob([`﻿${toCsv(sections)}`], {
		type: "text/csv;charset=utf-8;",
	});
	const url = URL.createObjectURL(blob);
	const a = document.createElement("a");
	a.href = url;
	a.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
	document.body.appendChild(a);
	a.click();
	a.remove();
	URL.revokeObjectURL(url);
};

/**
 * Hands the browser a file the server built (an .xlsx, say). Revokes the object URL,
 * or the blob is held for the session.
 */
export const downloadBlob = (blob, filename) => {
	const url = URL.createObjectURL(blob);
	const a = document.createElement("a");
	a.href = url;
	a.download = filename;
	document.body.appendChild(a);
	a.click();
	a.remove();
	URL.revokeObjectURL(url);
};

/** "campaign-insights_2026-08-07_2026-09-05.csv" */
export const exportName = (base, range) =>
	[base, range?.from, range?.to].filter(Boolean).join("_");

/**
 * Walks a paginated endpoint so an export carries every row, not the page on screen.
 * `limit` is the API's own ceiling (500); `cap` stops a runaway from pulling a whole table.
 */
export const fetchAllPages = async (
	fetchPage,
	{ limit = 500, cap = 5000 } = {},
) => {
	const out = [];
	for (let page = 1; out.length < cap; page += 1) {
		const res = await fetchPage({ page, limit });
		const items = res?.items ?? [];
		out.push(...items);
		if (items.length < limit || out.length >= (res?.total ?? 0)) break;
	}
	return out;
};
