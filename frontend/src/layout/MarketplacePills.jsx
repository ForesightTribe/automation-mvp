import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { useMarketplaces } from "../context/MarketplaceContext";
import { SINGLE_MARKETPLACE_PATHS } from "../lib/constants";

// ⚠️ A second, unrelated reason to drop "All": these pages cannot ANSWER it.
// Purchase orders are read one marketplace at a time — the service returns
// BLINKIT's when none is named — so an "All" pill offers a blended view that
// does not exist. Distinct from SINGLE_MARKETPLACE_PATHS above, which is about
// writes the campaign manager can only address to one marketplace.
const NO_ALL = ["/purchase-orders"];

/**
 * The marketplace filter, as a row of pills in the navbar.
 *
 * A pill row rather than a dropdown because the choice is small, permanent and worth
 * seeing without opening anything: which marketplace the numbers on screen cover is
 * the second most load-bearing fact on any page, after which client they belong to.
 *
 * ⚠️ Selecting a pill selects ONLY that marketplace, and "All" is how you get back to
 * everything. The underlying state is still a list of slugs, so a caller that wants
 * several at once can still have them; this control just never produces that itself.
 *
 * On the automation pages (`SINGLE_MARKETPLACE_PATHS`) the same row is a strict
 * one-of choice with no "All", and marketplaces the campaign manager cannot drive are
 * greyed out with the reason. See `MarketplaceContext` for why that choice is kept apart.
 */

/**
 * Brand colours for the chip on each pill.
 *
 * `/reference/marketplaces` carries a `color` for some marketplaces and null for the
 * rest, so this fills the gaps. The foreground is computed rather than stored, because
 * the two brands sit at opposite ends of the lightness range and a fixed ink colour is
 * unreadable on one of them.
 */
const FALLBACK_COLOR = {
	zepto: "#5B1D8C",
	instamart: "#F26B21",
};

/** Perceived lightness of a hex colour, 0–255. The coefficients are the usual
 *  luma weights: the eye reads green as far brighter than blue at equal value. */
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

// Selected is a SOLID DARK pill, and deliberately not a brand-red one: red is the
// product's accent and the bar already spends it on the active nav item. Neutral does
// not mean faint, though — a light grey fill reads as "hovered" next to controls that
// are already grey on white, so the selected state inverts instead. Each pill keeps its
// platform's own colour on the chip, which is the only colour in the row that carries
// meaning.
const PILL =
	"flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-sm transition-colors";
const PILL_ON = "border-inverse bg-inverse font-semibold text-on-inverse";
const PILL_OFF =
	"border-transparent font-medium text-content-muted hover:bg-muted hover:text-content";

/**
 * Why a pill cannot be picked on an automation page, or null when it can.
 * Unconnected first: a marketplace with no data at all is "not connected", whatever else.
 */
const automationBlock = (mp) =>
	!mp.connected
		? `${mp.name} — not connected yet`
		: !mp.automations
			? `Automations aren't available on ${mp.name} yet`
			: null;

export const MarketplacePills = () => {
	const {
		marketplaces,
		selected,
		allSelected,
		isLoading,
		selectOnly,
		selectAll,
		automation,
		selectAutomation,
		enterAutomationPage,
	} = useMarketplaces();

	// The automation pages act on ONE marketplace: every campaign-manager address names
	// one, so there is no "All" to send a write to. There the row drops "All" and drives
	// the pages' own choice, leaving the global selection untouched.
	const { pathname } = useLocation();
	const single = SINGLE_MARKETPLACE_PATHS.includes(pathname);
	const allowAll =
		!single && !NO_ALL.some((p) => pathname.startsWith(p));
	useEffect(() => {
		if (single && !isLoading) enterAutomationPage();
		// Entry only — re-running on every selection change would override the pill the
		// reader just clicked on this page.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [single, isLoading]);

	if (isLoading) return null;

	return (
		<div
			role="group"
			aria-label="Marketplace"
			className="flex items-center gap-1 rounded-xl border border-border bg-card p-1"
		>
			{allowAll && (
				<button
					type="button"
					onClick={selectAll}
					aria-pressed={allSelected}
					className={`${PILL} ${allSelected ? PILL_ON : PILL_OFF}`}
				>
					All
				</button>
			)}

			{marketplaces.map((mp) => {
				// "on" only when it is the sole selection. With All showing, every pill is
				// included but none of them is the answer to "what am I looking at".
				const blocked = single
					? automationBlock(mp)
					: mp.connected
						? null
						: `${mp.name} — not connected yet`;
				const on = single
					? mp.slug === automation
					: !allSelected && selected.includes(mp.slug);
				const bg = mp.color ?? FALLBACK_COLOR[mp.slug] ?? "#6B7280";
				return (
					<button
						key={mp.slug}
						type="button"
						disabled={Boolean(blocked)}
						onClick={() =>
							single
								? selectAutomation(mp.slug)
								: selectOnly(mp.slug)
						}
						aria-pressed={on}
						title={blocked ?? mp.name}
						className={`${PILL} ${on ? PILL_ON : PILL_OFF} disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent`}
					>
						<span
							aria-hidden="true"
							style={{
								backgroundColor: bg,
								color:
									lightness(bg) > 150 ? "#1f2937" : "#ffffff",
							}}
							className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[11px] font-bold"
						>
							{mp.name.charAt(0).toUpperCase()}
						</span>
						{mp.name}
					</button>
				);
			})}
		</div>
	);
};
