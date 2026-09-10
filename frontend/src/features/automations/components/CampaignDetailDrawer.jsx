import { useMemo } from "react";
import { Drawer } from "../../../components/ui/Drawer";
import { Loading } from "../../../components/feedback/Loading";
import { StatusPill } from "./StatusPill";
import { ChannelBadge } from "./ChannelBadge";
import { budgetScheduleTags, bidRuleTags } from "../automation";
import { ActionsSummaryPills } from "./ActionsSummaryPills";
import { useCampaignsForRange, useHistory, useKeywordMetrics } from "../hooks";
import { useDateRange } from "../../../context/DateRangeContext";
import { formatCurrency, formatNumber } from "../../../lib/format";

const Stat = ({ label, value }) => (
	<div className="bg-card px-4 py-3">
		<p className="text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
			{label}
		</p>
		<p className="mt-1 font-display text-lg font-semibold text-content tabular-nums">
			{value}
		</p>
	</div>
);

const Section = ({ title, hint, children }) => (
	<section className="mb-6 last:mb-0">
		<div className="mb-2 flex items-baseline justify-between gap-3">
			<h3 className="text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
				{title}
			</h3>
			{hint && (
				<span className="text-[11px] text-content-subtle">{hint}</span>
			)}
		</div>
		{children}
	</section>
);

const when = (iso) =>
	new Intl.DateTimeFormat("en-IN", {
		day: "numeric",
		month: "short",
		hour: "numeric",
		minute: "2-digit",
		hour12: true,
	}).format(new Date(iso));

/**
 * Everything this account knows about one campaign, gathered from the sources already on
 * the page: its performance from the campaign list, the automations pointed at it, the
 * keywords it runs, and what the engine has actually done to it.
 *
 * Read-only on purpose. Acting on the campaign stays in the row's own controls, so opening
 * a detail view can never be the thing that changes a live account.
 */
export const CampaignDetailDrawer = ({
	campaignId,
	open,
	onClose,
	schedules = [],
	bidRules = [],
}) => {
	const { data: campaigns } = useCampaignsForRange();
	const { range, days } = useDateRange();
	const { data: keywords, isLoading: loadingKw } = useKeywordMetrics(
		open ? campaignId : null,
	);
	const { data: history } = useHistory(1);

	const campaign = (campaigns ?? []).find(
		(c) => c.campaign_id === campaignId,
	);
	const mySchedules = schedules.filter((s) => s.campaign_id === campaignId);
	const myBidRules = bidRules.filter((b) => b.campaign_id === campaignId);

	const topKeywords = useMemo(
		() =>
			[...(keywords ?? [])]
				.sort(
					(a, b) =>
						(b.budget_consumed ?? 0) - (a.budget_consumed ?? 0),
				)
				.slice(0, 8),
		[keywords],
	);
	const activity = (history?.items ?? [])
		.filter((r) => r.campaign_id === campaignId)
		.slice(0, 6);

	if (!open) return null;

	const roas = campaign?.roas;
	const aov = campaign?.quantities_sold
		? campaign.ad_sales / campaign.quantities_sold
		: null;
	const cpm = campaign?.impressions
		? (campaign.budget_consumed / campaign.impressions) * 1000
		: null;

	return (
		<Drawer
			open={open}
			onClose={onClose}
			title={campaign?.name ?? `Campaign ${campaignId}`}
			subtitle={`ID ${campaignId}${campaign?.type ? ` · ${campaign.type}` : ""}${
				campaign?.status ? ` · ${campaign.status}` : ""
			}`}
			stats={
				<>
					<Stat
						label="Ad spend"
						value={formatCurrency(campaign?.budget_consumed ?? 0)}
					/>
					<Stat
						label="Ad sales"
						value={formatCurrency(campaign?.ad_sales ?? 0)}
					/>
					<Stat
						label="ROAS"
						value={roas == null ? "—" : `${roas.toFixed(2)}x`}
					/>
				</>
			}
		>
			<Section
				title="Performance"
				hint={`${range.from} to ${range.to} · ${days} days`}
			>
				<dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
					{[
						[
							"Impressions",
							formatNumber(campaign?.impressions ?? 0),
						],
						["Add to cart", formatNumber(campaign?.atc ?? 0)],
						[
							"Units sold",
							formatNumber(campaign?.quantities_sold ?? 0),
						],
						[
							"Average order value",
							aov == null ? "—" : formatCurrency(aov),
						],
						[
							"Average CPM",
							cpm == null ? "—" : formatCurrency(cpm),
						],
						[
							"Daily budget",
							campaign?.daily_budget != null
								? formatCurrency(campaign.daily_budget)
								: "not reported",
						],
					].map(([k, v]) => (
						<div
							key={k}
							className="flex justify-between gap-3 border-b border-border/60 py-1"
						>
							<dt className="text-content-muted">{k}</dt>
							<dd className="tabular-nums text-content">{v}</dd>
						</div>
					))}
				</dl>
			</Section>

			<Section
				title="Automations on this campaign"
				hint={`${mySchedules.length + myBidRules.length} total`}
			>
				{mySchedules.length + myBidRules.length === 0 ? (
					<p className="text-sm text-content-muted">
						Nothing is automating this campaign yet.
					</p>
				) : (
					<ul className="space-y-2">
						{mySchedules.map((s) => (
							<li
								key={`s${s.id}`}
								className="rounded-md border border-border p-3"
							>
								<div className="mb-1 flex items-center gap-2">
									<span className="text-sm font-medium text-content">
										{s.name || "Budget automation"}
									</span>
									<StatusPill status={s.status} />
									<ChannelBadge platform={s.platform} />
								</div>
								<ActionsSummaryPills
									tags={budgetScheduleTags(s)}
								/>
							</li>
						))}
						{myBidRules.map((b) => (
							<li
								key={`b${b.id}`}
								className="rounded-md border border-border p-3"
							>
								<div className="mb-1 flex items-center gap-2">
									<span className="text-sm font-medium text-content">
										{b.keyword}
									</span>
									<StatusPill status={b.status} />
									<ChannelBadge platform={b.platform} />
								</div>
								<ActionsSummaryPills tags={bidRuleTags(b)} />
							</li>
						))}
					</ul>
				)}
			</Section>

			<Section
				title="Top keywords by spend"
				hint={loadingKw ? "" : `${keywords?.length ?? 0} total`}
			>
				{loadingKw ? (
					<Loading label="Loading keywords…" />
				) : topKeywords.length === 0 ? (
					<p className="text-sm text-content-muted">
						No keyword data scraped for this campaign yet.
					</p>
				) : (
					<table className="w-full text-sm">
						<tbody>
							{topKeywords.map((k) => (
								<tr
									key={k.target}
									className="border-b border-border/60 last:border-0"
								>
									<td className="py-1.5 pr-2 text-content">
										{k.target}
									</td>
									<td className="py-1.5 text-right tabular-nums text-content-muted">
										{k.most_viewed_position != null
											? `#${k.most_viewed_position}`
											: "—"}
									</td>
									<td className="py-1.5 text-right tabular-nums text-content">
										{formatCurrency(k.budget_consumed ?? 0)}
									</td>
									<td className="py-1.5 text-right tabular-nums text-content-muted">
										{k.total_roas != null
											? `${k.total_roas.toFixed(2)}x`
											: "—"}
									</td>
								</tr>
							))}
						</tbody>
					</table>
				)}
			</Section>

			<Section title="Recent activity">
				{activity.length === 0 ? (
					<p className="text-sm text-content-muted">
						The engine has not acted on this campaign yet.
					</p>
				) : (
					<ul className="space-y-1.5">
						{activity.map((r) => (
							<li
								key={r.id}
								className="flex justify-between gap-3 text-sm"
							>
								<span
									className={
										r.success
											? "text-content"
											: "text-danger"
									}
								>
									{r.action}
									{r.new_value != null &&
										` ${formatCurrency(r.new_value)}`}
									{r.keyword && (
										<span className="text-content-muted">
											{" "}
											· {r.keyword}
										</span>
									)}
									{/* A dry run changed nothing on the account, and saying so is the
									    difference between "it worked" and "it would have". */}
									{r.dry_run && (
										<span className="ml-1 text-xs text-content-subtle">
											(dry run)
										</span>
									)}
								</span>
								<span className="shrink-0 text-xs text-content-subtle">
									{when(r.timestamp)}
								</span>
							</li>
						))}
					</ul>
				)}
			</Section>
		</Drawer>
	);
};
