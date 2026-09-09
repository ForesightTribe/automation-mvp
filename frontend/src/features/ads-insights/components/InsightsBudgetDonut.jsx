import { useMemo } from "react";
import {
	useBudgetSplit,
	usePreviousBudgetSplit,
	usePreviousRange,
} from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { insightsDonutOption } from "../chartOptions";
import { useState } from "react";
import { InfoTooltip } from "../../../components/ui/InfoTooltip";
import { formatCurrency, formatPercent } from "../../../lib/format";

const formatRoas = (v) => (v == null ? "—" : `${v.toFixed(2)}x`);

/** PRODUCT_LISTING to "Product listing". */
const typeLabel = (t) =>
	t
		? t
				.toLowerCase()
				.replace(/_/g, " ")
				.replace(/^\w/, (c) => c.toUpperCase())
		: "Unknown";

/**
 * Where the spend went, by campaign type. The total sits in the middle because the question
 * a donut answers is "how is this whole divided", and slices are labelled directly so
 * identity never depends on matching a colour to a legend.
 */
export const InsightsBudgetDonut = () => {
	const { data, isLoading, error, refetch } = useBudgetSplit();
	const [compare, setCompare] = useState(false);
	const { data: prev } = usePreviousBudgetSplit(compare);
	const prevRange = usePreviousRange();
	const rows = useMemo(() => data ?? [], [data]);

	// Share is what a donut is for, so the comparison is share-versus-share: a type can take
	// a bigger slice while the account spends less overall, and that is the thing worth
	// seeing. Absolute spend is in the table view.
	const prevTotal = (prev ?? []).reduce((s, r) => s + r.budget_consumed, 0);
	const shareOf = (list, type, tot) => {
		const row = (list ?? []).find((r) => r.campaign_type === type);
		return tot && row ? (row.budget_consumed / tot) * 100 : null;
	};
	const total = useMemo(
		() => rows.reduce((s, r) => s + r.budget_consumed, 0),
		[rows],
	);
	const option = useMemo(
		() =>
			insightsDonutOption(
				[...rows]
					.sort((a, b) => b.budget_consumed - a.budget_consumed)
					.map((r) => ({
						name: typeLabel(r.campaign_type),
						value: r.budget_consumed,
					})),
				{ total },
			),
		[rows, total],
	);

	const columns = [
		{
			key: "campaign_type",
			label: "Type",
			render: (r) => typeLabel(r.campaign_type),
		},
		{
			key: "budget_consumed",
			label: "Spend",
			align: "right",
			render: (r) => formatCurrency(r.budget_consumed),
		},
		{
			key: "share",
			label: "Share",
			align: "right",
			// formatPercent takes a fraction and does the ×100 itself.
			render: (r) =>
				total ? formatPercent(r.budget_consumed / total) : "—",
		},
		{
			key: "ad_sales",
			label: "Revenue",
			align: "right",
			render: (r) => formatCurrency(r.ad_sales),
		},
		{
			key: "roas",
			label: "RoAS",
			align: "right",
			render: (r) => formatRoas(r.roas),
		},
	];

	return (
		<ChartTableCard
			title={
				<span className="inline-flex items-center gap-1.5">
					Where the spend goes
					<InfoTooltip label="The share of ad spend taken by each campaign type in this window. The centre is the total billed. Percentages are of spend, not of revenue, so a large slice says where the money went, not what it earned: the table view carries each type's revenue and RoAS." />
				</span>
			}
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={!rows.length}
			renderChart={() => (
				<div className="flex flex-col gap-3">
					<EChart option={option} height={300} />
					<button
						type="button"
						aria-expanded={compare}
						onClick={() => setCompare((v) => !v)}
						className="flex w-fit items-center gap-1 self-start rounded-md border border-border px-2.5 py-1 text-xs font-medium text-content-muted transition-colors hover:border-content-subtle hover:text-content"
					>
						{compare ? "Hide comparison" : "Show comparison"}
					</button>
					{compare && (
						<div className="rounded-lg border border-border bg-surface p-3">
							<p className="mb-2 text-xs text-content-subtle">
								Share of spend against {prevRange.from} to{" "}
								{prevRange.to}, the {prevRange.days} days before
								this window.
							</p>
							<ul className="space-y-1">
								{[...rows]
									.sort(
										(a, b) =>
											b.budget_consumed -
											a.budget_consumed,
									)
									.map((r) => {
										const now = total
											? (r.budget_consumed / total) * 100
											: null;
										const was = shareOf(
											prev,
											r.campaign_type,
											prevTotal,
										);
										const diff =
											now != null && was != null
												? now - was
												: null;
										return (
											<li
												key={r.campaign_type}
												className="flex justify-between gap-3 text-sm"
											>
												<span className="text-content">
													{typeLabel(r.campaign_type)}
												</span>
												<span className="tabular-nums text-content-muted">
													{now == null
														? "—"
														: `${now.toFixed(1)}%`}
													{diff == null ? (
														<span className="ml-2 text-content-subtle">
															no prior data
														</span>
													) : (
														<span className="ml-2">
															{diff >= 0
																? "▲"
																: "▼"}{" "}
															{Math.abs(
																diff,
															).toFixed(1)}{" "}
															pts
														</span>
													)}
												</span>
											</li>
										);
									})}
							</ul>
						</div>
					)}
				</div>
			)}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.campaign_type}
		/>
	);
};
