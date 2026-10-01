import { MarketplaceMark } from "../../../components/ui/MarketplaceMark";
import { formatCurrency } from "../../../lib/format";
import { previousRangeLabel } from "../../../lib/dates";
import { useDateRange } from "../../../context/DateRangeContext";

/**
 * What each channel was worth over the window, and what it was made of.
 *
 * Stands in for the chart's legend, and does more than one: pointing at a row
 * brings that channel's line forward and pushes the others back, so a channel
 * can be followed without turning the rest off.
 *
 * One measure per table: the split behind it belongs to the whole account.
 *
 * `share` is off for a measure that is already a rate — channels' shares of an
 * average share of voice do not add to anything.
 *
 * `focus` is optional — without a chart to bring a line forward in, the rows
 * are a table and nothing reacts to pointing at them.
 *
 * Everything is for the picked window and measured against the window of equal
 * length before it.
 */
const money = (m) => (m?.value == null ? "—" : formatCurrency(m.value));
const percent = (m) => (m?.value == null ? "—" : `${m.value.toFixed(1)}%`);
export const FORMATS = { currency: money, percent };

const Row = ({
	row,
	metric,
	format,
	share,
	extras,
	wide,
	focused,
	onFocus,
}) => {
	const figure = row[metric];
	const delta = figure?.delta_pct;
	const { range } = useDateRange();
	const tone =
		delta == null || Math.round(delta * 100) === 0
			? "text-content-muted"
			: delta > 0
				? "text-success"
				: "text-danger";

	return (
		<li
			onMouseEnter={() => onFocus?.(row.name)}
			onMouseLeave={() => onFocus?.(null)}
			onFocus={() => onFocus?.(row.name)}
			onBlur={() => onFocus?.(null)}
			tabIndex={onFocus ? 0 : undefined}
			className={`flex items-baseline gap-4 border-b border-border py-1.5 transition-colors last:border-0 ${
				focused ? "bg-muted" : ""
			}`}
		>
			{/* The change rides with the channel's name, which is what it
			    qualifies. */}
			<span
				className={`flex min-w-0 items-center gap-1.5 text-sm text-content ${
					wide ? "flex-1" : "w-36"
				}`}
			>
				<MarketplaceMark marketplace={row} size={16} />
				<span className="truncate">{row.name}</span>
				{/* Nothing to compare against is left blank, not dashed: a
				    dash reads as a measured figure that came back empty. */}
				{delta != null && (
					<span
						title={`${format({ value: figure.prev })} over ${previousRangeLabel(range)}`}
						className={`shrink-0 cursor-help text-[11px] font-medium tabular-nums ${tone}`}
					>
						{delta > 0 ? "▲" : "▼"}
						{Math.abs(delta * 100).toFixed(0)}%
					</span>
				)}
			</span>
			{/* The share sits under the figure, small: it qualifies the
			    number rather than standing beside it as a second one. */}
			<span className="flex w-[100px] flex-col items-end">
				<span className="text-sm font-semibold text-content tabular-nums">
					{format(figure)}
				</span>
				{share != null && (
					<span className="text-[11px] leading-tight text-content-subtle tabular-nums">
						{share.toFixed(0)}% of total
					</span>
				)}
			</span>
			{extras.map((e) => (
				<span
					key={e.label}
					className={`${e.width} text-right text-sm text-content-muted tabular-nums`}
				>
					{e.value(row)}
				</span>
			))}
		</li>
	);
};

export const ChannelSplit = ({
	rows,
	metric = "revenue",
	label = "Revenue",
	format = "currency",
	showShare = true,
	extras = [],
	// Full width, with the name column taking the slack — for a table that is
	// the section rather than a legend beside it.
	wide = false,
	focus,
	onFocus,
}) => {
	if (rows.length < 2) return null;

	const total = showShare
		? rows.reduce((sum, m) => sum + (m[metric]?.value ?? 0), 0)
		: 0;

	return (
		<div className={`flex flex-col gap-1 ${wide ? "w-full" : "w-fit"}`}>
			<div className="flex items-baseline gap-4 border-b border-border pb-1 text-[11px] tracking-wide text-content-subtle uppercase">
				<span className={wide ? "flex-1" : "w-36"}>Channel</span>
				<span className="w-[100px] text-right">{label}</span>
				{extras.map((e) => (
					<span key={e.label} className={`${e.width} text-right`}>
						{e.label}
					</span>
				))}
			</div>
			<ul className="flex flex-col">
				{rows.map((m) => (
					<Row
						key={m.slug}
						row={m}
						metric={metric}
						format={FORMATS[format] ?? money}
						share={
							total
								? ((m[metric]?.value ?? 0) / total) * 100
								: null
						}
						extras={extras}
						wide={wide}
						focused={focus === m.name}
						onFocus={onFocus}
					/>
				))}
			</ul>
		</div>
	);
};
