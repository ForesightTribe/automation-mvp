/**
 * How a budget-utilisation figure is read, in one place.
 *
 * Green is "used what was set aside", red is "left money on the table". The bands exist so
 * the table, the drawer and the chart cannot disagree about where the line falls.
 *
 * ⚠️ Colour is never the only signal anywhere it is used: the number itself is always
 * printed beside it, so the hue speeds up a scan rather than carrying the meaning. Status
 * hues are reserved for exactly this kind of judgement, which is why they are spent here and
 * not on chart series identity elsewhere.
 */
export const BU_BANDS = [
	{
		min: 85,
		label: "85% and over",
		text: "text-success",
		dot: "bg-success",
		hex: "#16a34a",
	},
	{
		min: 60,
		label: "60 to 85%",
		text: "text-warning",
		dot: "bg-warning",
		hex: "#d97706",
	},
	{
		min: 0,
		label: "Under 60%",
		text: "text-danger",
		dot: "bg-danger",
		hex: "#dc2626",
	},
];

export const buBand = (bu) =>
	bu == null ? null : BU_BANDS.find((b) => bu >= b.min);
