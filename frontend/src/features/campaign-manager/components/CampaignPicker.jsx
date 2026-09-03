import { useEffect, useMemo, useRef, useState } from "react";
import { useCampaigns } from "../hooks";

const FIELD =
	"w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-content focus:border-primary focus:outline-none";

/**
 * Searchable campaign selector — the end-user picks by name, not by memorising ids.
 * Types to filter the account's campaigns (name or id); the chosen row reports both
 * `campaign_id` and `campaign_name` up.
 *
 * Only campaigns from the latest catalogue sync are offered, and **a typed id that isn't
 * among them is refused** rather than accepted as a raw id. That escape hatch existed so a
 * just-created campaign was never a dead end, but it also let a dead account's campaign id
 * be pasted straight back in from an old sheet — which is the exact accident the freshness
 * filter is here to prevent, and an automation pointed at an unwritable campaign fails
 * silently every run. Refreshing the campaign list is now the answer for a new campaign.
 */
export const CampaignPicker = ({ value, name, onChange, placeholder = "Search campaigns…" }) => {
	const { data: campaigns = [], isLoading } = useCampaigns();
	const [query, setQuery] = useState("");
	const [open, setOpen] = useState(false);
	const boxRef = useRef(null);

	useEffect(() => {
		const onDown = (e) => {
			if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
		};
		document.addEventListener("mousedown", onDown);
		return () => document.removeEventListener("mousedown", onDown);
	}, []);

	const matches = useMemo(() => {
		const q = query.trim().toLowerCase();
		const rows = campaigns.filter((c) => {
			if (!q) return true;
			return (c.name || "").toLowerCase().includes(q) || String(c.campaign_id).includes(q);
		});
		return rows.slice(0, 40);
	}, [campaigns, query]);

	const numericId = /^\d+$/.test(query.trim()) ? Number(query.trim()) : null;
	const unknownId =
		numericId && !campaigns.some((c) => c.campaign_id === numericId) ? numericId : null;

	const pick = (id, label) => {
		onChange(id, label);
		setQuery("");
		setOpen(false);
	};

	if (value) {
		return (
			<div className="flex items-center gap-2 rounded-md border border-border bg-surface px-2.5 py-1.5">
				<span className="min-w-0 flex-1 truncate text-sm text-content">
					{name || `campaign ${value}`}
					<span className="ml-1.5 text-xs text-content-subtle">#{value}</span>
				</span>
				<button
					type="button"
					onClick={() => onChange("", "")}
					className="text-content-subtle hover:text-danger"
					aria-label="Clear campaign"
				>
					✕
				</button>
			</div>
		);
	}

	return (
		<div ref={boxRef} className="relative">
			<input
				className={FIELD}
				value={query}
				onChange={(e) => setQuery(e.target.value)}
				onFocus={() => setOpen(true)}
				placeholder={placeholder}
			/>
			{open && (
				<ul className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-border bg-card shadow-lg">
					{isLoading && (
						<li className="px-3 py-2 text-xs text-content-subtle">Loading campaigns…</li>
					)}
					{!isLoading && matches.length === 0 && !unknownId && (
						<li className="px-3 py-2 text-xs text-content-subtle">No campaigns found.</li>
					)}
					{matches.map((c) => (
						<li key={c.campaign_id}>
							<button
								type="button"
								onClick={() => pick(c.campaign_id, c.name || `campaign ${c.campaign_id}`)}
								className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
							>
								<span className="min-w-0 truncate text-content">
									{c.name || `campaign ${c.campaign_id}`}
								</span>
								<span className="shrink-0 text-xs text-content-subtle">
									#{c.campaign_id}
									{c.status ? ` · ${c.status}` : ""}
								</span>
							</button>
						</li>
					))}
					{unknownId && (
						<li className="px-3 py-2 text-xs text-content-muted">
							<span className="font-medium text-content">#{unknownId}</span> isn't on
							this account's current campaign list. If you just created it, refresh the
							list from <span className="font-medium">Start or stop a campaign</span>.
						</li>
					)}
				</ul>
			)}
		</div>
	);
};
