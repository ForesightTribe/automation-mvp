import { useState } from "react";
import { Card } from "../../components/ui/Card";
import { AutomateBidForm } from "./components/AutomateBidForm";
import { AutomateBudgetForm } from "./components/AutomateBudgetForm";
import { CampaignsSection } from "./components/CampaignsSection";
import { HistoryCard } from "./components/HistoryCard";
import { ScheduledSection } from "./components/ScheduledSection";

/**
 * Campaign Manager — set-and-forget automation for Blinkit budgets and keyword bids.
 *
 * The page reads top-down as four full-width bands: the composer for a new automation,
 * the account's campaigns with their immediate on/off + budget controls, everything
 * scheduled, then history. They are bands rather than columns because every one of them
 * is a list of rows carrying campaign names, weekday strips and time windows — a third of
 * a laptop screen truncates all of it into uselessness.
 *
 * The immediate actions live ON a campaign's own row rather than in separate cards with
 * their own campaign pickers: the page used to offer three different ways to find a
 * campaign, and picking one by name is exactly where this goes wrong, because names
 * repeat across an account.
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

			<CampaignsSection />

			<ScheduledSection />

			<HistoryCard />
		</div>
	);
};
