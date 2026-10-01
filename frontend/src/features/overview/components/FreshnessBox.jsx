import { useFreshness } from "../hooks";
import { HoverHint } from "../../../components/ui/HoverHint";

/**
 * How current the page's data is: a small marker, with the per-feed detail on
 * hover rather than spread across the header.
 *
 * Each feed is judged against ITS OWN cadence. The public scrapes run weekly, so
 * five days old is on schedule, not stale — a single "older than a day" rule
 * would flag them every day of the week and teach the reader to ignore it.
 */
const FEEDS = {
	blinkit_seller_sales: { label: "Sales", everyHours: 24 },
	blinkit_seller_soh: { label: "Inventory", everyHours: 24 },
	blinkit_seller_po: { label: "Purchase orders", everyHours: 24 },
	blinkit_marketing: { label: "Ads", everyHours: 24 },
	blinkit_seller_scorecard: { label: "Scorecard", everyHours: 24 * 7 },
	public_search: { label: "Search visibility", everyHours: 24 * 7 },
	public_skus: { label: "Shelf availability", everyHours: 24 * 7 },
};

// A feed is behind once it is half a cycle past due, not the moment it is due:
// scrapes drift by an hour without anything being wrong.
const OVERDUE_FACTOR = 1.5;

const age = (hours) => {
	if (hours === null || hours === undefined) return "never run";
	if (hours < 1) return "just now";
	if (hours < 24) return `${Math.round(hours)}h ago`;
	const days = Math.round(hours / 24);
	return days === 1 ? "yesterday" : `${days} days ago`;
};

const describe = (chip) => {
	const feed = FEEDS[chip.dashboard];
	const label = feed?.label ?? chip.dashboard;
	const expected = feed?.everyHours ?? 24;
	const behind =
		chip.status === "failed" ||
		(chip.age_hours ?? 0) > expected * OVERDUE_FACTOR;
	return { label, behind, weekly: expected > 24 };
};

export const FreshnessBox = () => {
	const { data } = useFreshness();
	const chips = data ?? [];
	if (!chips.length) return null;

	const rows = chips.map((c) => ({ ...c, ...describe(c) }));
	const behind = rows.filter((r) => r.behind);
	// The headline figures come from the daily feeds, so the summary tracks those.
	const daily = rows.filter((r) => !r.weekly && r.age_hours != null);
	const newest = daily.length
		? Math.min(...daily.map((r) => r.age_hours))
		: null;

	return (
		<HoverHint
			placement="bottom"
			width={280}
			label={
				<span className="flex flex-col gap-1">
					{rows.map((r) => (
						<span
							key={r.dashboard}
							className="flex justify-between gap-4"
						>
							<span>
								{r.label}
								{r.weekly ? " (weekly)" : ""}
							</span>
							<span className={r.behind ? "text-warning" : ""}>
								{r.status === "running"
									? "running now"
									: age(r.age_hours)}
							</span>
						</span>
					))}
				</span>
			}
		>
			<button
				type="button"
				aria-label="Data freshness by source"
				className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-xs text-content-muted transition-colors hover:text-content"
			>
				<span
					aria-hidden
					className={`h-1.5 w-1.5 rounded-full ${
						behind.length ? "bg-warning" : "bg-success"
					}`}
				/>
				{behind.length
					? `${behind.length} feed${behind.length > 1 ? "s" : ""} behind`
					: `Data ${age(newest)}`}
			</button>
		</HoverHint>
	);
};
