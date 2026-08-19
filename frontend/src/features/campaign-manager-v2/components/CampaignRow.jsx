import { Button } from "../../../components/ui/Button";
import { formatCurrency } from "../../../lib/format";
import { Fact, Identity, RowShell } from "./ScheduleRowParts";

const FIELD =
	"rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-content focus:border-primary focus:outline-none";

// The knob is anchored with an explicit `left`: an absolutely-positioned element with no
// horizontal anchor falls back to its *static* position, which is whatever the button's
// own box happens to give it — so it rendered off-centre. Anchor first, then translate.
const Toggle = ({ on, disabled, onClick, label }) => (
	<button
		type="button"
		role="switch"
		aria-checked={on}
		aria-label={label}
		disabled={disabled}
		onClick={onClick}
		className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-0 p-0 transition-colors ${
			on ? "bg-success" : "bg-content-subtle"
		} ${disabled ? "cursor-not-allowed opacity-40" : "cursor-pointer hover:opacity-80"}`}
	>
		<span
			className={`pointer-events-none absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-card shadow-sm ring-1 ring-black/10 transition-transform ${
				on ? "translate-x-4" : "translate-x-0"
			}`}
		/>
	</button>
);

/**
 * One campaign: its live status, what it spends a day, what automation is attached to it,
 * and the two things you can do to it right now — flip it on/off, or push a new budget.
 *
 * The automation facts are the reason this band exists rather than a bare toggle list:
 * "is this campaign automated, and by what?" was previously answerable only by reading
 * the Scheduled band and matching campaign names by eye.
 *
 * `panel` is "start" | "budget" | null — the row expands into a confirm step for both,
 * because each writes a real number to a live campaign.
 */
export const CampaignRow = ({
	campaign,
	state,
	schedule,
	bidCount,
	busy,
	panel,
	budget,
	onBudget,
	onToggle,
	onOpenBudget,
	onClosePanel,
	onStart,
	onSetBudget,
	pending,
}) => {
	const name = campaign.name || `campaign ${campaign.campaign_id}`;
	const blocked = state.blocked ?? null;
	const noStart = state.noStart ?? null;
	// A row is toggleable unless the state forbids it outright, or forbids the only
	// direction the switch could move it.
	const locked = Boolean(blocked) || (!state.on && Boolean(noStart));

	return (
		<RowShell
			header={
				<>
					<Identity
						className="lg:col-span-4"
						badge={
							<span
								className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${state.tone}`}
							>
								{state.label}
							</span>
						}
						title={name}
						subtitle={`#${campaign.campaign_id}${pending ? " · applying…" : ""}`}
					/>
					<span className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:contents">
						<Fact
							className="lg:col-span-2"
							label="Daily budget"
							value={
								campaign.daily_budget != null
									? formatCurrency(campaign.daily_budget)
									: "—"
							}
							hint="at the last sync"
						/>
						<Fact
							className="lg:col-span-2"
							label="Budget schedule"
							value={
								schedule
									? `${formatCurrency(schedule.default_budget)} default`
									: "None"
							}
							hint={
								schedule
									? `${schedule.rules.length} window${schedule.rules.length === 1 ? "" : "s"}`
									: "not automated"
							}
						/>
						<Fact
							className="lg:col-span-1"
							label="Bid rules"
							value={bidCount || "None"}
							hint={bidCount ? "keywords" : "not automated"}
						/>
					</span>
				</>
			}
			actions={
				<>
					<Button
						size="sm"
						variant="ghost"
						disabled={busy}
						onClick={onOpenBudget}
					>
						Set budget
					</Button>
					<Toggle
						on={state.on}
						disabled={busy || locked}
						onClick={onToggle}
						label={`${state.on ? "Stop" : "Start"} ${name}`}
					/>
				</>
			}
		>
			{(blocked || noStart || panel) && (
				<>
					{(blocked || noStart) && (
						<p className="text-xs text-warning">
							{blocked ?? noStart}
						</p>
					)}

					{panel === "start" && (
						<div className={blocked || noStart ? "mt-3" : ""}>
							<p className="text-sm font-medium text-content">
								Start {name}?
							</p>
							<p className="mt-1 text-xs text-content-muted">
								Blinkit restarts a campaign by re-submitting it,
								so its budget is set as part of starting it. Its
								keywords, bids and products are carried over
								unchanged.
							</p>
							<div className="mt-3 flex flex-wrap items-end gap-3">
								<label className="flex flex-col gap-1">
									<span className="text-xs font-medium text-content-muted">
										Daily budget (₹)
									</span>
									<input
										type="number"
										min="1"
										value={budget}
										onChange={(e) =>
											onBudget(e.target.value)
										}
										placeholder="current"
										className={`${FIELD} w-32`}
									/>
								</label>
								<Button disabled={busy} onClick={onStart}>
									Start campaign
								</Button>
								<Button variant="ghost" onClick={onClosePanel}>
									Cancel
								</Button>
								<p className="text-xs text-content-subtle">
									Leave blank to keep the budget it was last
									running at.
								</p>
							</div>
						</div>
					)}

					{panel === "budget" && (
						<div className={blocked || noStart ? "mt-3" : ""}>
							<p className="text-sm font-medium text-content">
								Set {name}'s daily budget
							</p>
							<p className="mt-1 text-xs text-content-muted">
								A one-off push, applied now. A budget schedule
								on this campaign will overwrite it at its next
								run.
							</p>
							<div className="mt-3 flex flex-wrap items-end gap-3">
								<label className="flex flex-col gap-1">
									<span className="text-xs font-medium text-content-muted">
										Daily budget (₹)
									</span>
									<input
										type="number"
										min="1"
										value={budget}
										onChange={(e) =>
											onBudget(e.target.value)
										}
										placeholder="300"
										className={`${FIELD} w-32`}
									/>
								</label>
								<Button
									disabled={busy || !budget}
									onClick={onSetBudget}
								>
									Set budget
								</Button>
								<Button variant="ghost" onClick={onClosePanel}>
									Cancel
								</Button>
							</div>
						</div>
					)}
				</>
			)}
		</RowShell>
	);
};
