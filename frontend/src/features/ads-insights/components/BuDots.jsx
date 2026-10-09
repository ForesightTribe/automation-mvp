import { useRef, useState } from "react";
import { buBand } from "../buBands";
import { formatCurrency } from "../../../lib/format";

/**
 * Seven days of budget utilisation as a strip of dots, on the campaign's own row.
 *
 
 *
 * A legend states every band, the exact figures are one
 * hover away, and a day the campaign did not run is grey and named as such rather than drawn
 * as 0%, because "did not run" and "ran and underspent" are different facts and only one of
 * them is a problem.
 */
const Swatch = ({ tone }) => (
	<span className={`mt-1 block h-3 w-1 shrink-0 rounded-full ${tone}`} />
);

const Dot = ({ cell, campaignName, onShow, onHide, onClick }) => {
	const ref = useRef(null);
	const band = buBand(cell.bu);
	return (
		<button
			ref={ref}
			type="button"
			aria-label={
				cell.bu == null
					? `${cell.date}: did not run`
					: `${cell.date}: ${cell.bu.toFixed(1)}% of budget used`
			}
			onMouseEnter={() => onShow(cell, campaignName, ref.current)}
			onMouseLeave={onHide}
			onFocus={() => onShow(cell, campaignName, ref.current)}
			onBlur={onHide}
			onClick={onClick}
			className="flex h-4 w-4 items-center justify-center rounded-full transition-shadow hover:shadow-[0_0_0_3px_var(--color-muted)] focus-visible:shadow-[0_0_0_3px_var(--color-muted)] focus-visible:outline-none"
		>
			<span
				className={`block h-2.5 w-2.5 rounded-full ${band ? band.dot : "bg-border"}`}
			/>
		</button>
	);
};

/**
 * The hover panel, held by the TABLE rather than by each dot.
 *
 * One panel for the whole table, positioned fixed: a table renders hundreds of dots, and a
 * tooltip per dot would be hundreds of hidden elements, most inside an `overflow-auto` that
 * would clip them anyway.
 */
export const BuTooltip = ({ tip }) => {
	if (!tip) return null;
	const band = buBand(tip.cell.bu);
	const row = (tone, label, value) => (
		<div className="flex items-start gap-2">
			<Swatch tone={tone} />
			<dt className="flex-1 text-content-muted">{label}</dt>
			<dd className="font-medium text-content tabular-nums">{value}</dd>
		</div>
	);
	return (
		<div
			role="tooltip"
			style={{
				left: tip.left,
				top: tip.top,
				transform:
					tip.place === "above" ? "translateY(-100%)" : undefined,
			}}
			className="pointer-events-none fixed z-[80] w-64 rounded-xl border border-border bg-card p-4 shadow-xl"
		>
			<p className="font-display text-sm font-semibold text-content">
				{new Date(`${tip.cell.date}T00:00:00`).toLocaleDateString(
					"en-IN",
					{
						day: "numeric",
						month: "short",
						year: "numeric",
					},
				)}
			</p>
			{tip.name && (
				<p className="truncate text-[11px] text-content-subtle">
					{tip.name}
				</p>
			)}
			{tip.cell.bu == null ? (
				<p className="mt-3 border-t border-border pt-3 text-sm text-content-muted">
					This campaign did not run on this day, so there was no
					budget to use.
				</p>
			) : (
				<>
					<dl className="mt-3 flex flex-col gap-2.5 border-t border-border pt-3 text-sm">
						{row(band.dot, "BU %", `${tip.cell.bu.toFixed(2)}%`)}
						{row(
							band.dot,
							"Ad spend",
							formatCurrency(tip.cell.spend),
						)}
						{row(
							band.dot,
							"Daily budget",
							formatCurrency(tip.cell.allowed),
						)}
					</dl>
					{/* The DOT is the control; this panel is pointer-transparent by design, so it
					    must not read as something to click. */}
					<p className="mt-2.5 text-[11px] text-content-subtle">
						Click this dot for the full trend.
					</p>
				</>
			)}
		</div>
	);
};

/** Positions the shared panel against whichever dot the pointer is on. */
export const useBuTooltip = () => {
	const [tip, setTip] = useState(null);
	const show = (cell, name, el) => {
		const r = el?.getBoundingClientRect();
		if (!r) return;
		const below = window.innerHeight - r.bottom;
		setTip({
			cell,
			name,
			left: Math.min(Math.max(8, r.left - 24), window.innerWidth - 276),
			top: below > 250 ? r.bottom + 10 : r.top - 10,
			place: below > 250 ? "below" : "above",
		});
	};
	return { tip, show, hide: () => setTip(null) };
};

export const BuDots = ({ days, campaignName, onShow, onHide, onClick }) => (
	<div className="flex items-center justify-end gap-0.5">
		{days.map((cell) => (
			<Dot
				key={cell.date}
				cell={cell}
				campaignName={campaignName}
				onShow={onShow}
				onHide={onHide}
				onClick={onClick}
			/>
		))}
	</div>
);
