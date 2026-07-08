import { useState } from "react";
import { Card } from "../../components/ui/Card";
import { Button } from "../../components/ui/Button";
import { Loading } from "../../components/feedback/Loading";
import { ErrorState } from "../../components/feedback/ErrorState";
import { RuleForm } from "./components/RuleForm";
import { RulesList } from "./components/RulesList";
import { ActionsQueue } from "./components/ActionsQueue";
import { useEvaluateNow, useRules } from "./hooks";

/**
 * Ad Automation — Phase 1: rule engine + recommendation queue. No code here
 * touches Blinkit; "approved" means the user makes the change there by hand
 * (see the plan notes on why: Blinkit's mutation endpoints aren't
 * reverse-engineered yet, and the scraper's write_blocker aborts writes by
 * design). "Check now" runs every active rule on demand — there's no cron yet.
 */
export const AdAutomationPage = () => {
	const [editingRule, setEditingRule] = useState(null);
	const { data: rules, isLoading, error, refetch } = useRules();
	const evaluateNow = useEvaluateNow();

	return (
		<div className="flex flex-col gap-6">
			<div className="flex items-center justify-between gap-3">
				<div>
					<h1 className="font-display text-xl font-bold text-content">
						Ad Automation
					</h1>
					<p className="text-sm text-content-muted">
						Rules watch your ad spend; recommendations queue up for you to
						approve.
					</p>
				</div>
				<Button
					onClick={() => evaluateNow.mutate()}
					disabled={evaluateNow.isPending}
				>
					{evaluateNow.isPending ? "Checking…" : "Check now"}
				</Button>
			</div>

			{evaluateNow.isSuccess && (
				<p className="text-sm text-content-muted">
					{evaluateNow.data.new_actions} new recommendation(s) found.
				</p>
			)}

			<Card title={editingRule ? "Edit rule" : "Add a rule"}>
				<RuleForm rule={editingRule} onDone={() => setEditingRule(null)} />
			</Card>

			<Card title="Rules">
				{isLoading && <Loading label="Loading rules…" />}
				{error && <ErrorState message={error.message} onRetry={refetch} />}
				{!isLoading && !error && (
					<RulesList rules={rules ?? []} onEdit={setEditingRule} />
				)}
			</Card>

			<ActionsQueue />
		</div>
	);
};
