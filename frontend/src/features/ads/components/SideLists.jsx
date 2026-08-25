import { useVisibilityPlans, useCollections } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCurrency, formatNumber } from "../../../lib/format";

/** Visibility/placement plans — name, type, budget, status. */
export const VisibilityPlans = () => {
	const { data, isLoading, error, refetch } = useVisibilityPlans();
	const rows = data ?? [];

	return (
		<Card title="Visibility plans">
			{isLoading && <Loading label="Loading plans…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(rows.length === 0 ? (
					<EmptyState message="No visibility plans." />
				) : (
					<ul className="flex flex-col divide-y divide-border/60">
						{rows.map((p) => (
							<li
								key={p.plan_id}
								className="flex items-center justify-between gap-3 py-2"
							>
								<div className="min-w-0">
									<div className="truncate text-sm font-medium text-content">
										{p.name || `Plan #${p.plan_id}`}
									</div>
									<div className="text-xs text-content-subtle">
										{p.type || "—"}
										{p.status ? ` · ${p.status}` : ""}
									</div>
								</div>
								<span className="shrink-0 text-sm font-semibold tabular-nums text-content">
									{formatCurrency(p.budget)}
								</span>
							</li>
						))}
					</ul>
				))}
		</Card>
	);
};

/** Curated brand collections — name + product count. */
export const Collections = () => {
	const { data, isLoading, error, refetch } = useCollections();
	const rows = data ?? [];

	return (
		<Card title="Brand collections">
			{isLoading && <Loading label="Loading collections…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(rows.length === 0 ? (
					<EmptyState message="No collections." />
				) : (
					<ul className="flex flex-col divide-y divide-border/60">
						{rows.map((c) => (
							<li
								key={c.collection_id}
								className="flex items-center justify-between gap-3 py-2"
							>
								<div className="min-w-0">
									<div className="truncate text-sm font-medium text-content">
										{c.name ||
											`Collection #${c.collection_id}`}
									</div>
									{c.is_dynamic && (
										<div className="text-xs text-content-subtle">
											Dynamic
										</div>
									)}
								</div>
								<span className="shrink-0 text-sm font-semibold tabular-nums text-content">
									{formatNumber(c.number_of_products)} SKUs
								</span>
							</li>
						))}
					</ul>
				))}
		</Card>
	);
};
