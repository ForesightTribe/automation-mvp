/**
 * A marketplace's badge: its own colour, carrying the first letter of its name.
 *
 * The one place the mark is defined, so the navbar pills and anything else
 * showing a channel cannot drift apart on colour or shape.
 *
 * ⚠️ The ink is chosen from the fill's perceived lightness, not fixed. Zepto's
 * purple and Instamart's orange sit at opposite ends of the range, and either
 * black or white alone is unreadable on one of them.
 */
const FALLBACK_COLOR = {
	blinkit: "#F8CB46",
	zepto: "#5B1D8C",
	instamart: "#F26B21",
};

/** Perceived lightness of a hex colour, 0-255, on the usual luma weights. */
const lightness = (hex) => {
	const h = hex.replace("#", "");
	const n = parseInt(
		h.length === 3
			? h
					.split("")
					.map((c) => c + c)
					.join("")
			: h,
		16,
	);
	return (
		((n >> 16) & 255) * 0.299 + ((n >> 8) & 255) * 0.587 + (n & 255) * 0.114
	);
};

export const markColor = (mp) =>
	mp?.color ?? FALLBACK_COLOR[mp?.slug] ?? "#6B7280";

export const MarketplaceMark = ({ marketplace, size = 20 }) => {
	const bg = markColor(marketplace);
	return (
		<span
			aria-hidden="true"
			style={{
				backgroundColor: bg,
				color: lightness(bg) > 150 ? "#1f2937" : "#ffffff",
				width: size,
				height: size,
				fontSize: Math.round(size * 0.55),
			}}
			className="flex shrink-0 items-center justify-center rounded-md font-bold"
		>
			{(marketplace?.name ?? "?").charAt(0).toUpperCase()}
		</span>
	);
};
