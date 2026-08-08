import {
	LayoutGrid,
	BarChart3,
	Package,
	Warehouse,
	Megaphone,
	Target,
	Trophy,
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
	{ label: "Ads", path: "/ads", icon: Megaphone },
	{ label: "Campaign Manager", path: "/campaign-manager", icon: Target },
	{ label: "Campaign Manager v2", path: "/campaign-manager-v2", icon: Trophy },
	{ label: "Competition", path: "/competition", icon: Gauge },
	{ label: "Scorecard", path: "/scorecard", icon: FileText },
	{ label: "Reports", path: "/reports", icon: FileText },
	// adminOnly: hidden from members in the Sidebar; the /settings route is also
	// guarded by RequireAdmin and the backend's require_admin dependency.
	{ label: "Settings", path: "/settings", icon: Settings, adminOnly: true },
];
