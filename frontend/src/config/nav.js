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
	// Store, — Market View's icon, while that page is hidden
} from "lucide-react";

/**
 * Single source of truth for the primary navigation. The Sidebar renders from
 * this list and the router builds its routes against the same paths, so adding
 * a page = adding one entry here (plus its feature folder).
 *
 * `icon` is a lucide component — the rail is icon-only, so `label` is what the
 * tooltip and aria-label read. `badge` is an optional pill (e.g. "New"), shown
 * only when the rail is expanded.
 */
export const NAV_ITEMS = [
	{ label: "Overview", path: "/overview", icon: LayoutGrid },
	{ label: "Sales & Analytics", path: "/analytics", icon: BarChart3 },
	{ label: "Products", path: "/products", icon: Package },
	{ label: "Inventory", path: "/inventory", icon: Warehouse },
	{
		label: "Purchase Orders",
		path: "/purchase-orders",
		icon: ClipboardList,
		badge: "New",
	},

	{
		label: "Ads",
		icon: FlaskConical,
		children: [
			{ label: "Insights", path: "/ads/insights" },
			{ label: "Ad Automation", path: "/ads/automation" },
			{ label: "One-time Ops", path: "/ads/one-time-ops" },
		],
	},
	{ label: "Competition", path: "/competition", icon: Gauge },
	// Store-grain companion to Competition: the same public scrape, read as
	// "which shops and which search terms" rather than as national roll-ups.
	// Experimental — hidden for now (route commented out in app/router.jsx too).
	// { label: "Market View", path: "/market-view", icon: Store },
	// A clipboard, not a document: Scorecard rates performance while Reports produces
	// files, and both wearing FileText made two different destinations look like one.
	{ label: "Scorecard", path: "/scorecard", icon: ClipboardCheck },
	{ label: "Reports", path: "/reports", icon: FileText },
	// Open to everyone — the account block lives here; admin cards gate inside.
	{ label: "Settings", path: "/settings", icon: Settings },
];
