import { ChevronDown } from "lucide-react";
import { useMarketplaces } from "../context/MarketplaceContext";

/**
 * Global marketplace multi-select for the app shell. Connected marketplaces are
 * checkboxes; unconnected ones show disabled with a "soon" tag. Writes to
 * MarketplaceContext, so pages keyed on the selection refetch on change. Uses a
 * native <details> for the dropdown (no click-outside wiring needed).
 */
export const MarketplacePicker = () => {
	const {
		marketplaces,
		selected,
		allSelected,
		isLoading,
		toggle,
		selectAll,
	} = useMarketplaces();

	const label = isLoading
		? "Loading…"
		: allSelected
			? "All marketplaces"
			: selected.length === 0
				? "No marketplaces"
				: `${selected.length} selected`;

	return (
		<details className="relative">
			<summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-normal text-content">
				<span>{label}</span>
				<ChevronDown
					size={16}
					strokeWidth={1.5}
					aria-hidden="true"
					className="shrink-0 text-content-subtle"
				/>
			</summary>

			<div className="absolute z-10 mt-1 w-56 rounded-md border border-border bg-card p-1 shadow-lg">
				<button
					type="button"
					onClick={selectAll}
					disabled={allSelected}
					className="w-full rounded px-2 py-1.5 text-left text-sm font-medium text-primary hover:bg-muted disabled:opacity-40"
				>
					Select all connected
				</button>
				<div className="my-1 border-t border-border" />
				{marketplaces.map((mp) => {
					const checked = selected.includes(mp.slug);
					return (
						<label
							key={mp.slug}
							className={`flex items-center gap-2 rounded px-2 py-1.5 text-sm ${
								mp.connected
									? "cursor-pointer text-content hover:bg-muted"
									: "cursor-not-allowed text-content-subtle"
							}`}
						>
							<input
								type="checkbox"
								checked={checked}
								disabled={!mp.connected}
								onChange={() => toggle(mp.slug)}
							/>
							<span className="flex items-center gap-1.5">
								{mp.color && (
									<span
										className="inline-block h-2 w-2 rounded-full"
										style={{ backgroundColor: mp.color }}
									/>
								)}
								{mp.name}
							</span>
							{!mp.connected && (
								<span className="ml-auto rounded bg-muted px-1.5 py-0.5 text-xs text-content-subtle">
									soon
								</span>
							)}
						</label>
					);
				})}
			</div>
		</details>
	);
};
