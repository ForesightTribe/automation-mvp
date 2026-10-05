import { useRecentDays } from "./hooks";
import { YesterdayGlance } from "./components/YesterdayGlance";
import { RevenuePanel } from "./components/RevenuePanel";
import { AdsPanel } from "./components/AdsPanel";
import { PoPanel } from "./components/PoPanel";
import { ReachPanel } from "./components/ReachPanel";
import { VisibilityPanel } from "./components/VisibilityPanel";
import { PricePanel } from "./components/PricePanel";
import { OverviewExport } from "./components/OverviewExport";
import { Loading } from "../../components/feedback/Loading";
import { useMarketplaces } from "../../context/MarketplaceContext";
import { PriorityProvider } from "./priority";

/**
 * Overview — a daily briefing, read top to bottom: how yesterday went, then how
 * the selected period is trending.
 *
 * The opening block always reads the latest complete day, whatever range is
 * selected; everything from the trajectory down follows the date picker. The two
 * are kept apart so it is clear which is which.
 */
export const OverviewPage = () => {
	const { data: recent, isLoading } = useRecentDays();
	// ⚠️ Nothing on this page may draw before the marketplace picker resolves.
	// Until it does, the selection is empty, and every "is this multi-channel?"
	// test on the page reads that as a tenant with ONE channel — so the whole
	// page would render its single-channel layout and then swap.
	const { ready } = useMarketplaces();

	const rows = recent ?? [];

	if (!ready) return <Loading label="Loading overview…" />;

	return (
		<PriorityProvider>
			<div className="flex flex-col gap-10">
				<div className="flex flex-col gap-4">
					{/* The page as one file, above the sections it covers —
				    it is the whole overview, not yesterday's part of it. */}
					<div className="flex items-center justify-end">
						<OverviewExport />
					</div>

					{isLoading && <Loading label="Loading overview…" />}
					{!isLoading && <YesterdayGlance rows={rows} />}
				</div>

				{/* Follows the date picker, unlike the block above it. */}
				<RevenuePanel />

				<AdsPanel />

				<PoPanel />

				<ReachPanel />

				<VisibilityPanel />

				<PricePanel />
			</div>
		</PriorityProvider>
	);
};
