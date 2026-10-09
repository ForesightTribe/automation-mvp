import { useMemo, useState } from "react";
import {
	useBudgetSplit,
	usePreviousBudgetSplit,
	usePreviousRange,
} from "../hooks";
import { Card } from "../../../components/ui/Card";
import { EChart } from "../../../components/charts/EChart";
import { InfoTooltip } from "../../../components/ui/InfoTooltip";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { insightsDonutOption, SERIES } from "../chartOptions";
import { chartColor, OTHER_COLOR } from "../../../lib/marketplaceColors";
import { marketplaceName } from "../../../lib/marketplace";
import { formatCurrency } from "../../../lib/format";
import { MarketplaceTag, enumLabel } from "./insightsTable";

const roasText = (v) => (v == null ? "—" : `${v.toFixed(2)}x`);
const ROW =
	"grid items-center gap-8 border-b border-muted py-1.5 text-sm grid-cols-[11rem_7rem_5rem_5rem]";
const ROW_CMP =
	"grid items-center gap-8 border-b border-muted py-1.5 text-sm grid-cols-[11rem_7rem_5rem_5rem_5.5rem]";

/** A marketplace with more than this many types shows its top 3 and "+ N more". */
const FOLD_AFTER = 4;

/**
 * Share of ad spend: a donut of marketplaces, with each marketplace's campaign
 * types beside it. Types are the marketplace's own words and never merged across
 * marketplaces; all type bars share one scale. One marketplace in view splits the
 * donut by type instead.
 */
export const SpendSplitCard = () => {
	const { data, isLoading, error, refetch } = useBudgetSplit();
	const [compare, setCompare] = useState(false);
	const [open, setOpen] = useState(() => new Set());
	const {
		data: prev,
		isLoading: prevLoading,
		error: prevError,
	} = usePreviousBudgetSplit(compare);
	const prevRange = usePreviousRange();

	const rows = useMemo(
		() => (data ?? []).filter((r) => r.budget_consumed > 0),
		[data],
	);
	const total = rows.reduce((s, r) => s + r.budget_consumed, 0);
	const groups = useMemo(() => {
		const by = new Map();
		for (const r of rows) {
			const g = by.get(r.platform) ?? {
				platform: r.platform,
				spend: 0,
				sales: 0,
				types: [],
			};
			g.spend += r.budget_consumed;
			g.sales += r.ad_sales;
			g.types.push(r);
			by.set(r.platform, g);
		}
		return [...by.values()]
			.map((g) => ({
				...g,
				types: g.types.sort(
					(a, b) => b.budget_consumed - a.budget_consumed,
				),
			}))
			.sort((a, b) => b.spend - a.spend);
	}, [rows]);
	const multi = groups.length > 1;

	// Share of spend in the previous window, by marketplace and by type, for the comparison.
	const prevShare = useMemo(() => {
		const list = (prev ?? []).filter((r) => r.budget_consumed > 0);
		const tot = list.reduce((s, r) => s + r.budget_consumed, 0);
		const out = {};
		for (const r of list) {
			const k = `${r.platform}:${r.campaign_type}`;
			out[k] = (r.budget_consumed / tot) * 100;
			out[r.platform] =
				(out[r.platform] ?? 0) + (r.budget_consumed / tot) * 100;
		}
		return tot ? out : null;
	}, [prev]);

	const option = useMemo(() => {
		const items = multi
			? groups.map((g) => ({
					name: marketplaceName(g.platform),
					value: g.spend,
					itemStyle: { color: chartColor(g.platform) },
				}))
			: (groups[0]?.types ?? []).map((t, i) => ({
					name: enumLabel(t.campaign_type),
					value: t.budget_consumed,
					// Past five types the colours repeat; the tail is one grey.
					itemStyle: {
						color: i < SERIES.length ? SERIES[i] : OTHER_COLOR,
					},
				}));
		return insightsDonutOption(items, {
			total,
			radius: multi ? ["44%", "63%"] : ["50%", "72%"],
			labelsToEdge: true,
			showLabels: multi,
		});
	}, [groups, multi, total]);

	const share = (v) => (total ? (v / total) * 100 : 0);
	const change = (key, now) => {
		if (!compare) return null;
		// An empty cell would read as "no change"; say which it is.
		if (!prevShare)
			return (
				<span className="text-right text-[11px] text-content-subtle">
					{prevLoading ? "…" : prevError ? "error" : "—"}
				</span>
			);
		const was = prevShare[key];
		if (was == null)
			return (
				<span className="text-right text-[11px] text-content-subtle">
					new
				</span>
			);
		const d = now - was;
		return (
			<span
				className={`text-right text-xs tabular-nums ${Math.abs(d) < 0.05 ? "text-content-subtle" : "text-content-muted"}`}
			>
				{d >= 0 ? "▲" : "▼"} {Math.abs(d).toFixed(1)} pts
			</span>
		);
	};
	const rowCls = compare ? ROW_CMP : ROW;

	const typeRow = (t) => (
		<div key={`${t.platform}:${t.campaign_type}`} className={rowCls}>
			<span
				className={`flex min-w-0 items-center gap-2 text-content ${multi ? "pl-4" : ""}`}
			>
				{/* Single-marketplace view splits the donut by type, so the dot
				    is its legend. */}
				{!multi && (
					<span
						aria-hidden="true"
						className="size-2 shrink-0 rounded-full"
						style={{
							background:
								SERIES[groups[0].types.indexOf(t)] ??
								OTHER_COLOR,
						}}
					/>
				)}
				<span className="truncate">{enumLabel(t.campaign_type)}</span>
			</span>
			<span className="text-right tabular-nums">
				{formatCurrency(t.budget_consumed)}
			</span>
			<span className="text-right text-content-subtle tabular-nums">
				{share(t.budget_consumed).toFixed(1)}%
			</span>
			<span className="text-right tabular-nums text-content-muted">
				{roasText(
					t.budget_consumed ? t.ad_sales / t.budget_consumed : null,
				)}
			</span>
			{change(
				`${t.platform}:${t.campaign_type}`,
				share(t.budget_consumed),
			)}
		</div>
	);

	return (
		<Card
			title={
				<span className="inline-flex items-center gap-1.5">
					Spend Distribution
					<InfoTooltip label="The share of ad spend in this window: by marketplace in the donut, and by each marketplace's campaign types beside it. Each marketplace names its types its own way, so types are never merged across marketplaces. Percentages are of spend, not revenue; RoAS says what each part earned." />
				</span>
			}
			actions={
				<button
					type="button"
					aria-expanded={compare}
					onClick={() => setCompare((v) => !v)}
					className="rounded-md border border-border px-2.5 py-1 text-xs font-medium text-content-muted transition-colors hover:border-content-subtle hover:text-content"
				>
					{compare ? "Hide comparison" : "Show comparison"}
				</button>
			}
		>
			{isLoading && <Loading label="Loading…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading && !error && !rows.length && (
				<EmptyState message="No ad spend in this window." />
			)}
			{!isLoading && !error && rows.length > 0 && (
				<div className="grid grid-cols-1 items-center gap-7 lg:grid-cols-[23rem_max-content] lg:justify-start lg:gap-x-40">
					<div>
						<EChart option={option} height={420} />
					</div>
					<div className="min-w-0">
						{compare && (
							<p className="mb-2 text-xs text-content-subtle">
								Change in share of spend against{" "}
								{prevRange.from} to {prevRange.to}, the{" "}
								{prevRange.days} days before.
							</p>
						)}
						<div
							className={`${rowCls} border-border pt-0 text-[11px] font-semibold tracking-[0.08em] text-content-subtle uppercase`}
						>
							<span>
								{multi ? "Marketplace / type" : "Campaign type"}
							</span>
							<span className="text-right">Spend</span>
							<span className="text-right">Share</span>
							<span className="text-right">RoAS</span>
							{compare && (
								<span className="text-right">vs before</span>
							)}
						</div>
						{groups.map((g) => {
							const folded =
								g.types.length > FOLD_AFTER &&
								!open.has(g.platform);
							const shown = folded
								? g.types.slice(0, 3)
								: g.types;
							return (
								<div key={g.platform}>
									{multi && (
										<div
											className={`${rowCls} border-0 pt-3 font-semibold`}
										>
											<span className="flex min-w-0 items-center gap-2">
												<MarketplaceTag
													slug={g.platform}
													compact
												/>
												<span className="truncate">
													{marketplaceName(
														g.platform,
													)}
												</span>
											</span>
											<span className="text-right tabular-nums">
												{formatCurrency(g.spend)}
											</span>
											<span className="text-right tabular-nums">
												{share(g.spend).toFixed(1)}%
											</span>
											<span className="text-right tabular-nums">
												{roasText(
													g.spend
														? g.sales / g.spend
														: null,
												)}
											</span>
											{change(g.platform, share(g.spend))}
										</div>
									)}
									{shown.map(typeRow)}
									{g.types.length > FOLD_AFTER && (
										<button
											type="button"
											onClick={() =>
												setOpen((s) => {
													const n = new Set(s);
													if (n.has(g.platform))
														n.delete(g.platform);
													else n.add(g.platform);
													return n;
												})
											}
											className={`py-1 text-left text-xs text-content-muted hover:text-content hover:underline ${multi ? "pl-4" : ""}`}
										>
											{folded
												? `+ ${g.types.length - 3} more ${marketplaceName(g.platform)} types`
												: "Show fewer"}
										</button>
									)}
								</div>
							);
						})}
					</div>
				</div>
			)}
		</Card>
	);
};
