import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { formatCurrency } from "../../../lib/format";
import {
	useAddBudgetRule,
	useBudgetSchedules,
	useCreateBudgetSchedule,
} from "../hooks";
import { CampaignPicker } from "./CampaignPicker";
import { TimingFields, emptyTiming, timingPayload } from "./TimingFields";

const FIELD =
	"rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-content focus:border-primary focus:outline-none";
const LABEL = "text-xs font-medium text-content-muted";

/**
 * Automate a campaign's daily budget: pick the campaign, set the everyday budget (what
 * applies when no window is active), and add a first scheduled window (₹ + timing).
 *
 * **A campaign can only have ONE automation** — it has one everyday budget and one on/off
 * policy, so two would only contradict each other. But wanting a second window for a
 * campaign is completely normal, so picking an already-automated campaign switches this
 * form into "add a window to it" rather than refusing: the everyday budget, label and
 * toggle belong to the existing automation and are shown read-only instead of re-asked.
 *
 * The "stop when the window ends" checkbox is campaign ACTIVATION (docs/campaign-activation.md)
 * folded into this form rather than given its own composer: on Blinkit a restart carries
 * the budget, so "run 19:00–02:00 at ₹1000" is one automation, not two. It governs only
 * the STOP — a stopped campaign is started at a window start either way.
 */
export const AutomateBudgetForm = ({ onDone }) => {
	const [campaign, setCampaign] = useState({ id: "", name: "" });
	const [label, setLabel] = useState("");
	const [defaultBudget, setDefaultBudget] = useState("");
	const [windowBudget, setWindowBudget] = useState("");
	const [stopAfterWindow, setStopAfterWindow] = useState(false);
	const [timing, setTiming] = useState(emptyTiming());

	const { data: schedules = [] } = useBudgetSchedules();
	const createSchedule = useCreateBudgetSchedule();
	const addRule = useAddBudgetRule();

	// The automation this campaign already has, if any — decides which mode we're in.
	const existing = schedules.find(
		(s) => s.campaign_id === Number(campaign.id),
	);
	const mutation = existing ? addRule : createSchedule;

	const valid = campaign.id && windowBudget && (existing || defaultBudget);

	const submit = (e) => {
		e.preventDefault();
		if (!valid) return;
		const rule = { budget: Number(windowBudget), ...timingPayload(timing) };

		if (existing) {
			addRule.mutate(
				{ scheduleId: existing.id, body: rule },
				{ onSuccess: () => onDone?.() },
			);
			return;
		}
		createSchedule.mutate(
			{
				campaign_id: Number(campaign.id),
				campaign_name: campaign.name || null,
				name: label || null,
				default_budget: Number(defaultBudget),
				stop_after_window: stopAfterWindow,
				rule,
			},
			{ onSuccess: () => onDone?.() },
		);
	};

	return (
		<form onSubmit={submit} className="space-y-4">
			<div className="grid gap-4 sm:grid-cols-2">
				<label className="flex flex-col gap-1 sm:col-span-2">
					<span className={LABEL}>Campaign</span>
					<CampaignPicker
						value={campaign.id}
						name={campaign.name}
						onChange={(id, name) => setCampaign({ id, name })}
					/>
				</label>

				{existing ? (
					<div className="sm:col-span-2 rounded-lg border border-border bg-muted/40 p-3">
						<p className="text-sm font-medium text-content">
							This campaign already has an automation
						</p>
						<p className="mt-1 text-xs text-content-muted">
							Everyday budget{" "}
							{formatCurrency(existing.default_budget)} ·{" "}
							{existing.rules.length} window
							{existing.rules.length === 1 ? "" : "s"} ·{" "}
							{existing.stop_after_window
								? "stops the campaign when a window ends"
								: "never stops the campaign"}
							. The window below will be added to it. To change
							the everyday budget or the on/off setting, edit the
							automation in the Scheduled list.
						</p>
					</div>
				) : (
					<>
						<label className="flex flex-col gap-1">
							<span className={LABEL}>Everyday budget (₹)</span>
							<input
								type="number"
								min="1"
								value={defaultBudget}
								onChange={(e) =>
									setDefaultBudget(e.target.value)
								}
								placeholder="300"
								className={FIELD}
							/>
							<span className="text-xs text-content-subtle">
								Used outside the scheduled window.
							</span>
						</label>
						<label className="flex flex-col gap-1">
							<span className={LABEL}>Label (optional)</span>
							<input
								value={label}
								onChange={(e) => setLabel(e.target.value)}
								placeholder="Weekend nights"
								className={FIELD}
							/>
						</label>
					</>
				)}
			</div>

			<div className="space-y-3 border-t border-border pt-4">
				<div>
					<h3 className="text-sm font-semibold text-content">
						{existing ? "New window" : "Scheduled window"}
					</h3>
					<p className="text-xs text-content-muted">
						When to apply a different budget — and how much.
					</p>
				</div>
				<label className="flex max-w-48 flex-col gap-1">
					<span className={LABEL}>Budget during window (₹)</span>
					<input
						type="number"
						min="1"
						value={windowBudget}
						onChange={(e) => setWindowBudget(e.target.value)}
						placeholder="1500"
						className={FIELD}
					/>
				</label>
				<TimingFields value={timing} onChange={setTiming} />

				{!existing && (
					<label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-border bg-card p-3">
						<input
							type="checkbox"
							checked={stopAfterWindow}
							onChange={(e) =>
								setStopAfterWindow(e.target.checked)
							}
							className="mt-0.5 h-4 w-4 accent-primary"
						/>
						<span className="min-w-0">
							<span className="block text-sm font-medium text-content">
								Stop the campaign when the window ends
							</span>
							<span className="block text-xs text-content-muted">
								At the end of each window the budget returns to
								the everyday amount and the campaign is stopped.
								It starts again at the next window.
							</span>
						</span>
					</label>
				)}
			</div>

			{mutation.isError && (
				<p className="text-xs text-danger">
					{mutation.error?.status === 409
						? "An automation for that campaign already exists — reopen this form to add a window to it."
						: (mutation.error?.message ?? "Failed to save")}
				</p>
			)}

			<div className="flex gap-2">
				<Button type="submit" disabled={mutation.isPending || !valid}>
					{mutation.isPending
						? "Saving…"
						: existing
							? "Add window"
							: "Create budget automation"}
				</Button>
				<Button type="button" variant="ghost" onClick={onDone}>
					Cancel
				</Button>
			</div>
		</form>
	);
};
