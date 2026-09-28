import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import {
	useShareOfVoice,
	useTopCompetitors,
	useTopCompetitorsByMarketplace,
	useMarketplaceBreakdown,
} from "../hooks";
import { marketplaceName } from "../../../lib/marketplace";
import { MarketplaceMark } from "../../../components/ui/MarketplaceMark";
import { ChannelSplit } from "./ChannelSplit";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatNumber, formatDayLabel as dayLabel } from "../../../lib/format";

/**
 * Where the brand sits on the shelf against everyone else selling into the same
 * searches.
 *
 * Shown as a position rather than a trend. The keyword scrape runs on its own
 * cadence — six days in the last ninety — so a line between those points would
 * draw a continuity the data does not have. The change is stated against the
 * previous scrape, and that scrape is named.
 */
const Delta = ({ points }) => {
	if (points === null || points === undefined)
		return <span className="text-content-subtle">—</span>;
	const flat = Math.round(points * 10) === 0;
	const tone = flat
		? "text-content-muted"
		: points > 0
			? "text-success"
			: "text-danger";
	return (
		<span className={`font-medium ${tone}`}>
			{points > 0 ? "▲" : "▼"} {Math.abs(points).toFixed(1)} pts
		</span>
	);
};

export const VisibilityPanel = () => {
	const { data: sov, isLoading, error, refetch } = useShareOfVoice();
	const { data: breakdown } = useMarketplaceBreakdown();
	const { data: byChannel } = useTopCompetitorsByMarketplace();
	const { data: comp } = useTopCompetitors();

	const summary = sov?.summary;
	const trend = sov?.trend ?? [];
	// The two most recent scraped days, whenever they happened to run.
	const latest = trend[trend.length - 1];
	const before = trend.length > 1 ? trend[trend.length - 2] : null;
	const movePts =
		latest?.avg_sov != null && before?.avg_sov != null
			? latest.avg_sov - before.avg_sov
			: null;

	// The channel-split leaderboard where it is available: a competitor's
	// store count and rank are per marketplace, and one blended row hides
	// that it leads on one shelf and trails on another.
	const split = byChannel ?? [];
	const showChannel = new Set(split.map((r) => r.marketplace)).size > 1;
	const blended = comp?.competitors ?? [];
	const competitors = showChannel ? split : blended;

	return (
		<section className="flex flex-col">
			<div className="grid grid-cols-1 gap-8 rounded-xl border border-border bg-card p-6 lg:grid-cols-5">
				<div className="flex flex-col gap-5 lg:col-span-2">
					{isLoading && <Loading label="Loading visibility…" />}
					{error && (
						<ErrorState message={error.message} onRetry={refetch} />
					)}

					{summary && (
						<>
							<div className="flex flex-col gap-1">
								<p className="text-[11px] font-semibold tracking-[0.1em] text-content-subtle uppercase">
									Share of voice
								</p>
								<p className="font-display text-3xl font-bold text-content tabular-nums">
									{summary.latest_sov == null
										? "—"
										: `${summary.latest_sov.toFixed(1)}%`}
								</p>
								<p className="text-xs text-content-muted">
									<Delta points={movePts} />{" "}
									{before
										? `vs ${dayLabel(before.date)}`
										: "no earlier scrape"}
								</p>
							</div>

							{/* Where that share of voice was won. A share of an
							    average share is meaningless, so no split. */}
							<ChannelSplit
								rows={(breakdown ?? []).filter(
									(m) =>
										m.connected &&
										m.visibility?.value != null,
								)}
								metric="visibility"
								label="Period avg"
								format="percent"
								showShare={false}
								extras={[
									{
										label: "Avg rank",
										width: "w-16",
										value: (m) =>
											m.avg_rank?.value == null
												? "—"
												: m.avg_rank.value.toFixed(1),
									},
								]}
							/>
						</>
					)}
				</div>

				<div className="lg:col-span-3">
					{competitors.length === 0 ? (
						!isLoading && (
							<EmptyState message="No competitors seen in this period." />
						)
					) : (
						<>
							<div className="flex items-baseline gap-3 border-b border-border pb-1.5 text-[11px] tracking-wide text-content-subtle uppercase">
								{showChannel && (
									<span className="w-24 pl-2">Channel</span>
								)}
								<span className="flex-1 pl-2">Competitor</span>
								<span className="w-20 text-right">Stores</span>
								<span className="w-20 text-right">
									Avg rank
								</span>
								{/* The denominator is the competitor set, not the
								    whole shelf — our own listings are not in it. */}
								<span
									className="w-16 cursor-help text-right"
									title="Share of competitor presence, excluding our own brand"
								>
									Share
								</span>
							</div>
							<ul className="flex flex-col">
								{competitors.map((c) => (
									<li
										key={`${c.marketplace ?? ""}|${c.competitor}`}
										className="flex items-center gap-3 border-b border-border py-2 last:border-0"
									>
										{showChannel && (
											<span className="flex w-24 min-w-0 items-center gap-1.5 pl-2 text-sm text-content">
												<MarketplaceMark
													marketplace={{
														slug: c.marketplace,
														name: marketplaceName(
															c.marketplace,
														),
													}}
													size={15}
												/>
												<span className="truncate">
													{marketplaceName(
														c.marketplace,
													)}
												</span>
											</span>
										)}
										<span className="min-w-0 flex-1 truncate pl-2 text-sm text-content capitalize">
											{c.competitor.replace(/-/g, " ")}
										</span>
										<span className="w-20 text-right text-sm text-content-muted tabular-nums">
											{formatNumber(c.stores)}
										</span>
										<span className="w-20 text-right text-sm text-content-muted tabular-nums">
											{c.avg_position == null
												? "—"
												: c.avg_position.toFixed(1)}
										</span>
										<span className="w-16 text-right text-sm font-medium text-content tabular-nums">
											{c.share_pct == null
												? "—"
												: `${c.share_pct.toFixed(0)}%`}
										</span>
									</li>
								))}
							</ul>

							<Link
								to="/competition"
								className="mt-4 flex items-center justify-end gap-1 border-t border-border pt-3 text-xs font-medium text-brand hover:underline"
							>
								See all competitors
								<ArrowRight size={12} aria-hidden />
							</Link>
						</>
					)}
				</div>
			</div>
		</section>
	);
};
