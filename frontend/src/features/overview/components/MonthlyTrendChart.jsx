import { useMemo } from "react";
import { useMonthlyTrends } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { EChart } from "../../../components/charts/EChart";
import { monthlySeriesOption } from "../../../components/charts/options";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";

/**
 * One month-on-month Operations chart (OSA / fill rate / PO value). All three
 * share the `useMonthlyTrends` query (deduped); each picks its metric via
 * `seriesKey` and styling via the option config.
 */
export const MonthlyTrendChart = ({
	title,
	seriesKey,
	label,
	color,
	type = "line",
	kind = "currency",
	// All three metrics come from Blinkit seller tables. `emptyMessage` lets the
	// caller say so when the selected marketplace has no such source, instead of
	// "No data yet", which implies a scrape is merely pending.
	emptyMessage = "No data yet.",
}) => {
	const { data, isLoading, error, refetch } = useMonthlyTrends();
	const option = useMemo(
		() =>
			monthlySeriesOption(data ?? [], {
				key: seriesKey,
				label,
				color,
				type,
				kind,
			}),
		[data, seriesKey, label, color, type, kind],
	);
	const hasData = (data ?? []).some((r) => r[seriesKey] != null);

	return (
		<Card title={title}>
			{isLoading && <Loading label="Loading…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(hasData ? (
					<EChart option={option} height={220} />
				) : (
					<EmptyState message={emptyMessage} />
				))}
		</Card>
	);
};
