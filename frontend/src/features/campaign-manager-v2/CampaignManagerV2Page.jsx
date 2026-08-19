import { useState } from "react";
import { Card } from "../../components/ui/Card";
import { ActivateNowCard } from "./components/ActivateNowCard";
import { AutomateBidForm } from "./components/AutomateBidForm";
import { AutomateBudgetForm } from "./components/AutomateBudgetForm";
import { HistoryCard } from "./components/HistoryCard";
import { ScheduledSection } from "./components/ScheduledSection";
import { SetBudgetNowCard } from "./components/SetBudgetNowCard";

/**
 * Campaign Manager — set-and-forget automation for Blinkit budgets and keyword bids.
 *
 * The page reads top-down as one column of full-width bands: the composer for a new
 * automation, then the two on-demand actions side by side, then everything scheduled,
 * then history. Scheduled is a band rather than a side pane because its rows carry
 * campaign names, weekday strips and time windows that a third of a laptop screen
 * truncates into uselessness.
 *
 * Every edit just writes DB rows + enqueues a reconcile — no browser work happens here.
 */
const OPTIONS = [
	{
		key: "budget",
		icon: "₹",
		title: "Automate budget",
		desc: "Schedule a campaign's daily budget — set a default and raise or lower it during chosen time windows.",
	},
	{
		key: "bid",
		icon: "◎",
		title: "Automate bidding",
		desc: "Chase a target search position for a keyword within a bid range, during the times you choose.",
	},
];

const OptionTile = ({ option, onClick }) => (
	<button
		type="button"
		onClick={onClick}
		className="flex flex-col items-start gap-2 rounded-xl border border-border bg-surface p-4 text-left transition-colors hover:border-primary hover:bg-muted"
	>
		<span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-soft text-lg text-primary">
			{option.icon}
		</span>
		<span className="font-display text-sm font-semibold text-content">
			{option.title}
		</span>
		<span className="text-xs text-content-muted">{option.desc}</span>
	</button>
);

const Composer = ({ mode, setMode }) => {
	if (mode === null) {
		return (
			<Card title="Create an automation">
				<div className="grid gap-3 sm:grid-cols-2">
					{OPTIONS.map((o) => (
						<OptionTile
							key={o.key}
							option={o}
							onClick={() => setMode(o.key)}
						/>
					))}
				</div>
			</Card>
		);
	}

	const option = OPTIONS.find((o) => o.key === mode);
	return (
		<Card
			title={option.title}
			actions={
				<button
					type="button"
					onClick={() => setMode(null)}
					className="text-xs font-medium text-content-muted hover:text-content"
				>
					← Back
				</button>
			}
		>
			{mode === "budget" ? (
				<AutomateBudgetForm onDone={() => setMode(null)} />
			) : (
				<AutomateBidForm onDone={() => setMode(null)} />
			)}
		</Card>
	);
};

export const CampaignManagerV2Page = () => {
	const [mode, setMode] = useState(null); // null | "budget" | "bid"

	return (
		<div className="space-y-6">
			<header>
				<h1 className="font-display text-xl font-semibold text-content">
					Campaign Manager
				</h1>
				<p className="text-sm text-content-muted">
					Automate campaign budgets and keyword bids across the times
					that matter.
				</p>
			</header>

			<Composer mode={mode} setMode={setMode} />

			<div className="grid gap-6 lg:grid-cols-2">
				<SetBudgetNowCard />
				<ActivateNowCard />
			</div>

			<ScheduledSection />

			<HistoryCard />
		</div>
	);
};
