import { marketplaceName } from "../../../lib/marketplace";
import { MarketplaceMark } from "../../../components/ui/MarketplaceMark";

const ALL = "all";

/**
 * Scope for a trend: everything together, or one channel on its own.
 *
 * A single choice, not a multi-select — the sum of an arbitrary subset is a
 * number with no name. One row of chips directly under the card's title, so it
 * reads as "which of these am I looking at" before the chart below it.
 */
export const MarketplaceLines = ({ slugs, value, onSelect }) => (
	<div
		role="group"
		aria-label="Channel"
		className="flex flex-wrap items-center gap-1.5"
	>
		{[ALL, ...slugs].map((slug) => {
			const isAll = slug === ALL;
			const on = value === slug;
			return (
				<button
					key={slug}
					type="button"
					onClick={() => onSelect(slug)}
					aria-pressed={on}
					className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors ${
						on
							? "border-brand bg-brand text-on-brand"
							: "border-border bg-card text-content-muted hover:border-content-subtle hover:text-content"
					}`}
				>
					{!isAll && (
						<MarketplaceMark
							marketplace={{ slug, name: marketplaceName(slug) }}
							size={13}
						/>
					)}
					{isAll ? "All channels" : marketplaceName(slug)}
				</button>
			);
		})}
	</div>
);
