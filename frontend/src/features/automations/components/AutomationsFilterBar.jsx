export const TYPE_OPTIONS = [
	{ value: "", label: "All" },
	{ value: "campaign", label: "Campaigns" },
	{ value: "keyword", label: "Keywords" },
];

const STATUS_OPTIONS = [
	{ value: "", label: "All statuses" },
	{ value: "running", label: "Active" },
	{ value: "scheduled", label: "Scheduled" },
	{ value: "paused", label: "Paused" },
	{ value: "stopped", label: "Stopped" },
	{ value: "ended", label: "Ended" },
];

/** Underlined type tabs plus a status dropdown for narrowing further.
 *
 * ⚠️ No channel pills any more (ZC-E1). The marketplace is the NAVBAR's choice on this page,
 * one at a time, and the list is already scoped to it — a second, local marketplace filter
 * could only disagree with the first. Selected states use neutral ink, not a colour fill:
 * colour here is reserved for real status (success/warning/danger). */
export const AutomationsFilterBar = ({
	type,
	onType,
	status,
	onStatus,
	counts = {},
}) => (
	<div className="flex flex-col gap-3">
		<div className="flex flex-wrap items-center justify-between gap-3 border-b border-border">
			<div className="flex gap-5">
				{TYPE_OPTIONS.map((o) => (
					<button
						key={o.value}
						type="button"
						onClick={() => onType(o.value)}
						className={`-mb-px border-b-2 pb-2 text-sm font-medium transition-colors ${
							type === o.value
								? "border-content text-content"
								: "border-transparent text-content-muted hover:text-content"
						}`}
					>
						{o.label}
						{/* The count rides on the tab it filters by, so the number is a reason to
						    click rather than a statistic to read. */}
						{counts[o.value] != null && (
							<span className="ml-1.5 text-xs tabular-nums text-content-subtle">
								{counts[o.value]}
							</span>
						)}
					</button>
				))}
			</div>
			<select
				value={status}
				onChange={(e) => onStatus(e.target.value)}
				className="mb-2 rounded-md border border-border bg-card px-2.5 py-1 text-sm text-content focus:outline-none focus:ring-2 focus:ring-content-subtle/40"
			>
				{STATUS_OPTIONS.map((o) => (
					<option key={o.value} value={o.value}>
						{o.label}
					</option>
				))}
			</select>
		</div>
	</div>
);
