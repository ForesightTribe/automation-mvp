import { useAdMarketplaces } from "../hooks";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { AdMarketplaceCard } from "./AdMarketplaceCard";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";

/**
 * Ads by marketplace: one card per marketplace, so "All" is a visible per-MP split
 * rather than only a combined total. Shows the selected connected marketplaces plus
 * every unconnected one as a "coming soon" card. Mirrors the Overview breakdown.
 */
export const AdMarketplaceBreakdown = () => {
	const { data, isLoading, error, refetch } = useAdMarketplaces();
	const { selected } = useMarketplaces();

	if (isLoading) return <Loading label="Loading marketplaces…" />;
	if (error) return <ErrorState message={error.message} onRetry={refetch} />;

	const rows = (data ?? []).filter(
		(r) => !r.connected || selected.includes(r.slug),
	);

	return (
		<section className="flex flex-col gap-3">
			<h2 className="font-display text-sm font-semibold text-content">
				By marketplace
			</h2>
			{rows.length === 0 ? (
				<EmptyState message="No marketplaces selected." />
			) : (
				<div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
					{rows.map((row) => (
						<AdMarketplaceCard key={row.slug} row={row} />
					))}
				</div>
			)}
		</section>
	);
};
