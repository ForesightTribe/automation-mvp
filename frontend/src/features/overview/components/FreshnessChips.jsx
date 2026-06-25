import { useFreshness } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";

/** "2h ago" / "3d ago" from an age in hours (null -> "never"). */
const humanizeAge = (hours) => {
	if (hours === null || hours === undefined) return "never";
	if (hours < 1) return "just now";
	if (hours < 24) return `${Math.round(hours)}h ago`;
	return `${Math.round(hours / 24)}d ago`;
};

const STATUS_TONE = {
	success: "bg-success-soft text-success",
	failed: "bg-danger-soft text-danger",
	running: "bg-info-soft text-info",
	pending: "bg-warning-soft text-warning",
};

/**
 * Per-dashboard sync freshness. One chip per scrape dashboard showing its last
 * run's status + age, so stale or failed feeds are obvious at a glance.
 */
export const FreshnessChips = () => {
	const { data, isLoading, error, refetch } = useFreshness();

	return (
		<Card title="Data freshness">
			{isLoading && <Loading label="Loading sync status…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(data?.length ? (
					<div className="flex flex-wrap gap-2">
						{data.map((chip) => (
							<span
								key={`${chip.platform}-${chip.dashboard}`}
								className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
									STATUS_TONE[chip.status] ??
									"bg-muted text-content-muted"
								}`}
							>
								<span className="font-semibold">
									{chip.dashboard}
								</span>
								<span className="opacity-80">
									{humanizeAge(chip.age_hours)}
								</span>
							</span>
						))}
					</div>
				) : (
					<EmptyState message="No scrape history yet." />
				))}
		</Card>
	);
};
