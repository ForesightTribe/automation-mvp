import { Card } from "./Card";
import { DeltaBadge } from "./DeltaBadge";
import { Sparkline } from "../charts/Sparkline";

/**
 * Per-tone card treatment. Every tone shares the same shadow pair (0/2/8 black
 * 10% at rest, 0/4/16 black 15% on hover) and the same stroke ramp — 25% opacity
 * resting, 100% on hover — only the hue changes. The `[&]:` prefix on the resting
 * border is a specificity bump so it beats Card's own `border-border`; the hover
 * rule doesn't need one because `:hover` carries its own.
 */
const TONES = {
	neutral: {
		card: "[&]:border-[#a8a49e]/25 hover:border-[#a8a49e]",
		label: "text-content-subtle",
		value: "text-content",
	},
	danger: {
		card: "[&]:border-[#be123c]/25 [&]:bg-[#fff1f2] hover:border-[#be123c]",
		label: "text-[#be123c]/75",
		value: "text-[#be123c]",
	},
	warning: {
		card: "[&]:border-[#b45309]/25 [&]:bg-[#fffbeb] hover:border-[#b45309]",
		label: "text-[#b45309]/75",
		value: "text-[#b45309]",
	},
	/* One tile per strip may be `featured` — a filled card that pulls the eye to
	   the headline metric. Use it once; two featured tiles cancel each other. */
	featured: {
		card: "[&]:border-[#6b4a6b] [&]:bg-[#6b4a6b]",
		label: "text-white/70",
		value: "text-white",
	},
};

const SHADOW =
	"shadow-[0_2px_8px_rgba(0,0,0,0.10)] hover:shadow-[0_4px_16px_rgba(0,0,0,0.15)]";

/**
 * One headline KPI: label, a preformatted value, and its growth badge. The
 * caller formats `value` (currency, percent, etc.) since formatting is
 * metric-specific; this tile only handles layout. `delta` is a fraction or null;
 * `goodWhenDown` flips the badge colors for lower-is-better metrics like rank.
 * Pass `series` (array of daily values) to render a sparkline under the number.
 *
 * `tone` picks the card treatment — `neutral` by default, `danger` for
 * out-of-stock counts, `warning` for low-cover. See TONES above.
 *
 * `hint` explains what the number counts — the counts behind a percentage
 * ("24,410 of 25,474 listed"), a caveat, a denominator. It sits behind a round ⓘ
 * beside the label and appears on hover, so the tile stays a number.
 */
export const MetricTile = ({
	label,
	value,
	hint,
	delta,
	goodWhenDown = false,
	series,
	sparkColor,
	seriesType = "line",
	seriesLabel,
	tone = "neutral",
}) => {
	const t = TONES[tone] ?? TONES.neutral;

	return (
		<Card
			className={`${t.card} ${SHADOW} relative min-h-[104px] transition-[transform,box-shadow,border-color] duration-200 ease-out`}
		>
			<div className="flex items-start justify-between gap-2">
				<p
					className={`text-xs font-medium tracking-wide uppercase ${t.label}`}
				>
					{label}
				</p>
				{hint && (
					// No `relative` on this wrapper on purpose: the panel's
					// containing block is then the CARD, so it can hang below the
					// tile instead of over the number.
					<span className="group/info shrink-0">
						<button
							type="button"
							tabIndex={0}
							aria-label={`What does ${label} mean?`}
							className="grid h-4 w-4 cursor-help place-items-center rounded-full border border-current text-[10px] leading-none opacity-50 transition-opacity hover:opacity-100 focus-visible:opacity-100"
						>
							i
						</button>
						<span
							role="tooltip"
							className="pointer-events-none absolute top-full right-0 left-0 z-50 mt-2 hidden rounded-lg border border-border bg-card p-3 text-xs leading-relaxed font-normal text-content-muted normal-case shadow-[0_4px_16px_rgba(0,0,0,0.15)] group-hover/info:block group-focus-within/info:block"
						>
							{hint}
						</span>
					</span>
				)}
			</div>
			<div className="mt-2 flex items-baseline justify-between gap-2">
				<p
					className={`font-display text-xl font-bold xl:text-2xl ${t.value}`}
				>
					{value}
				</p>
				<DeltaBadge delta={delta} goodWhenDown={goodWhenDown} />
			</div>
			{series && (
				<div className="mt-3">
					<Sparkline
						values={series}
						color={sparkColor}
						type={seriesType}
					/>
					{seriesLabel && (
						<p
							className={`mt-1 text-center text-[10px] ${t.label}`}
						>
							{seriesLabel}
						</p>
					)}
				</div>
			)}
		</Card>
	);
};
