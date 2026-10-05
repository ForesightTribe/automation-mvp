import { markColor } from "../../../components/ui/MarketplaceMark";

/**
 * The day's revenue as one bar, divided by the channel that earned it.
 *
 * Only for the all-channels selection: with a single marketplace in view the
 * bar is one full segment, which says nothing the total above it does not.
 *
 * Segments carry their colour from the tiles beside them, so the bar needs no
 * legend of its own. A share is written inside its segment only where it fits;
 * below that the sliver would hold a label wider than itself, so the figure
 * stays on hover instead.
 */
const LABEL_FITS = 12;

export const ChannelShareBar = ({ rows: all }) => {
	// Only channels that have reported: a segment of zero width for one whose
	// feed has not landed reads as a channel that sold nothing.
	const rows = all.filter((m) => m.revenue?.value != null);
	const total = rows.reduce((sum, m) => sum + m.revenue.value, 0);
	if (rows.length < 2 || !total) return null;

	return (
		<span className="flex h-6 w-full gap-0.5 overflow-hidden rounded-md">
			{rows.map((m) => {
				const share = (m.revenue.value / total) * 100;
				return (
					<span
						key={m.slug}
						title={`${m.name}: ${share.toFixed(0)}%`}
						style={{
							backgroundColor: markColor(m),
							width: `${share}%`,
						}}
						className="flex items-center justify-center text-[10px] font-semibold text-white/95 first:rounded-l-md last:rounded-r-md"
					>
						{share >= LABEL_FITS ? `${share.toFixed(0)}%` : ""}
					</span>
				);
			})}
		</span>
	);
};
