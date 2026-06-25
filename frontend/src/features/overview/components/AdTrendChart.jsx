import { useMemo } from "react";
import { useTrends } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { EChart } from "../../../components/charts/EChart";
import { spendRevenueOption } from "../../../components/charts/options";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";

/** Ad Spend vs Ad Revenue over the selected window — the return-on-spend story. */
export const AdTrendChart = () => {
	const { data, isLoading, error, refetch } = useTrends();
	const option = useMemo(() => spendRevenueOption(data ?? []), [data]);
	const hasData = (data ?? []).some(
		(r) => r.ad_spend != null || r.ad_sales != null,
	);

	return (
		<Card title="Ad spend vs ad revenue">
			{isLoading && <Loading label="Loading trend…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(hasData ? (
					<EChart option={option} height={300} />
				) : (
					<EmptyState message="No ad data in this window." />
				))}
		</Card>
	);
};
