import { useAlerts } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";

const SEVERITY_ACCENT = {
	critical: "border-l-danger",
	warning: "border-l-warning",
	info: "border-l-info",
};

/**
 * Attention feed — scrape failures, out-of-stock, and fill-loss signals from
 * /overview/alerts, ordered by severity. An empty list means all clear.
 */
export const AttentionFeed = () => {
	const { data, isLoading, error, refetch } = useAlerts();

	return (
		<Card title="Needs attention">
			{isLoading && <Loading label="Loading alerts…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(data?.length ? (
					<ul className="flex flex-col gap-2">
						{data.map((alert, i) => (
							<li
								key={`${alert.category}-${i}`}
								className={`border-l-2 bg-muted/50 px-3 py-2 ${
									SEVERITY_ACCENT[alert.severity] ??
									"border-l-border"
								}`}
							>
								<p className="text-sm font-medium text-content">
									{alert.title}
								</p>
								{alert.detail && (
									<p className="text-xs text-content-muted">
										{alert.detail}
									</p>
								)}
							</li>
						))}
					</ul>
				) : (
					<EmptyState
						title="All clear"
						message="No alerts right now."
						icon="✓"
					/>
				))}
		</Card>
	);
};
