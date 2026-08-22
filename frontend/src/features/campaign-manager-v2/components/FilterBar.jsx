import { Search, X } from "lucide-react";

/**
 * One search-and-status toolbar, shared by the Campaigns and Scheduled bands.
 *
 * Shared deliberately: this page previously offered three different ways to find a
 * campaign (a picker dropdown, a segmented filter, a search box), each styled its own
 * way. One bar means "find the cola campaign" is the same gesture wherever you are.
 *
 * `options` is a list of [value, label]; the empty-string value is the "no filter" pill.
 * `extra` hangs an owner-specific control (the campaign band's Refresh) off the end.
 */
export const FilterBar = ({
	query,
	onQuery,
	placeholder,
	options,
	value,
	onValue,
	active,
	onClear,
	extra,
}) => (
	<div className="mb-4 flex flex-col gap-3 border-b border-border pb-4 lg:flex-row lg:items-center">
		<label className="relative min-w-0 sm:w-80">
			<Search className="pointer-events-none absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2 text-content-subtle" />
			<input
				value={query}
				onChange={(e) => onQuery(e.target.value)}
				placeholder={placeholder}
				aria-label={placeholder}
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
			{options.map(([optValue, label]) => (
				<button
					key={optValue || "all"}
					type="button"
					onClick={() => onValue(optValue)}
					className={`rounded-md px-2 py-0.5 text-xs font-medium transition-colors ${
						value === optValue
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
			{extra}
		</div>
	</div>
);
