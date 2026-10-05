import { useState } from "react";
import { Toggle } from "../../../components/ui/Toggle";
import { useAutomationMarketplace } from "../../../context/MarketplaceContext";
import { holdReason } from "../../../lib/marketplaces";

/**
 * The campaign's own on/off, on its own row.
 *
 * ⚠️ It CONFIRMS before acting. This is a live write sitting inside a selection surface: the
 * reader came here to choose a campaign, and a mis-aimed click would stop one that is
 * spending. The confirmation is what makes the control safe enough to keep here at all.
 *
 * The switch itself is the shared `Toggle`, which also handles the `stopPropagation` this
 * needs: the row is the select target, so without it starting a campaign would also
 * choose it. Disabled where the state is unknown rather than guessing a direction,
 * because flipping the wrong way stops something live.
 */
/**
 * Decided on `state` — what the status MEANS (`running` / `paused` / `held` / `ended` /
 * `draft`, from `CampaignRow.state`) — never on the marketplace's raw word (ZC-E4).
 *
 * The raw words differ per marketplace, and reading them directly got the one case that
 * matters most wrong: a campaign the marketplace HELD (Blinkit ON_HOLD, Zepto
 * DAILY_BUDGET_EXHAUSTED / INSUFFICIENT_WALLET_BALANCE) is still live. Offering Start on it
 * is offering a write the engine refuses (`writes.status_transition_denied`) — and because a
 * refused write still exits cleanly, the row used to report success. Held reads as ON, with
 * Stop available (the engine accepts that) and the reason it is not delivering in the hint.
 *
 * `ended` is final on every marketplace, so it offers nothing. A `state` that is missing or
 * unmapped leaves the control disabled rather than guessing a direction.
 */
const LIVE = new Set(["running", "held"]);
const STARTABLE = new Set(["paused", "draft"]);

export const CampaignStateToggle = ({
	name,
	status,
	state,
	refused = null,
	busy,
	onActivate,
}) => {
	const [confirming, setConfirming] = useState(false);
	const { name: mpName } = useAutomationMarketplace();
	const live = LIVE.has(state);
	const known = live || STARTABLE.has(state) || state === "ended";
	// Only ever about the Start direction: a live campaign — held included — can always be
	// stopped. `refused` (a campaign automations may not touch) blocks both.
	const blocked =
		refused ??
		(state === "ended"
			? `This campaign has ended. ${mpName} treats that as final, so it cannot be started again.`
			: null);
	const held = state === "held" ? holdReason(status, mpName) : null;
	// A start/stop of this campaign is already queued or running. Inert until it settles:
	// the second write would be decided against a state the first is in the middle of
	// changing, and the two would race on a single-slot lane.
	const hint = busy
		? `Already ${busy.status === "pending" ? "queued" : "running"} — waiting for it to finish`
		: !known
			? "Campaign state unknown"
			: blocked
				? blocked
				: held
					? `${held} Stop it now to halt it completely.`
					: live
						? "Stop this campaign now"
						: "Start this campaign now";
	return (
		<>
			{/* ⚠️ The title sits on the WRAPPER, not the switch. A disabled <button> fires no
			    mouse events in most browsers, so a tooltip on the button itself is invisible
			    in exactly the case that most needs explaining — a Start we have turned off.
			    `inline-flex` so the span does not change the cell's layout. */}
			<span className="inline-flex" title={hint}>
				<Toggle
					on={live}
					disabled={!known || Boolean(blocked)}
					aria-label={
						blocked
							? `Cannot start this campaign — ${blocked}`
							: live
								? "Stop this campaign"
								: "Start this campaign"
					}
					title={hint}
					onChange={() => setConfirming(true)}
				/>
			</span>
			{confirming && (
				<div
					onClick={(e) => e.stopPropagation()}
					className="fixed inset-0 z-70 flex items-center justify-center bg-black/40 p-6"
				>
					{/* ⚠️ `whitespace-normal` is load-bearing. This dialog renders inside a table cell
					    that sets `whitespace-nowrap`, and `position: fixed` escapes the cell's layout
					    but NOT its inherited text properties: without it the sentence refuses to wrap
					    and runs out of the box. */}
					<div className="w-full max-w-sm rounded-lg border border-border bg-card p-5 wrap-break-word whitespace-normal">
						<p className="font-display text-base font-semibold text-content">
							{live
								? "Stop this campaign?"
								: "Start this campaign?"}
						</p>
						<p className="mt-1.5 text-sm text-content-muted">
							{live
								? `“${name}” is ${held ? "on hold, but still live" : "running"}. Stopping it now halts its spend immediately.`
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
