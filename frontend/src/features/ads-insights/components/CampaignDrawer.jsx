import { useMemo } from "react";
import { Drawer } from "../../../components/ui/Drawer";
import { Stat, Section } from "../../../components/ui/Stat";
import { Loading } from "../../../components/feedback/Loading";
import { EChart } from "../../../components/charts/EChart";
import { miniCompareOption, SERIES } from "../chartOptions";
import { enumLabel } from "./insightsTable";
import { useCampaigns, useKeywords } from "../hooks";
import { useDateRange } from "../../../context/DateRangeContext";
import {
	formatCurrency,
	formatNumber,
	formatPercent,
} from "../../../lib/format";

/**
 * One campaign in full, opened from the table. Read-only: acting on the campaign stays in
 * the row's controls, so opening a detail view can never be what changes a live account.
 */
export const CampaignDrawer = ({ campaignId, open, onClose }) => {
	const { range, days } = useDateRange();
	const { data: page } = useCampaigns({
		page: 1,
		limit: 250,
		sort: "spend",
		order: "desc",
	});
	const { data: kw, isLoading: loadingKw } = useKeywords({
		campaignId: open ? campaignId : null,
		page: 1,
		limit: 50,
		sort: "spend",
		order: "desc",
	});

	const c = (page?.items ?? []).find((r) => r.campaign_id === campaignId);
	const keywords = useMemo(() => (kw?.items ?? []).slice(0, 10), [kw]);

	if (!open) return null;

	// A fraction, because formatPercent multiplies by 100 on the way out.
	const acos = c?.ad_sales ? c.budget_consumed / c.ad_sales : null;
	const aov = c?.quantities_sold ? c.ad_sales / c.quantities_sold : null;
	const cpm = c?.impressions
		? (c.budget_consumed / c.impressions) * 1000
		: null;
	const allowed = c?.daily_budget != null ? c.daily_budget * days : null;
	const bu = allowed ? (c.budget_consumed / allowed) * 100 : null;

	return (
		<Drawer
			open={open}
			onClose={onClose}
			title={c?.name ?? `Campaign ${campaignId}`}
			subtitle={`ID ${campaignId}${c?.type ? ` · ${enumLabel(c.type)}` : ""}${c?.status ? ` · ${enumLabel(c.status)}` : ""}`}
			stats={
				<>
					<Stat
						label="Ad spend"
						value={formatCurrency(c?.budget_consumed ?? 0)}
					/>
					<Stat
						label="Ad sales"
						value={formatCurrency(c?.ad_sales ?? 0)}
					/>
					<Stat
						label="ROAS"
						value={c?.roas == null ? "—" : `${c.roas.toFixed(2)}x`}
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
						["ACoS", acos == null ? "—" : formatPercent(acos)],
						[
							"Average order value",
							aov == null ? "—" : formatCurrency(aov),
						],
						["Impressions", formatNumber(c?.impressions ?? 0)],
						["Add to cart", formatNumber(c?.atc ?? 0)],
						["Units sold", formatNumber(c?.quantities_sold ?? 0)],
						[
							"Average CPM",
							cpm == null ? "—" : formatCurrency(cpm),
						],
						[
							"Budget utilisation",
							bu == null
								? "no daily budget reported"
								: formatPercent(bu),
						],
						[
							"Daily budget",
							c?.daily_budget != null
								? formatCurrency(c.daily_budget)
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
				title="Top keywords by spend"
				hint={loadingKw ? "" : `${kw?.total ?? 0} total`}
			>
				{loadingKw ? (
					<Loading label="Loading keywords…" />
				) : keywords.length === 0 ? (
					<p className="text-sm text-content-muted">
						No keyword rows for this campaign in this window.
					</p>
				) : (
					<>
						<div className="mb-3">
							<EChart
								option={miniCompareOption(
									keywords.map((k) => k.budget_consumed),
									[],
									{
										color: SERIES[0],
										format: formatCurrency,
									},
								)}
								height={110}
							/>
						</div>
						<table className="w-full text-sm">
							<tbody>
								{keywords.map((k) => (
									<tr
										key={`${k.target}|${k.match_type ?? ""}`}
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
											{formatCurrency(
												k.budget_consumed ?? 0,
											)}
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
					</>
				)}
			</Section>
		</Drawer>
	);
};
