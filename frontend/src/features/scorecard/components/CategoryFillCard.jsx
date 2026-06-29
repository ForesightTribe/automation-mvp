import { useMemo } from "react";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { categoryFillOption } from "../../../components/charts/options";
import { formatCompactCurrency, formatNumber } from "../../../lib/format";

const formatPct = (v) =>
	v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`;

/**
 * Per-category fill rate for the selected week, best-first. Fed from the page's
 * `scorecard/weekly` fetch (the `categories` JSON), so it shares loading/error
 * state with the KPI strip rather than fetching again. The best-performing
 * category is surfaced as a chip in the header.
 */
export const CategoryFillCard = ({
	categories = [],
	bestCategory,
	isLoading,
	error,
	refetch,
}) => {
	const sorted = useMemo(
		() =>
			[...categories].sort(
				(a, b) => (b.fill_rate ?? 0) - (a.fill_rate ?? 0),
			),
		[categories],
	);

	const option = useMemo(
		() =>
			categoryFillOption(
				sorted.map((c) => ({
					label: c.proxy_category ?? "—",
					value: c.fill_rate,
				})),
			),
		[sorted],
	);

	const columns = [
		{ key: "proxy_category", label: "Category", render: (r) => r.proxy_category ?? "—" },
		{
			key: "fill_rate",
			label: "Fill rate",
			align: "right",
			render: (r) => formatPct(r.fill_rate),
		},
		{
			key: "weighted_fill_rate_percent",
			label: "Weighted",
			align: "right",
			render: (r) => formatPct(r.weighted_fill_rate_percent),
		},
		{
			key: "potential_loss",
			label: "Potential loss",
			align: "right",
			render: (r) => formatCompactCurrency(r.potential_loss),
		},
		{
			key: "manufacturer_rank",
			label: "Rank",
			align: "right",
			render: (r) => formatNumber(r.manufacturer_rank),
		},
	];

	const bestChip =
		bestCategory?.proxy_category != null ? (
			<span className="rounded-full bg-success/10 px-2.5 py-0.5 text-xs font-medium text-success">
				Best: {bestCategory.proxy_category} ({formatPct(bestCategory.fill_rate)})
			</span>
		) : null;

	return (
		<ChartTableCard
			title="Category fill"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={sorted.length === 0}
			emptyMessage="No category data for this week."
			renderChart={() => (
				<EChart
					option={option}
					height={Math.max(160, sorted.length * 32 + 40)}
				/>
			)}
			columns={columns}
			rows={sorted}
			rowKey={(r) => r.proxy_category}
			extraActions={bestChip}
		/>
	);
};
