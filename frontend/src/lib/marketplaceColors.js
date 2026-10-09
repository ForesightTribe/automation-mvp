/**
 * Each marketplace's CHART colour — the fill a marketplace wears in charts and bars.
 *
 * Not the brand colour (`MarketplaceMark`'s chip): Blinkit's yellow is 1.5:1 on white and
 * Zepto's purple too dark to chart. These are chart-safe shades of the same hues, run through
 * the dataviz palette validator on the white card surface (2026-10-08, all pairs: lightness
 * band, chroma, CVD ΔE ≥ 8, normal-vision ΔE ≥ 15). Blinkit's sits under 3:1, so it always
 * comes with a label or a table — never colour alone.
 *
 * Colour follows the marketplace everywhere, never its rank. A marketplace without an entry
 * gets the neutral "Other" grey rather than a generated hue.
 */
const CHART = {
	zepto: "#7C3AED",
	blinkit: "#D4A000",
	instamart: "#EA580C",
};

export const OTHER_COLOR = "#B4B0AB";

export const chartColor = (slug) => CHART[slug] ?? OTHER_COLOR;

/** Ink that reads on top of a chart colour (Blinkit's gold and the grey need dark ink). */
export const chartInk = (slug) =>
	slug === "blinkit" || !CHART[slug] ? "#1f2937" : "#ffffff";
