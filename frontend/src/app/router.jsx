import { createBrowserRouter } from "react-router-dom";
import { AppLayout } from "../layout/AppLayout";
import { RequireAuth } from "../routes/RequireAuth";
import { RequireAdmin } from "../routes/RequireAdmin";
import { RedirectIfAuth } from "../routes/RedirectIfAuth";
import { LandingPage } from "../routes/LandingPage";
import { NotFoundPage } from "../routes/NotFoundPage";

import { OverviewPage } from "../features/overview/OverviewPage";
import { AnalyticsPage } from "../features/analytics/AnalyticsPage";
import { ProductsPage } from "../features/products/ProductsPage";
import { InventoryPage } from "../features/inventory/InventoryPage";
import { AdsPage } from "../features/ads/AdsPage";
import { CompetitionPage } from "../features/competition/CompetitionPage";
import { ScorecardPage } from "../features/scorecard/ScorecardPage";
import { SettingsPage } from "../features/settings/SettingsPage";

/**
 * Route table. Three tiers:
 *   - Public "/" (marketing landing) behind RedirectIfAuth — logged-in users
 *     bounce to /overview. Login is a modal on the landing page, not a route.
 *   - The dashboard shell behind RequireAuth inside AppLayout (Overview lives at
 *     /overview).
 *   - Admin-only pages (Settings) nested under RequireAdmin.
 * Paths mirror config/nav.js — keep them in sync.
 */
export const router = createBrowserRouter([
	{
		element: <RedirectIfAuth />,
		children: [{ path: "/", element: <LandingPage /> }],
	},
	{
		element: <RequireAuth />,
		children: [
			{
				element: <AppLayout />,
				children: [
					{ path: "/overview", element: <OverviewPage /> },
					{ path: "/analytics", element: <AnalyticsPage /> },
					{ path: "/products", element: <ProductsPage /> },
					{ path: "/inventory", element: <InventoryPage /> },
					{ path: "/ads", element: <AdsPage /> },
					{ path: "/competition", element: <CompetitionPage /> },
					{ path: "/scorecard", element: <ScorecardPage /> },
					{
						element: <RequireAdmin />,
						children: [
							{
								path: "/settings",
								element: <SettingsPage />,
							},
						],
					},
				],
			},
		],
	},
	{ path: "*", element: <NotFoundPage /> },
]);
