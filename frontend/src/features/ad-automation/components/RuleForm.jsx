import { useEffect, useState } from "react";
import { Button } from "../../../components/ui/Button";
import { useCreateRule, useUpdateRule } from "../hooks";

const METRICS = [
	{ value: "roas", label: "RoAS" },
	{ value: "acos", label: "ACoS" },
	{ value: "budget_consumed", label: "Spend" },
	{ value: "ad_sales", label: "Ad revenue" },
	{ value: "impressions", label: "Impressions" },
];

const OPERATORS = [
	{ value: "lt", label: "<" },
	{ value: "lte", label: "≤" },
	{ value: "gt", label: ">" },
	{ value: "gte", label: "≥" },
];

const SCOPES = [
	{ value: "all", label: "All campaigns" },
	{ value: "campaign_type", label: "Campaign type" },
	{ value: "campaign", label: "Specific campaign ID" },
];

const ACTIONS = [
	{ value: "alert_only", label: "Alert only" },
	{ value: "pause", label: "Pause campaign" },
	{ value: "resume", label: "Resume campaign" },
	{ value: "adjust_budget_pct", label: "Adjust budget %" },
	{ value: "adjust_bid_pct", label: "Adjust bid %" },
];

const EMPTY = {
	name: "",
	scope_type: "all",
	scope_value: "",
	metric: "roas",
	operator: "lt",
	threshold: "",
	window_days: 7,
	action_type: "alert_only",
	action_value: "",
};

const fieldCls =
	"rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-content focus:outline-none focus:ring-2 focus:ring-primary/30";

/** Create or edit a rule. `rule` is null for create; passing one switches the
 * form into edit mode (prefilled, PUT instead of POST) and `onDone` is called
 * on both save and cancel so the parent can close the panel. */
export const RuleForm = ({ rule, onDone }) => {
	const [form, setForm] = useState(EMPTY);
	const createRule = useCreateRule();
	const updateRule = useUpdateRule();

	useEffect(() => {
		if (rule) {
			setForm({
				name: rule.name,
				scope_type: rule.scope_type,
				scope_value: rule.scope_value ?? "",
				metric: rule.metric,
				operator: rule.operator,
				threshold: rule.threshold,
				window_days: rule.window_days,
				action_type: rule.action_type,
				action_value: rule.action_value ?? "",
			});
		} else {
			setForm(EMPTY);
		}
	}, [rule]);

	const set = (key) => (e) =>
		setForm((f) => ({ ...f, [key]: e.target.value }));

	const mutation = rule ? updateRule : createRule;

	const submit = (e) => {
		e.preventDefault();
		const payload = {
			...form,
			scope_value: form.scope_value || null,
			threshold: Number(form.threshold),
			window_days: Number(form.window_days),
			action_value: form.action_value === "" ? null : Number(form.action_value),
		};
		const run = rule
			? updateRule.mutateAsync({ ruleId: rule.id, payload })
			: createRule.mutateAsync(payload);
		run.then(() => {
			setForm(EMPTY);
			onDone?.();
		});
	};

	return (
		<form
			onSubmit={submit}
			className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
		>
			<label className="col-span-2 flex flex-col gap-1 text-xs text-content-subtle sm:col-span-3 lg:col-span-4">
				Rule name
				<input
					required
					value={form.name}
					onChange={set("name")}
					placeholder="e.g. Cut budget on low RoAS"
					className={fieldCls}
				/>
			</label>

			<label className="flex flex-col gap-1 text-xs text-content-subtle">
				Scope
				<select
					value={form.scope_type}
					onChange={set("scope_type")}
					className={fieldCls}
				>
					{SCOPES.map((s) => (
						<option key={s.value} value={s.value}>
							{s.label}
						</option>
					))}
				</select>
			</label>

			{form.scope_type !== "all" && (
				<label className="flex flex-col gap-1 text-xs text-content-subtle">
					{form.scope_type === "campaign_type" ? "Type value" : "Campaign ID"}
					<input
						required
						value={form.scope_value}
						onChange={set("scope_value")}
						className={fieldCls}
					/>
				</label>
			)}

			<label className="flex flex-col gap-1 text-xs text-content-subtle">
				Metric
				<select
					value={form.metric}
					onChange={set("metric")}
					className={fieldCls}
				>
					{METRICS.map((m) => (
						<option key={m.value} value={m.value}>
							{m.label}
						</option>
					))}
				</select>
			</label>

			<label className="flex flex-col gap-1 text-xs text-content-subtle">
				Condition
				<div className="flex gap-1.5">
					<select
						value={form.operator}
						onChange={set("operator")}
						className={`${fieldCls} w-16`}
					>
						{OPERATORS.map((o) => (
							<option key={o.value} value={o.value}>
								{o.label}
							</option>
						))}
					</select>
					<input
						required
						type="number"
						step="any"
						value={form.threshold}
						onChange={set("threshold")}
						className={`${fieldCls} w-full`}
					/>
				</div>
			</label>

			<label className="flex flex-col gap-1 text-xs text-content-subtle">
				Window (days)
				<input
					required
					type="number"
					min="1"
					value={form.window_days}
					onChange={set("window_days")}
					className={fieldCls}
				/>
			</label>

			<label className="flex flex-col gap-1 text-xs text-content-subtle">
				Action
				<select
					value={form.action_type}
					onChange={set("action_type")}
					className={fieldCls}
				>
					{ACTIONS.map((a) => (
						<option key={a.value} value={a.value}>
							{a.label}
						</option>
					))}
				</select>
			</label>

			{form.action_type.endsWith("_pct") && (
				<label className="flex flex-col gap-1 text-xs text-content-subtle">
					Change by %
					<input
						required
						type="number"
						step="any"
						value={form.action_value}
						onChange={set("action_value")}
						placeholder="-20"
						className={fieldCls}
					/>
				</label>
			)}

			<div className="col-span-2 flex items-end gap-2 sm:col-span-3 lg:col-span-4">
				<Button type="submit" size="sm" disabled={mutation.isPending}>
					{rule ? "Save changes" : "Add rule"}
				</Button>
				{rule && (
					<Button
						type="button"
						variant="secondary"
						size="sm"
						onClick={onDone}
					>
						Cancel
					</Button>
				)}
				{mutation.isError && (
					<span className="text-xs text-danger">
						{mutation.error.message}
					</span>
				)}
			</div>
		</form>
	);
};
