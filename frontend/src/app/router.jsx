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
import { ProductDetailPage } from "../features/products/ProductDetailPage";
import { InventoryPage } from "../features/inventory/InventoryPage";
import { AdsPage } from "../features/ads/AdsPage";
import { InsightsPage } from "../features/ads-insights/InsightsPage";
import { CampaignManagerPage } from "../features/campaign-manager/CampaignManagerPage";
import { CampaignManagerV2Page } from "../features/campaign-manager-v2/CampaignManagerV2Page";
import { AutomationsPage } from "../features/automations/AutomationsPage";
import { CompetitionPage } from "../features/competition/CompetitionPage";
import { ScorecardPage } from "../features/scorecard/ScorecardPage";
import { ReportsPage } from "../features/reports/ReportsPage";
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
					{
						path: "/products/:itemId",
						element: <ProductDetailPage />,
					},
					{ path: "/inventory", element: <InventoryPage /> },
					{ path: "/ads", element: <AdsPage /> },
					{ path: "/ads/insights", element: <InsightsPage /> },
					// Ad Automation and /automations are ONE page under two paths: the Ads
					// child is where the nav points, and /automations keeps older links working.
					{ path: "/ads/automation", element: <AutomationsPage /> },
					{
						path: "/campaign-manager",
						element: <CampaignManagerPage />,
					},
					{
						path: "/campaign-manager-v2",
						element: <CampaignManagerV2Page />,
					},
					{ path: "/automations", element: <AutomationsPage /> },
					{ path: "/competition", element: <CompetitionPage /> },
					{ path: "/scorecard", element: <ScorecardPage /> },
					{ path: "/reports", element: <ReportsPage /> },
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
