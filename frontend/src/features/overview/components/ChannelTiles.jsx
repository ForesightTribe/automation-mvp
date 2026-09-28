import {
	formatCurrency,
	formatNumber,
	formatDayLabel as dayLabel,
} from "../../../lib/format";
import {
	MarketplaceMark,
	markColor,
} from "../../../components/ui/MarketplaceMark";
import { useMarketplacesForDay } from "../hooks";
import { useMarketplaces } from "../../../context/MarketplaceContext";

/**
 * How the day went on each marketplace: the same measures as the total beside
 * it, one tile per channel instead of one set blended across all of them.
 *
 * Only channels this tenant actually scrapes appear. A marketplace with no feed
 * comes back `connected: false` and is left out rather than drawn as ₹0 — an
 * absent channel and a channel that sold nothing are different facts.
 *
 * A tile is tinted with the channel's own colour, the one its badge carries
 * everywhere else, so which channel a figure belongs to reads before the
 * label does.
 *
 * The change is measured against the same day last week, matching the total,
 * which is why the baseline day is fetched rather than read off `delta_pct` —
 * that field compares the window with the one immediately before it.
 */
/** One measure inside a channel tile: name left, figure right. */
const Detail = ({ label, value }) => (
	<span className="flex items-baseline justify-between gap-2 text-xs">
		<span className="text-content-muted">{label}</span>
		<span className="font-medium text-content tabular-nums">{value}</span>
	</span>
);

const money = (m) => (m?.value == null ? "—" : formatCurrency(m.value));

const ChannelTile = ({ row, baseline, was }) => {
	const color = markColor(row);
	const change = was ? ((row.revenue.value - was) / was) * 100 : null;
	const tone =
		change == null || Math.round(change) === 0
			? "text-content-muted"
			: change > 0
				? "text-success"
				: "text-danger";

	return (
		<div
			style={{ backgroundColor: `${color}12`, borderColor: `${color}3d` }}
			className="flex flex-col gap-1 rounded-xl border px-4 py-3.5"
		>
			<span className="flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-content-subtle uppercase">
				<MarketplaceMark marketplace={row} size={18} />
				{row.name}
			</span>

			<div className="flex min-w-0 flex-col gap-0.5">
				<span className="font-display text-2xl leading-tight font-bold text-content tabular-nums">
					{formatCurrency(row.revenue.value)}
				</span>
				<span
					title={
						was == null
							? "Nothing recorded the same day last week"
							: `${row.name}, ${dayLabel(baseline)}: ${formatCurrency(was)}`
					}
					className="flex items-baseline gap-1.5 text-xs tabular-nums"
				>
					{change == null ? (
						<span className="text-content-subtle">—</span>
					) : (
						<span className={`font-medium ${tone}`}>
							{change > 0 ? "▲" : "▼"}{" "}
							{Math.abs(change).toFixed(0)}%
						</span>
					)}
					<span className="text-content-subtle">
						{baseline ? `vs ${dayLabel(baseline)}` : ""}
					</span>
				</span>
			</div>

			<span
				style={{ borderColor: `${color}3d` }}
				className="mt-2 flex flex-col gap-1.5 border-t pt-2"
			>
				<Detail
					label="Organic revenue"
					value={money(row.organic_revenue)}
				/>
				<Detail label="Ad spend" value={money(row.ad_spend)} />
				<Detail label="Ad revenue" value={money(row.ad_sales)} />
				<Detail
					label="ROAS"
					value={
						row.roas?.value == null
							? "—"
							: `${row.roas.value.toFixed(2)}×`
					}
				/>
				<Detail
					label="Units sold"
					value={
						row.units_sold?.value == null
							? "—"
							: formatNumber(row.units_sold.value)
					}
				/>
			</span>
		</div>
	);
};

/**
 * The connected channels that sold on `day`, richest first.
 *
 * Narrowed by the marketplace picker, the same as every figure beside them —
 * the breakdown endpoint answers for the whole tenant, so a channel left out
 * of the selection has to be dropped here or the tiles would contradict the
 * total above them.
 */
export const useChannelRows = (day) => {
	const { data } = useMarketplacesForDay(day);
	const { selected } = useMarketplaces();
	return (data ?? [])
		.filter(
			(m) =>
				m.connected &&
				m.revenue?.value != null &&
				(!selected || selected.includes(m.slug)),
		)
		.sort((a, b) => b.revenue.value - a.revenue.value);
};

export const ChannelTiles = ({ day, baseline }) => {
	const rows = useChannelRows(day);
	const { data: before } = useMarketplacesForDay(baseline);

	// One channel is the whole business — a split of one only repeats the
	// total already beside it.
	if (rows.length < 2) return null;

	const prior = new Map(
		(before ?? []).map((m) => [m.slug, m.revenue?.value ?? null]),
	);

	return rows.map((m) => (
		<ChannelTile
			key={m.slug}
			row={{ ...m, day }}
			baseline={baseline}
			was={prior.get(m.slug)}
		/>
	));
};
