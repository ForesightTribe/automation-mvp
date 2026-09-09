import { Pencil } from "lucide-react";
import { formatCurrency } from "../../../lib/format";

/**
 * What step 1 decided, carried into the steps that follow.
 *
 * Judging a budget window on step 2 takes three things decided on step 1: which campaign it
 * applies to, what that campaign runs at by default, and when the automation is allowed to
 * act. The recap carries them forward so the numbers being typed can be read against them.
 *
 * Read-only by design: it restates, it does not edit. "Change" returns to step 1, which is
 * the one place those fields are set, so there is never a second way to set the same thing.
 */
const Field = ({ label, value, hint }) => (
	<div className="min-w-0">
		<p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-content-subtle">
			{label}
		</p>
		<p
			className="truncate text-sm font-medium text-content"
			title={typeof value === "string" ? value : undefined}
		>
			{value}
		</p>
		{hint && <p className="text-[11px] text-content-subtle">{hint}</p>}
	</div>
);

const dateText = (iso) =>
	iso
		? new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", {
				day: "numeric",
				month: "short",
				year: "numeric",
			})
		: null;

export const WizardContext = ({
	kind,
	campaignLabel,
	campaignId,
	keyword,
	matchType,
	name,
	defaultBudget,
	timing,
	onceDate,
	onChange,
}) => {
	const from = dateText(timing?.start_date);
	const to = dateText(timing?.end_date);
	// A one-off window carries its date on the RULE, not on the automation, so an automation
	// made of a single dated window has no start_date. Its day comes from `onceDate`, which
	// is why that is read in preference to the range.
	const once = onceDate ? `${dateText(onceDate)} only` : null;
	const runs = from
		? to
			? `${from} to ${to}`
			: `${from} onwards`
		: to
			? `until ${to}`
			: (once ?? "Not set");

	return (
		<div className="flex items-start justify-between gap-4 rounded-lg border border-border bg-muted/40 px-4 py-3">
			<div className="grid min-w-0 flex-1 grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3 lg:grid-cols-4">
				<Field
					label="Campaign"
					value={campaignLabel || "Not selected"}
					hint={campaignId ? `ID ${campaignId}` : null}
				/>
				{kind === "keyword" ? (
					<Field
						label="Keyword"
						value={keyword ? `“${keyword}”` : "Not selected"}
						hint={matchType}
					/>
				) : (
					<Field
						label="Default daily budget"
						value={
							defaultBudget
								? formatCurrency(Number(defaultBudget))
								: "Not set"
						}
						hint="Outside every window"
					/>
				)}
				{kind === "campaign" && (
					<Field label="Automation name" value={name || "Untitled"} />
				)}
				<Field
					label="Runs"
					value={runs}
					hint={
						once
							? "Once, no repeat"
							: timing?.end_date
								? null
								: from
									? "No end date"
									: null
					}
				/>
			</div>
			{onChange && (
				<button
					type="button"
					onClick={onChange}
					className="flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-content-muted transition-colors hover:bg-muted hover:text-brand"
				>
					<Pencil size={13} />
					Change
				</button>
			)}
		</div>
	);
};
