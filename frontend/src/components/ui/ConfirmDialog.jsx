import { Button } from "./Button";

/**
 * The confirmation step in front of an action that reaches a live ad account.
 *
 * Automation lifecycle changes, a one-off budget push, starting or stopping a campaign:
 * none of them is an undo away, so each states what it is about to do, to what, before
 * it happens.
 *
 * `blocked` is for a state the engine itself refuses (resetting a running rule, which
 * comes back a 409): the dialog still opens and explains, but the confirm is inert
 * rather than spending a request that is going to fail.
 */
export const ConfirmDialog = ({
	open,
	title,
	body,
	confirmLabel = "Confirm",
	danger = false,
	blocked = null,
	pending = false,
	error = null,
	children,
	onConfirm,
	onCancel,
}) => {
	if (!open) return null;
	return (
		<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
			<div className="w-full max-w-md rounded-lg border border-border bg-card p-5">
				<h3 className="mb-2 font-display text-base font-semibold text-content">
					{title}
				</h3>
				{/* whitespace-normal: these dialogs are opened from table cells that set
				    nowrap, and a campaign name is long enough to run off the card. */}
				<div className="mb-4 whitespace-normal break-words text-sm leading-relaxed text-content-muted">
					{body}
				</div>
				{children}
				{blocked && (
					<p className="mb-4 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm text-content">
						{blocked}
					</p>
				)}
				{error && (
					<p className="mb-4 rounded-md border-2 border-danger/50 px-3 py-2 text-sm text-danger">
						{error}
					</p>
				)}
				<div className="flex justify-end gap-2">
					<Button variant="secondary" size="sm" onClick={onCancel}>
						Cancel
					</Button>
					<Button
						variant={danger ? "danger" : "brandSolid"}
						size="sm"
						disabled={pending || Boolean(blocked)}
						onClick={onConfirm}
					>
						{pending ? "Working…" : confirmLabel}
					</Button>
				</div>
			</div>
		</div>
	);
};
