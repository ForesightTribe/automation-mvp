import { ChevronRight, X } from "lucide-react";

/**
 * One line in the attention rail: a category dot and what it is. The figures
 * live in the panel the row opens, so the rail stays a list of things to look
 * at rather than a second set of numbers competing with the ones on the page.
 *
 * Colour is never the only signal: the category is in the drawer's heading and
 * the impact wording, so the dot is reinforcement rather than the message.
 */
const DOT = {
	revenue_risk: "bg-danger",
	warning: "bg-warning",
	opportunity: "bg-success",
	activity: "bg-info",
};

export const categoryOf = (insight) => {
	if (insight.type === "opportunity" || insight.type === "win")
		return "opportunity";
	// Something the system did rather than something wrong. It earns a place in
	// the rail because it is worth knowing what moved overnight, but an amber
	// dot would read as a problem where there is none.
	if (insight.type === "change") return "activity";
	const money = insight.impact?.unit === "INR" && insight.impact?.value;
	return money ? "revenue_risk" : "warning";
};

export const AttentionRow = ({ insight, onOpen, onDismiss }) => {
	const category = categoryOf(insight);

	return (
		// The dismiss control is a SIBLING of the open control, not nested in it:
		// a button inside a button is invalid, and the two do different things.
		<li className="group/row flex items-start">
			<button
				type="button"
				onClick={() => onOpen(insight)}
				className="flex min-w-0 flex-1 items-start gap-2.5 rounded-lg px-2 py-2.5 text-left transition-colors hover:bg-muted"
			>
				<span
					aria-hidden
					className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${DOT[category]}`}
				/>
				<span className="min-w-0 flex-1 text-sm leading-snug text-content">
					{insight.title}
				</span>
				<ChevronRight
					size={14}
					aria-hidden
					className="mt-0.5 shrink-0 text-content-subtle"
				/>
			</button>

			{onDismiss && (
				<button
					type="button"
					onClick={() => onDismiss(insight)}
					aria-label={`Dismiss: ${insight.title}`}
					title="Dismiss"
					className="mt-1.5 shrink-0 rounded p-1 text-content-subtle/60 transition-colors hover:bg-muted hover:text-content"
				>
					<X size={13} aria-hidden />
				</button>
			)}
		</li>
	);
};
