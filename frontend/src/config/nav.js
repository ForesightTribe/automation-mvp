import {
	LayoutGrid,
	BarChart3,
	Package,
	Warehouse,
	Megaphone,
	FlaskConical,
	Target,
	Gauge,
	FileText,
	Settings,
} from "lucide-react";

/**
 * Single source of truth for the primary navigation. The Sidebar renders from
 * this list and the router builds its routes against the same paths, so adding
 * a page = adding one entry here (plus its feature folder).
 *
 * `icon` is a lucide component — the rail is icon-only, so `label` is what the
 * tooltip and aria-label read.
 */
export const NAV_ITEMS = [
	{ label: "Overview", path: "/overview", icon: LayoutGrid },
	{ label: "Sales & Analytics", path: "/analytics", icon: BarChart3 },
	{ label: "Products", path: "/products", icon: Package },
	{ label: "Inventory", path: "/inventory", icon: Warehouse },
	// A plain top-level entry, deliberately outside the AdsBeta group below.
	{ label: "Ads", path: "/ads", icon: Megaphone },

	// {
	// 	label: "AdsBeta",
	// 	icon: FlaskConical,
	// 	children: [
	// 		{ label: "Insights", path: "/ads/insights" },
	// 		{ label: "Ad Automation", path: "/ads/automation" },
	// 	],
	// },
	{ label: "Campaign Manager", path: "/campaign-manager", icon: Target },
	{ label: "Competition", path: "/competition", icon: Gauge },
	{ label: "Scorecard", path: "/scorecard", icon: FileText },
	// HIDDEN 2026-09-10 — work in progress, kept out of the nav so the client does not
	// find it. The ROUTE is untouched: /reports still resolves for anyone with the URL
	// or a bookmark. Uncomment to restore; nothing else needs changing.
	// { label: "Reports", path: "/reports", icon: FileText },
	// adminOnly: hidden from members in the Sidebar; the /settings route is also
	// guarded by RequireAdmin and the backend's require_admin dependency.
	//
	// HIDDEN 2026-09-10 — as above. Note this one is ALREADY invisible to clients via
	// adminOnly; commenting it out hides it from admins too. The /settings route stays
	// guarded by RequireAdmin either way.
	// { label: "Settings", path: "/settings", icon: Settings, adminOnly: true },
];
