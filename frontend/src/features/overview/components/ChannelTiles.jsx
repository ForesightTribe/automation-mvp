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
 * The change is measured against the same day last week, matching the total.
 * That baseline is asked for in the same request as the day itself, so the
 * comparison costs no second fetch of an endpoint that aggregates per
 * marketplace.
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
	// A channel whose feed has not landed for this day. Reported as that rather
	// than as ₹0, which claims it sold nothing.
	const reported = row.revenue?.value != null;
	const change =
		reported && was ? ((row.revenue.value - was) / was) * 100 : null;
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
					{reported ? formatCurrency(row.revenue.value) : "—"}
				</span>
				{reported ? (
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
				) : (
					<span className="text-xs text-content-muted">
						Not reported yet
					</span>
				)}
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
export const useChannelRows = (day, baseline) => {
	const { data, isPending } = useMarketplacesForDay(day, baseline);
	const { selected, ready } = useMarketplaces();
	// `settled` is false until the picker resolves AND the day's rows arrive.
	// Before that `selected` is empty and the rows are missing, which together
	// read as a tenant with one channel — so callers hold rather than draw the
	// single-channel layout and swap it a moment later.
	const settled = ready && !isPending;
	if (!settled) return { rows: [], settled };
	const rows = (data ?? [])
		.filter(
			(m) =>
				m.connected &&
				m.revenue !== undefined &&
				selected.includes(m.slug),
		)
		.sort((a, b) => (b.revenue?.value ?? -1) - (a.revenue?.value ?? -1));
	return { rows, settled };
};

export const ChannelTiles = ({ day, baseline }) => {
	const { rows } = useChannelRows(day, baseline);

	// One channel is the whole business — a split of one only repeats the
	// total already beside it.
	if (rows.length < 2) return null;

	return rows.map((m) => (
		<ChannelTile
			key={m.slug}
			row={{ ...m, day }}
			baseline={baseline}
			was={m.revenue?.prev ?? null}
		/>
	));
};
