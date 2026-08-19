import { Search, X } from "lucide-react";

/**
 * The Scheduled band's toolbar: free-text search plus status pills.
 *
 * Both narrow BOTH groups at once, because the question being asked is usually about a
 * campaign ("what is running on the cola campaign?"), not about a mechanism — and a
 * campaign normally has a budget automation and bid rules at the same time. The counts in
 * each group header stay honest by reading "2 of 5" while a filter is on.
 */
const STATUSES = [
	["", "All"],
	["running", "Running"],
	["scheduled", "Scheduled"],
	["paused", "Paused"],
	["stopped", "Stopped"],
	["ended", "Ended"],
];

export const ScheduledFilters = ({
	query,
	onQuery,
	status,
	onStatus,
	active,
	onClear,
}) => (
	<div className="mb-4 flex flex-col gap-3 border-b border-border pb-4 lg:flex-row lg:items-center">
		<label className="relative min-w-0 sm:w-80">
			<Search className="pointer-events-none absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2 text-content-subtle" />
			<input
				value={query}
				onChange={(e) => onQuery(e.target.value)}
				placeholder="Search campaign, keyword or id…"
				aria-label="Search scheduled automations"
				className="w-full rounded-md border border-border bg-surface py-1.5 pr-8 pl-8 text-sm text-content focus:border-primary focus:outline-none"
			/>
			{query && (
				<button
					type="button"
					onClick={() => onQuery("")}
					aria-label="Clear search"
					className="absolute top-1/2 right-2 -translate-y-1/2 text-content-subtle hover:text-content"
				>
					<X className="h-3.5 w-3.5" />
				</button>
			)}
		</label>

		<div className="flex flex-wrap items-center gap-1 lg:ml-auto">
			{STATUSES.map(([value, label]) => (
				<button
					key={value || "all"}
					type="button"
					onClick={() => onStatus(value)}
					className={`rounded-md px-2 py-0.5 text-xs font-medium transition-colors ${
						status === value
							? "bg-primary-soft text-primary"
							: "text-content-muted hover:text-content"
					}`}
				>
					{label}
				</button>
			))}
			{active && (
				<button
					type="button"
					onClick={onClear}
					className="ml-1 text-xs font-medium text-content-subtle hover:text-danger"
				>
					Clear filters
				</button>
			)}
		</div>
	</div>
);
