import { useMarketplaceBreakdown } from "../hooks";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { MarketplaceCard } from "./MarketplaceCard";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";

/**
 * Marketplace-wise overview: one card per marketplace. Shows the selected
 * connected marketplaces (driven by the global selector) plus every unconnected
 * one as a "coming soon" card, so the multi-marketplace shape is always visible
 * even while only Blinkit has data.
 */
export const MarketplaceBreakdown = () => {
	const { data, isLoading, error, refetch } = useMarketplaceBreakdown();
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
						<MarketplaceCard key={row.slug} row={row} />
					))}
				</div>
			)}
		</section>
	);
};
