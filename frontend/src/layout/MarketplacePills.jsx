import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { useMarketplaces } from "../context/MarketplaceContext";
import { ORDERS_PATHS, SINGLE_MARKETPLACE_PATHS } from "../lib/constants";

/** The page itself or anything under it — `/ads/automation/` included. */
const onPath = (pathname, paths) =>
	paths.some((p) => pathname === p || pathname.startsWith(`${p}/`));

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
 * "All" is only offered when the client has more than one marketplace — with one, its
 * pill is the whole selection and is shown lit.
 *
 * Two kinds of page turn the row into a strict one-of choice with no "All", driving
 * the page's OWN selection and leaving the global one untouched:
 *   - the automation pages (`SINGLE_MARKETPLACE_PATHS`) — every write names one
 *     marketplace; those the campaign manager cannot drive are greyed out with the reason.
 *   - purchase orders (`ORDERS_PATHS`) — read one marketplace at a time; there is no
 *     blended PO view to offer.
 * See `MarketplaceContext` for why those choices are kept apart.
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
		? `${mp.name} — no data for this brand yet`
		: !mp.automations
			? `Automations aren't available on ${mp.name} yet`
			: null;

const unconnected = (mp) =>
	mp.connected ? null : `${mp.name} — no data for this brand yet`;

export const MarketplacePills = () => {
	const {
		marketplaces,
		connected,
		selected,
		allSelected,
		isLoading,
		ready,
		selectOnly,
		selectAll,
		automation,
		selectAutomation,
		enterAutomationPage,
		orders,
		selectOrders,
		enterOrdersPage,
	} = useMarketplaces();

	// On a single-marketplace page the row drives that page's own choice, leaving the
	// global selection untouched (see the docblock above).
	const { pathname } = useLocation();
	const scope = onPath(pathname, SINGLE_MARKETPLACE_PATHS)
		? "automation"
		: onPath(pathname, ORDERS_PATHS)
			? "orders"
			: null;
	const allowAll = !scope && connected.length > 1;
	useEffect(() => {
		if (!ready) return;
		if (scope === "automation") enterAutomationPage();
		if (scope === "orders") enterOrdersPage();
		// Entry only (and again once a switched-to client's list lands) — re-running on
		// every selection change would override the pill the reader just clicked.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [scope, ready]);

	// Holds the row's place while the list loads, so the navbar does not reflow on
	// every client switch.
	if (isLoading)
		return (
			<div
				aria-hidden="true"
				className="h-10 w-48 animate-pulse rounded-xl border border-border bg-muted"
			/>
		);

	// Per scope: why a pill cannot be picked, whether it is lit, and what a click does.
	const pill = {
		automation: {
			blocked: automationBlock,
			on: (slug) => slug === automation,
			pick: selectAutomation,
		},
		orders: {
			blocked: unconnected,
			on: (slug) => slug === orders,
			pick: selectOrders,
		},
		global: {
			blocked: unconnected,
			// "on" only when it is the selection. With All lit, every pill is included but
			// none of them is the answer to "what am I looking at".
			on: (slug) => !allSelected && selected.includes(slug),
			pick: selectOnly,
		},
	}[scope ?? "global"];

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
				const blocked = pill.blocked(mp);
				const on = pill.on(mp.slug);
				const bg = mp.color ?? FALLBACK_COLOR[mp.slug] ?? "#6B7280";
				return (
					<button
						key={mp.slug}
						type="button"
						disabled={Boolean(blocked)}
						onClick={() => pill.pick(mp.slug)}
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
