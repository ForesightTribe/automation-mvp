import { useClient } from "../../../context/ClientContext";

/**
 * Which clients a user may open, for the add and edit dialogs. "All" keeps up
 * as clients are added; a chosen set does not.
 */
export const ClientScopePicker = ({ scope, onScope, picked, onToggle }) => {
	const { clients } = useClient();

	const radio = (value, label, hint) => (
		<label
			key={value}
			className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 transition-colors ${
				scope === value
					? // Brand colour on the border and the dot only; the panel stays neutral.
						"border-brand bg-card"
					: "border-border hover:border-content-subtle"
			}`}
		>
			<input
				type="radio"
				name="scope"
				checked={scope === value}
				onChange={() => onScope(value)}
				className="mt-0.5 accent-brand"
			/>
			<span>
				<span className="block text-sm font-medium text-content">
					{label}
				</span>
				<span className="block text-xs text-content-muted">{hint}</span>
			</span>
		</label>
	);

	return (
		<>
			<span className="mt-1 text-xs font-semibold tracking-wide text-content-subtle uppercase">
				Client access
			</span>
			{radio(
				"all",
				"Every client on the account",
				"Including any client added later.",
			)}
			{radio(
				"listed",
				"Only the clients I choose",
				"They will not see that the other clients exist.",
			)}

			{scope === "listed" && (
				<div className="flex flex-col gap-1.5 rounded-xl border border-border p-3">
					{(clients ?? []).map((c) => (
						<label
							key={c.id}
							className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm text-content hover:bg-muted"
						>
							<input
								type="checkbox"
								checked={picked.includes(c.id)}
								onChange={() => onToggle(c.id)}
								className="accent-brand"
							/>
							{c.name}
						</label>
					))}
				</div>
			)}
		</>
	);
};
