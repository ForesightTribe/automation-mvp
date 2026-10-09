import { MarketplaceMark } from "./MarketplaceMark";
import { marketplaceName } from "../../lib/marketplace";

/**
 * Channel picker: one row of chips, one channel at a time.
 *
 * The shared shape used by every card that scopes to a marketplace, so the
 * control looks and behaves the same wherever it appears. `allLabel` adds a
 * leading "everything" chip; omit it where a card must always be on exactly
 * one channel.
 */
export const ChannelChips = ({ slugs, value, onSelect, allLabel = null }) => {
	if (!slugs?.length) return null;
	const chip = (active) =>
		`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors ${
			active
				? "border-brand bg-brand text-on-brand"
				: "border-border bg-card text-content-muted hover:border-content-subtle hover:text-content"
		}`;

	return (
		<div role="group" aria-label="Channel" className="flex flex-wrap items-center gap-1.5">
			{allLabel && (
				<button
					type="button"
					onClick={() => onSelect(null)}
					aria-pressed={value == null}
					className={chip(value == null)}
				>
					{allLabel}
				</button>
			)}
			{slugs.map((slug) => (
				<button
					key={slug}
					type="button"
					onClick={() => onSelect(slug)}
					aria-pressed={value === slug}
					className={chip(value === slug)}
				>
					<MarketplaceMark
						marketplace={{ slug, name: marketplaceName(slug) }}
						size={13}
					/>
					{marketplaceName(slug)}
				</button>
			))}
		</div>
	);
};
