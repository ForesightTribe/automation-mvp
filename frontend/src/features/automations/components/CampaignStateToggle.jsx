import { useState } from "react";

/**
 * The campaign's own on/off, on its own row.
 *
 * ⚠️ It CONFIRMS before acting. This is a live write sitting inside a selection surface: the
 * reader came here to choose a campaign, and a mis-aimed click would stop one that is
 * spending. The confirmation is what makes the control safe enough to keep here at all.
 *
 * ⚠️ `stopPropagation`: the row is the select target, so without it starting a campaign
 * would also choose it. Disabled where the state is unknown rather than guessing a
 * direction, because flipping the wrong way stops something live.
 */
export const CampaignStateToggle = ({ name, status, onActivate }) => {
	const [confirming, setConfirming] = useState(false);
	const live = status === "ACTIVE" || status === "SCHEDULED";
	const known = Boolean(status);
	return (
		<>
			<button
				type="button"
				disabled={!known}
				title={
					!known
						? "Campaign state unknown"
						: live
							? "Stop this campaign now"
							: "Start this campaign now"
				}
				onClick={(e) => {
					e.stopPropagation();
					setConfirming(true);
				}}
				className={`relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-40 ${
					live ? "bg-success" : "bg-border"
				}`}
			>
				<span
					className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-card shadow-sm transition-transform ${
						live ? "translate-x-4" : ""
					}`}
				/>
			</button>
			{confirming && (
				<div
					onClick={(e) => e.stopPropagation()}
					className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-6"
				>
					{/* ⚠️ `whitespace-normal` is load-bearing. This dialog renders inside a table cell
					    that sets `whitespace-nowrap`, and `position: fixed` escapes the cell's layout
					    but NOT its inherited text properties: without it the sentence refuses to wrap
					    and runs out of the box. */}
					<div className="w-full max-w-sm rounded-lg border border-border bg-card p-5 break-words whitespace-normal">
						<p className="font-display text-base font-semibold text-content">
							{live
								? "Stop this campaign?"
								: "Start this campaign?"}
						</p>
						<p className="mt-1.5 text-sm text-content-muted">
							{live
								? `“${name}” is running. Stopping it now halts its spend immediately.`
								: `“${name}” is not running. Starting it now lets it spend immediately.`}
						</p>
						<div className="mt-4 flex justify-end gap-2">
							<button
								type="button"
								onClick={() => setConfirming(false)}
								className="cursor-pointer rounded-md border border-border px-3 py-1.5 text-sm text-content transition-colors hover:bg-muted"
							>
								Cancel
							</button>
							<button
								type="button"
								onClick={() => {
									setConfirming(false);
									onActivate?.(live ? "paused" : "running");
								}}
								className="cursor-pointer rounded-md border border-brand bg-brand px-3 py-1.5 text-sm font-medium text-on-brand transition-colors hover:bg-brand-hover"
							>
								{live ? "Stop campaign" : "Start campaign"}
							</button>
						</div>
					</div>
				</div>
			)}
		</>
	);
};
