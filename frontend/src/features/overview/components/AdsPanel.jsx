import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import {
	useOverview,
	useTopCampaigns,
	useMarketplaceBreakdown,
} from "../hooks";
import { ChannelSplit } from "./ChannelSplit";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCurrency } from "../../../lib/format";
import { useDailyBudgetUtilisation } from "../../../lib/budgetUtilisation";
import { buBand } from "../../../lib/budgetBands";
import { useDateRange } from "../../../context/DateRangeContext";
import { previousRangeLabel } from "../../../lib/dates";
import { marketplaceName } from "../../../lib/marketplace";
import { MarketplaceMark } from "../../../components/ui/MarketplaceMark";

/**
 * How advertising did over the selected window: what it returned, and which
 * campaigns returned it.
 *
 * Campaigns are ranked by attributed REVENUE rather than spend — the question
 * is which ones are carrying the period, and the biggest spender is not always
 * the answer. Each row shows what it cost beside what it earned, so a large
 * share bought at a poor return cannot hide behind its size.
 */
/** The move against the window before, with that window's figure on hover.
 *  Nothing to compare against is left blank rather than dashed. */
const Change = ({ delta, prev }) => {
	if (delta == null) return null;
	const pct = delta * 100;
	const tone =
		Math.round(pct) === 0
			? "text-content-muted"
			: pct > 0
				? "text-success"
				: "text-danger";
	return (
		<p
			title={prev}
			className={`cursor-help text-xs font-medium tabular-nums ${tone}`}
		>
			{pct > 0 ? "▲" : "▼"} {Math.abs(pct).toFixed(0)}%
		</p>
	);
};

export const AdsPanel = () => {
	const { data: summary } = useOverview();
	const { range } = useDateRange();
	const { data, isLoading, error, refetch } = useTopCampaigns();
	const { data: breakdown } = useMarketplaceBreakdown();

	const all = data?.items ?? [];

	// Utilisation comes from the same hook the Ads page uses, so the two screens
	// cannot report different percentages of the same money. It reads the last
	// seven days rather than the picked window: the figures beside it follow the
	// picker, but a standing daily budget is only meaningful over recent days,
	// since nothing records what that budget was further back.
	const { campaigns: buCampaigns } = useDailyBudgetUtilisation({ days: 7 });
	// The same seven days at campaign grain, so a row can show what that campaign
	// used. Days it did not run contribute to neither side of the division: a
	// campaign that ran twice at full budget is fully utilised, not 2/7ths of it.
	const buByCampaign = new Map(
		buCampaigns.map((c) => {
			const ran = c.days.filter((d) => d.allowed);
			const spend = ran.reduce((s, d) => s + d.spend, 0);
			const allowed = ran.reduce((s, d) => s + d.allowed, 0);
			return [c.campaign_id, allowed ? (spend / allowed) * 100 : null];
		}),
	);

	// Top eight by attributed revenue.
	const earning = all.filter((c) => c.ad_sales > 0);
	const campaigns = earning.slice(0, 8);

	// The channel column earns its width only where campaigns run on more than
	// one — otherwise it repeats the same word down every row.
	const showChannel = new Set(earning.map((c) => c.marketplace)).size > 1;
	return (
		<section className="flex flex-col">
			<div className="grid grid-cols-1 gap-8 rounded-xl border border-border bg-card p-6 lg:grid-cols-5">
				<div className="flex flex-col gap-5 lg:col-span-2">
					<div className="flex flex-col gap-1">
						<p className="text-[11px] font-semibold tracking-[0.1em] text-content-subtle uppercase">
							Ad revenue
						</p>
						<p className="font-display text-3xl font-bold text-content tabular-nums">
							{formatCurrency(summary?.ad_sales?.value)}
						</p>
						<Change
							delta={summary?.ad_sales?.delta_pct}
							prev={
								summary?.ad_sales?.prev == null
									? `Nothing recorded in ${previousRangeLabel(range)}`
									: `${formatCurrency(summary.ad_sales.prev)} over ${previousRangeLabel(range)}`
							}
						/>
					</div>

					{/* Which channels the ad revenue above came from. */}
					<ChannelSplit
						rows={(breakdown ?? []).filter(
							(m) => m.connected && m.ad_sales?.value != null,
						)}
						metric="ad_sales"
						label="Ad revenue"
						extras={[
							{
								label: "RoAS",
								width: "w-14",
								value: (m) =>
									m.roas?.value == null
										? "—"
										: `${m.roas.value.toFixed(2)}×`,
							},
						]}
					/>
				</div>

				<div className="lg:col-span-3">
					{isLoading && <Loading label="Loading campaigns…" />}
					{error && (
						<ErrorState message={error.message} onRetry={refetch} />
					)}
					{!isLoading && !error && campaigns.length === 0 && (
						<EmptyState message="No campaign revenue in this period." />
					)}

					{campaigns.length > 0 && (
						<>
							{/* One line per campaign, the channel it ran on, then
							    what it cost, what it earned, the ratio, and how
							    much of its budget it is actually using. */}
							<div className="flex items-baseline gap-3 border-b border-border pb-1.5 text-xs tracking-wide text-content-subtle uppercase">
								{showChannel && (
									<span className="w-24">Channel</span>
								)}
								<span className="flex-1">Campaign</span>
								<span className="w-24 text-right">Spend</span>
								<span className="w-24 text-right">
									Ad revenue
								</span>
								<span className="w-14 text-right">RoAS</span>
								<span className="w-20 text-right">Budget</span>
							</div>
							<ul className="flex flex-col">
								{campaigns.map((c) => (
									<li
										key={c.campaign_id}
										className="flex items-center gap-3 border-b border-border py-2 last:border-0"
									>
										{showChannel && (
											<span className="flex w-24 min-w-0 items-center gap-1.5 text-sm text-content">
												<MarketplaceMark
													marketplace={{
														slug: c.marketplace,
														name: marketplaceName(
															c.marketplace,
														),
													}}
													size={16}
												/>
												<span className="truncate">
													{marketplaceName(
														c.marketplace,
													)}
												</span>
											</span>
										)}
										<span
											title={
												c.name ?? String(c.campaign_id)
											}
											className="min-w-0 flex-1 truncate text-sm text-content"
										>
											{c.name ?? c.campaign_id}
										</span>
										<span className="w-24 text-right text-sm text-content-muted tabular-nums">
											{formatCurrency(c.budget_consumed)}
										</span>
										<span className="w-24 text-right text-sm font-medium text-content tabular-nums">
											{formatCurrency(c.ad_sales)}
										</span>
										<span className="w-14 text-right text-sm text-content-muted tabular-nums">
											{c.roas.toFixed(2)}×
										</span>
										<span
											className={`w-20 text-right text-sm font-medium tabular-nums ${
												buBand(
													buByCampaign.get(
														c.campaign_id,
													),
												)?.text ?? "text-content-subtle"
											}`}
										>
											{buByCampaign.get(c.campaign_id) ==
											null
												? "—"
												: `${buByCampaign.get(c.campaign_id).toFixed(0)}%`}
										</span>
									</li>
								))}
							</ul>

							{/* The table is the top eight; the rest live on the Ads page. */}
							<Link
								to="/ads/insights"
								className="mt-4 flex items-center justify-end gap-1 border-t border-border pt-3 text-xs font-medium text-brand hover:underline"
							>
								See all campaigns
								{earning.length > campaigns.length &&
									` (${earning.length})`}
								<ArrowRight size={12} aria-hidden />
							</Link>
						</>
					)}
				</div>
			</div>
		</section>
	);
};
