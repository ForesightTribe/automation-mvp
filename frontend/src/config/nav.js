import {
	LayoutGrid,
	BarChart3,
	Package,
	Warehouse,
	FlaskConical,
	Gauge,
	ClipboardCheck,
	ClipboardList,
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
	{ label: "Purchase Orders", path: "/purchase-orders", icon: ClipboardList },
	// Ads (/ads) and Campaign Manager (/campaign-manager) are hidden from the rail
	// while AdsBeta carries the ad work; both routes still resolve for saved links.
	{
		label: "AdsBeta",
		icon: FlaskConical,
		children: [
			{ label: "Insights", path: "/ads/insights" },
			{ label: "Ad Automation", path: "/ads/automation" },
			{ label: "One-time Ops", path: "/ads/one-time-ops" },
		],
	},
	{ label: "Competition", path: "/competition", icon: Gauge },
	// A clipboard, not a document: Scorecard rates performance while Reports produces
	// files, and both wearing FileText made two different destinations look like one.
	{ label: "Scorecard", path: "/scorecard", icon: ClipboardCheck },
	{ label: "Reports", path: "/reports", icon: FileText },
	// adminOnly: hidden from members in the Sidebar; the /settings route is also
	// guarded by RequireAdmin and the backend's require_admin dependency.
	{ label: "Settings", path: "/settings", icon: Settings, adminOnly: true },
];
