import { useMemo } from "react";
import { useTrends } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { EChart } from "../../../components/charts/EChart";
import { revenueOption } from "../../../components/charts/options";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";

/** Total store revenue per day over the selected window. */
export const SalesTrendChart = () => {
	const { data, isLoading, error, refetch } = useTrends();
	const option = useMemo(() => revenueOption(data ?? []), [data]);
	const hasData = (data ?? []).some((r) => r.revenue != null);

	return (
		<Card title="Total revenue">
			{isLoading && <Loading label="Loading trend…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(hasData ? (
					<EChart option={option} height={300} />
				) : (
					<EmptyState message="No sales in this window." />
				))}
		</Card>
	);
};
