import { formatCurrency } from "../../../../lib/format";
import { MarketplaceTag } from "../insightsTable";
import { DIM_LABEL, NOUN } from "./explorerModel";
import { RoasPill } from "./explorerColumns";

/** The three RoAS bands. Soft status hues: the band's name and the RoAS number always sit
 * beside the colour, so it is never the only signal. */
const BANDS = [
	{
		label: "Losing money",
		note: "RoAS below 1×",
		color: "#f87171",
		test: (v) => v < 1,
	},
	{
		label: "Below target",
		note: "RoAS 1× to 3×",
		color: "#fbbf24",
		test: (v) => v >= 1 && v < 3,
	},
	{
		label: "On target",
		note: "RoAS 3× or more",
		color: "#4ade80",
		test: (v) => v >= 3,
	},
];

/**
 * "Is the money earning?" in two simple parts: how the spend splits across the three RoAS
 * bands, then the biggest spenders as bars coloured by their band. Replaces a spend-vs-RoAS
 * scatter, which was hard to read. Every bar opens the row's detail.
 */
export const EarnChart = ({ rows, dim, multi, onOpen }) => {
	const pts = rows.filter((r) => r.spend > 0 && r.roas != null);
	if (!pts.length)
		return (
			<p className="py-6 text-sm text-content-muted">
				Nothing to show for this selection.
			</p>
		);
	const total = pts.reduce((s, r) => s + r.spend, 0);
	const bands = BANDS.map((b) => {
		const inBand = pts.filter((r) => b.test(r.roas));
		return {
			...b,
			spend: inBand.reduce((s, r) => s + r.spend, 0),
			n: inBand.length,
		};
	});
	const top = [...pts].sort((a, b) => b.spend - a.spend).slice(0, 12);
	const max = top[0].spend;

	return (
		<div className="flex flex-col gap-5">
			<div>
				<p className="text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
					Where the spend earned · {pts.length} {NOUN[dim]}
				</p>
				<div className="mt-2 flex h-3 gap-0.5 overflow-hidden rounded-full">
					{bands
						.filter((b) => b.spend)
						.map((b) => (
							<span
								key={b.label}
								title={`${b.label}: ${formatCurrency(b.spend)} · ${((b.spend / total) * 100).toFixed(1)}% of spend`}
								className="block min-w-0.5"
								style={{
									flex: `${b.spend} 1 0`,
									background: b.color,
								}}
							/>
						))}
				</div>
				<div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-3">
					{bands.map((b) => (
						<div
							key={b.label}
							className="rounded-lg border border-border px-3 py-2.5"
						>
							<p className="flex items-center gap-1.5 text-xs font-semibold text-content">
								<span
									className="h-2.5 w-2.5 rounded-sm"
									style={{ background: b.color }}
								/>
								{b.label}
							</p>
							<p className="mt-1 font-display text-lg font-semibold text-content">
								{formatCurrency(b.spend)}{" "}
								<span className="text-sm font-medium text-content-muted">
									{total
										? ((b.spend / total) * 100).toFixed(0)
										: 0}
									%
								</span>
							</p>
							<p className="text-xs text-content-muted">
								{b.n} {NOUN[dim]} · {b.note}
							</p>
						</div>
					))}
				</div>
			</div>
			<div>
				<p className="mb-1 text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
					Biggest spenders
				</p>
				<div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,2fr)_6rem_4.5rem] gap-3 border-b border-border pb-1.5 text-[11px] font-semibold tracking-[0.08em] text-content-subtle uppercase">
					<span>{DIM_LABEL[dim]}</span>
					<span>Spend</span>
					<span className="text-right">Spend</span>
					<span className="text-right">RoAS</span>
				</div>
				{top.map((r) => {
					const band = BANDS.find((b) => b.test(r.roas));
					return (
						<button
							key={r.key}
							type="button"
							onClick={() => onOpen(r)}
							className="group grid w-full grid-cols-[minmax(0,1.3fr)_minmax(0,2fr)_6rem_4.5rem] items-center gap-3 border-b border-muted py-2 text-left text-sm"
						>
							<span className="flex min-w-0 items-center gap-1.5">
								{multi &&
									r.platforms.map((m) => (
										<MarketplaceTag
											key={m}
											slug={m}
											compact
										/>
									))}
								<span className="truncate text-content group-hover:text-brand group-hover:underline">
									{r.name}
								</span>
							</span>
							<span className="h-2 rounded-full bg-muted">
								<span
									className="block h-full rounded-full"
									style={{
										width: `${((r.spend / max) * 100).toFixed(1)}%`,
										background: band.color,
									}}
								/>
							</span>
							<span className="text-right tabular-nums">
								{formatCurrency(r.spend)}
							</span>
							<span className="text-right">
								<RoasPill value={r.roas} />
							</span>
						</button>
					);
				})}
			</div>
		</div>
	);
};
