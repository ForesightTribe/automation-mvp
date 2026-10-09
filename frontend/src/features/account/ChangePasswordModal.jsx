import { useState } from "react";

import { useChangeOwnPassword } from "../settings/hooks";
import { useAuth } from "../../context/AuthContext";
import { Modal } from "../../components/ui/Modal";
import { Button } from "../../components/ui/Button";

const MIN = 8;

/**
 * Changing your own password.
 *
 * Reached from the account block on Settings, which is open to every user —
 * everyone starts with a password an admin chose and passed on, so without this
 * there is no way to end up with one only you know. The current password is
 * required: a token left open on a shared machine is not proof of ownership.
 *
 * On success the user is signed out, so the next sign-in uses the new password
 * and a shared browser is not left holding a live session.
 *
 * ⚠️ This signs out THIS device only. Tokens are stateless and signed with
 * SECRET_KEY, so one already issued to another device keeps working until it
 * expires — a server-side token version would be needed to evict those.
 */
export const ChangePasswordModal = ({ open, onClose }) => {
	const { user, logout } = useAuth();
	const change = useChangeOwnPassword();
	const [form, setForm] = useState({ current: "", next: "", confirm: "" });
	const [error, setError] = useState(null);
	const [done, setDone] = useState(false);

	const set = (k) => (e) => {
		setForm((f) => ({ ...f, [k]: e.target.value }));
		setError(null);
		setDone(false);
	};

	const mismatch = Boolean(form.confirm) && form.next !== form.confirm;
	const ready =
		form.current.length > 0 && form.next.length >= MIN && !mismatch;

	const submit = async () => {
		setError(null);
		try {
			await change.mutateAsync({
				currentPassword: form.current,
				newPassword: form.next,
			});
			setForm({ current: "", next: "", confirm: "" });
			setDone(true);
			// Long enough to read the confirmation, then out. Without the pause
			// the screen would snap to the login form with no explanation.
			setTimeout(logout, 1500);
		} catch (e) {
			setError(e.message);
		}
	};

	const field = (label, key, hint) => (
		<label className="flex flex-col gap-1.5">
			<span className="text-xs font-medium text-content-muted">{label}</span>
			<input
				type="password"
				value={form[key]}
				onChange={set(key)}
				autoComplete={key === "current" ? "current-password" : "new-password"}
				className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-content transition-colors focus:border-brand focus:outline-none"
			/>
			{hint && <span className="text-xs text-content-subtle">{hint}</span>}
		</label>
	);

	return (
		<Modal
			open={open}
			onClose={onClose}
			title="Change your password"
			size="md"
			footer={
				<div className="flex items-center justify-end gap-2">
					<Button variant="ghost" onClick={onClose}>
						Close
					</Button>
					<Button
						variant="brandSolid"
						onClick={submit}
						disabled={!ready || change.isPending}
					>
						{change.isPending ? "Changing…" : "Change password"}
					</Button>
				</div>
			}
		>
			<div className="flex flex-col gap-3">
				<p className="text-xs text-content-muted">
					Signed in as {user?.email}. You will be signed out and will
					need to sign in again with the new password.
				</p>

				{field("Current password", "current")}
				{field("New password", "next", `At least ${MIN} characters`)}
				{field("Confirm new password", "confirm")}

				{mismatch && (
					<p className="text-xs text-warning">
						The two new passwords do not match.
					</p>
				)}
				{error && (
					<p className="rounded-lg border-2 border-danger/50 px-3 py-2 text-sm text-content">
						{error}
					</p>
				)}
				{done && (
					<p className="rounded-lg border border-success/30 bg-success-soft px-3 py-2 text-sm text-content">
						Password changed — signing you out…
					</p>
				)}

			</div>
		</Modal>
	);
};
