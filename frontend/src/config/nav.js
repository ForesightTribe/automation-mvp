/**
 * Single source of truth for the primary navigation. The Sidebar renders from
 * this list and the router builds its routes against the same paths, so adding
 * a page = adding one entry here (plus its feature folder).
 *
 * `icon` is a short glyph placeholder — swap for an icon component later.
 */
export const NAV_ITEMS = [
	{ label: "Overview", path: "/overview", icon: "▣" },
	{ label: "Sales & Analytics", path: "/analytics", icon: "▤" },
	{ label: "Products", path: "/products", icon: "▦" },
	{ label: "Inventory", path: "/inventory", icon: "▥" },
	{ label: "Campaign Manager", path: "/ads", icon: "◈" },
	{ label: "Competition", path: "/competition", icon: "◎" },
	{ label: "Scorecard", path: "/scorecard", icon: "◍" },
	// adminOnly: hidden from members in the Sidebar; the /settings route is also
	// guarded by RequireAdmin and the backend's require_admin dependency.
	{ label: "Settings", path: "/settings", icon: "⚙", adminOnly: true },
];
