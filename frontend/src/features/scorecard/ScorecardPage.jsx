import { useState } from "react";
import { useMarketplaces } from "../../context/MarketplaceContext";
import { useScorecardWeeks, useScorecardWeekly } from "./hooks";
import { WeekPicker } from "./components/WeekPicker";
import { KpiStrip } from "./components/KpiStrip";
import { FillTrendChart } from "./components/FillTrendChart";
import { CategoryFillCard } from "./components/CategoryFillCard";
import { KeySkusCard } from "./components/KeySkusCard";
import { FacilitiesCard } from "./components/FacilitiesCard";
import { Loading } from "../../components/feedback/Loading";
import { ErrorState } from "../../components/feedback/ErrorState";
import { EmptyState } from "../../components/feedback/EmptyState";

/**
 * Scorecard — a marketplace's view of brand health. Composition root. Scorecard
 * data is weekly snapshots, so the page navigates by week (the global date picker
 * is ignored here). The selected week is page-local state that defaults to the
 * latest available and re-keys every child fetch when changed.
 *
 * There's no blended scorecard across marketplaces (the backend always answers
 * with exactly one platform), so the navbar's marketplace pills control WHICH
 * one: narrow to a single marketplace there to see it explicitly, or leave
 * "All"/multiple selected to get the backend's own auto-detect (Blinkit if it
 * publishes a scorecard for this tenant, else Zepto — Instamart is never
 * auto-detected, only reachable by picking it explicitly).
 */
export const ScorecardPage = () => {
	const { data: weeks, isLoading: weeksLoading, error: weeksError } =
		useScorecardWeeks();
	const [picked, setPicked] = useState(null);
	const selectedWeek = picked ?? weeks?.[0] ?? null;

	// There's no blended scorecard — the backend always answers with exactly
	// one platform (auto-detected, or explicit when the navbar pills narrow to
	// one marketplace — see hooks.js's useScorecardMarketplace). Naming it here
	// only when the picker itself is explicit avoids claiming to know which
	// platform "All"/auto-detect actually resolved to.
	const { marketplaces, selected, allSelected } = useMarketplaces();
	const explicitMp =
		!allSelected && selected.length === 1
			? marketplaces.find((m) => m.slug === selected[0])
			: null;
	const subtitle = explicitMp
		? `${explicitMp.name}'s view of my brand health.`
		: "Your view of brand health.";

	const {
		data: weekly,
		isLoading,
		error,
		refetch,
	} = useScorecardWeekly(selectedWeek);

	return (
		<div className="flex flex-col gap-6">
			<div className="flex flex-wrap items-start justify-between gap-3">
				<div>
					<h1 className="font-display text-xl font-bold text-content">
						Scorecard
					</h1>
					<p className="text-sm text-content-muted">{subtitle}</p>
				</div>
				<WeekPicker
					weeks={weeks ?? []}
					value={selectedWeek}
					onChange={setPicked}
				/>
			</div>

			{weeksLoading && <Loading label="Loading scorecard…" />}
			{weeksError && (
				<ErrorState message={weeksError.message} />
			)}
			{!weeksLoading && !weeksError && (weeks?.length ?? 0) === 0 && (
				<EmptyState message="No scorecard data yet for this client." />
			)}

			{!weeksLoading && !weeksError && (weeks?.length ?? 0) > 0 && (
				<>
					{isLoading && <Loading label="Loading week…" />}
					{error && (
						<ErrorState message={error.message} onRetry={refetch} />
					)}
					{!isLoading && !error && weekly && (
						<KpiStrip metrics={weekly.metrics} />
					)}

					<FillTrendChart />

					<CategoryFillCard
						categories={weekly?.categories ?? []}
						bestCategory={weekly?.best_category}
						isLoading={isLoading}
						error={error}
						refetch={refetch}
					/>

					<div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
						<KeySkusCard from={selectedWeek} />
						<FacilitiesCard from={selectedWeek} />
					</div>
				</>
			)}
		</div>
	);
};
