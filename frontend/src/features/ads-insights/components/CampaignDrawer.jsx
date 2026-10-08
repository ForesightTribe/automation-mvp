import { Drawer } from "../../../components/ui/Drawer";
import { Stat, Section } from "../../../components/ui/Stat";
import { Loading } from "../../../components/feedback/Loading";
import { EChart } from "../../../components/charts/EChart";
import { miniCompareOption, SERIES } from "../chartOptions";
import { enumLabel, MiniTable } from "./insightsTable";
import { RoasPill } from "./explorer/explorerColumns";
import { useCampaignKeywords, useDataWindow } from "../hooks";
import { useDateRange } from "../../../context/DateRangeContext";
import { campaignStatusLabel } from "../../../components/ui/CampaignStatusBadge";
import {
	formatCurrency,
	formatDate,
	formatNumber,
	formatPercent,
} from "../../../lib/format";

/**
 * One campaign in full, opened from the table. Read-only: acting on the campaign stays in
 * the row's controls, so opening a detail view can never be what changes a live account.
 *
 * `campaign` is the table's own row, so the figures here are the ones on the row and no
 * second copy of the campaign list is fetched. Its top keywords come from ITS marketplace
 * (`/ads/campaign-keywords`): Blinkit's 8-day snapshot, Zepto's per-day keyword report summed
 * over the window, Instamart's keyword table. Zepto's used to be looked up in Blinkit's table
 * and always came back empty.
 */
export const CampaignDrawer = ({ campaign: c, open, onClose }) => {
	const { range } = useDateRange();
	// Days with ad data only: a window ending today must not count today's budget as unspent (N1).
	const data = useDataWindow();
	const days = data.days;
	const isInstamart = c?.platform === "instamart";
	const { data: kw, isLoading: loadingKw } = useCampaignKeywords(
		c?.platform,
		c?.campaign_id,
		{ enabled: open },
	);

	if (!open || !c) return null;

	const keywords = kw?.items ?? [];
	const hasPosition = keywords.some((k) => k.position != null);
	// What the keyword figures cover. Blinkit's are an 8-day snapshot, so they are labelled
	// with their own dates rather than the picker's.
	const kwPeriod =
		kw?.period_start && kw?.period_end
			? `${formatDate(kw.period_start)} to ${formatDate(kw.period_end)}`
			: "";
	const isSnapshot = c.platform === "blinkit";

	// A fraction, because formatPercent multiplies by 100 on the way out.
	const acos = c.ad_sales ? c.budget_consumed / c.ad_sales : null;
	// Instamart's units-sold figure is unreliable (confirmed 2026-09-30), so AOV — derived
	// from it — is withheld for Instamart rows only.
	const aov =
		!isInstamart && c.quantities_sold
			? c.ad_sales / c.quantities_sold
			: null;
	const cpm = c.impressions
		? (c.budget_consumed / c.impressions) * 1000
		: null;
	const allowed = c.daily_budget != null ? c.daily_budget * days : null;
	const bu = allowed ? c.budget_consumed / allowed : null;

	return (
		<Drawer
			open={open}
			onClose={onClose}
			title={c.name ?? `Campaign ${c.campaign_id}`}
			subtitle={`${enumLabel(c.platform)} · ID ${c.campaign_id}${c.type ? ` · ${enumLabel(c.type)}` : ""}${c.status ? ` · ${campaignStatusLabel(c.status)}` : ""}`}
			stats={
				<>
					<Stat
						label="Ad spend"
						value={formatCurrency(c.budget_consumed ?? 0)}
					/>
					<Stat
						label="Ad sales"
						value={formatCurrency(c.ad_sales ?? 0)}
					/>
					<Stat
						label="ROAS"
						value={c.roas == null ? "—" : `${c.roas.toFixed(2)}x`}
					/>
				</>
			}
		>
			<Section
				title="Performance"
				hint={`${data.from} to ${data.to} · ${days} days${data.partial ? " with data" : ""}`}
			>
				<dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
					{[
						["ACoS", acos == null ? "—" : formatPercent(acos)],
						...(isInstamart
							? []
							: [
									[
										"Average order value",
										aov == null ? "—" : formatCurrency(aov),
									],
								]),
						["Impressions", formatNumber(c.impressions ?? 0)],
						["Add to cart", formatNumber(c.atc ?? 0)],
						...(isInstamart
							? []
							: [
									[
										"Units sold",
										formatNumber(c.quantities_sold ?? 0),
									],
								]),
						[
							"Average CPM",
							cpm == null ? "—" : formatCurrency(cpm),
						],
						[
							"Budget utilisation",
							// A fraction: this was a percentage passed through formatPercent, which
							// multiplies by 100 again — 49.9% read "4990%".
							bu == null
								? "no daily budget reported"
								: formatPercent(bu, 1),
						],
						[
							"Daily budget",
							c.daily_budget != null
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
				hint={loadingKw || !kw ? "" : `${kw.total} total`}
			>
				{loadingKw ? (
					<Loading label="Loading keywords…" />
				) : keywords.length === 0 ? (
					<p className="text-sm text-content-muted">
						{isSnapshot
							? `No Blinkit keyword report for this campaign on or before ${formatDate(range.to)}.`
							: "No keyword activity for this campaign in this window."}
					</p>
				) : (
					<>
						{isSnapshot && kwPeriod && (
							<p className="mb-2 text-xs text-content-subtle">
								Blinkit reports keywords as an 8-day total —
								these cover {kwPeriod}, not the selected dates.
							</p>
						)}
						<div className="mb-3">
							<EChart
								option={miniCompareOption(
									keywords.map((k) => k.spend),
									[],
									{
										color: SERIES[0],
										format: formatCurrency,
									},
								)}
								height={110}
							/>
						</div>
						<MiniTable
							head={[
								{ label: "Keyword" },
								...(keywords.some((k) => k.match_type)
									? [{ label: "Match" }]
									: []),
								...(hasPosition
									? [{ label: "Position", align: "right" }]
									: []),
								{ label: "Spend", align: "right" },
								{ label: "Sales", align: "right" },
								{ label: "RoAS", align: "right" },
							]}
							rows={keywords.map((k) => ({
								key: `${k.keyword}|${k.match_type ?? ""}`,
								cells: [
									<span
										key="k"
										className="block truncate text-content"
										title={k.keyword}
									>
										{k.keyword}
									</span>,
									...(keywords.some((x) => x.match_type)
										? [
												<span
													key="m"
													className="text-content-muted"
												>
													{k.match_type
														? enumLabel(
																k.match_type,
															)
														: "—"}
												</span>,
											]
										: []),
									...(hasPosition
										? [
												k.position != null
													? `#${k.position}`
													: "—",
											]
										: []),
									formatCurrency(k.spend ?? 0),
									formatCurrency(k.sales ?? 0),
									<RoasPill key="r" value={k.roas} />,
								],
							}))}
						/>
					</>
				)}
			</Section>
		</Drawer>
	);
};
