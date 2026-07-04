import { useRankMatrix } from "./hooks";
import { SovKpis } from "./components/SovKpis";
import { SovTrendCard } from "./components/SovTrendCard";
import { RankHeatmapCard } from "./components/RankHeatmapCard";
import { TopCompetitorsCard } from "./components/TopCompetitorsCard";
import { PricePositionCard } from "./components/PricePositionCard";
import { FreshnessBadge } from "../../components/ui/FreshnessBadge";

/**
 * Competition — "how do I look on the shelf vs competitors?" The home for the
 * keyword-scrape insights: share of voice, the keyword × city rank heatmap
 * (where am I weak), the competitor leaderboard, and price positioning. All
 * public-scrape data is weekly, so the header carries a freshness badge and each
 * section keys on the global date window's `days`.
 */
export const CompetitionPage = () => {
	// Freshness for the whole page comes from the rank-matrix `as_of` (same
	// keyword-scrape source that feeds most sections).
	const { data: matrix } = useRankMatrix();

	return (
		<div className="flex flex-col gap-6">
			<div className="flex items-start justify-between gap-3">
				<div>
					<h1 className="font-display text-xl font-bold text-content">
						Competition
					</h1>
					<p className="text-sm text-content-muted">
						How you look on the shelf vs competitors.
					</p>
				</div>
				<FreshnessBadge at={matrix?.as_of} />
			</div>

			<SovKpis />

			<SovTrendCard />

			<RankHeatmapCard />

			<div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
				<TopCompetitorsCard />
				<PricePositionCard />
			</div>
		</div>
	);
};
