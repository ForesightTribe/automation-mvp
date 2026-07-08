import { DataTable } from "../../../components/ui/DataTable";
import { Button } from "../../../components/ui/Button";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { useDeleteRule, useUpdateRule } from "../hooks";

const OP_LABEL = { lt: "<", lte: "≤", gt: ">", gte: "≥" };

const scopeLabel = (rule) => {
	if (rule.scope_type === "all") return "All campaigns";
	return `${rule.scope_type === "campaign_type" ? "Type" : "Campaign"} = ${rule.scope_value}`;
};

/** Rules table with an active/inactive toggle, edit (hands the row up to the
 * parent's RuleForm), and delete. */
export const RulesList = ({ rules, onEdit }) => {
	const updateRule = useUpdateRule();
	const deleteRule = useDeleteRule();

	if (!rules.length) {
		return (
			<EmptyState
				title="No rules yet"
				message="Add a rule above to start watching your ad campaigns."
			/>
		);
	}

	const columns = [
		{ key: "name", label: "Rule" },
		{ key: "scope", label: "Scope", render: scopeLabel },
		{
			key: "condition",
			label: "Condition",
			render: (r) => `${r.metric} ${OP_LABEL[r.operator]} ${r.threshold} / ${r.window_days}d`,
		},
		{
			key: "action",
			label: "Action",
			render: (r) =>
				r.action_type.replace(/_/g, " ") +
				(r.action_value != null ? ` (${r.action_value}%)` : ""),
		},
		{
			key: "active",
			label: "Active",
			render: (r) => (
				<button
					type="button"
					onClick={() =>
						updateRule.mutate({
							ruleId: r.id,
							payload: { is_active: !r.is_active },
						})
					}
					className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
						r.is_active
							? "bg-success-soft text-success"
							: "bg-muted text-content-muted"
					}`}
				>
					{r.is_active ? "Active" : "Paused"}
				</button>
			),
		},
		{
			key: "actions",
			label: "",
			align: "right",
			render: (r) => (
				<div className="flex justify-end gap-1.5">
					<Button variant="ghost" size="sm" onClick={() => onEdit(r)}>
						Edit
					</Button>
					<Button
						variant="ghost"
						size="sm"
						onClick={() => deleteRule.mutate(r.id)}
					>
						Delete
					</Button>
				</div>
			),
		},
	];

	return <DataTable columns={columns} rows={rules} rowKey={(r) => r.id} />;
};
