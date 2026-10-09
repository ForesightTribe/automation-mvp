import { useEffect, useState } from "react";
import { Modal } from "../../../components/ui/Modal";
import { Button } from "../../../components/ui/Button";
import {
	useResetUserPassword,
	useSetUserClients,
	useSetUserRole,
} from "../hooks";
import { useClient } from "../../../context/ClientContext";

/**
 * Everything about one user in a single place: what they may do, which clients
 * they may do it to, and a password reset if they are locked out.
 *
 * One editor rather than controls scattered across a table row — a role
 * dropdown that saves on change gives no chance to reconsider, and three
 * separate affordances per row made the table read as a control panel.
 *
 * Two modes, not a checkbox list with a special case: "every client" is a
 * standing permission that keeps up as clients are added, while a chosen set is
 * a fixed list. Collapsing them would mean a new brand silently appearing for
 * someone scoped to three others.
 *
 * Saving replaces the previous grants outright, so what is ticked here is the
 * user's complete access rather than an addition to it.
 */
export const UserEditModal = ({ user, open, onClose }) => {
	const { clients } = useClient();
	const setClients = useSetUserClients();
	const setRole = useSetUserRole();
	const resetPassword = useResetUserPassword();
	const [role, setRoleValue] = useState("member");
	const [scope, setScope] = useState("all");
	const [picked, setPicked] = useState([]);
	const [error, setError] = useState(null);
	// An admin-set password, for someone locked out. Separate from the access
	// save, because they are independent actions and bundling them would mean
	// an access change could not be made without touching a password.
	const [pw, setPw] = useState("");
	const [pwDone, setPwDone] = useState(false);
	const [pwError, setPwError] = useState(null);

	// Reopening for a different user must not carry the last one's selection.
	useEffect(() => {
		if (!open || !user) return;
		setRoleValue(user.role);
		setScope(user.client_scope === "listed" ? "listed" : "all");
		setPicked((user.clients ?? []).map((c) => c.id));
		setError(null);
		setPw("");
		setPwDone(false);
		setPwError(null);
	}, [open, user]);

	const toggle = (id) =>
		setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

	const save = async () => {
		setError(null);
		try {
			// Role first: the server refuses demoting the last admin, and that
			// refusal should stop the whole save rather than leave a half-applied
			// change behind.
			if (role !== user.role) {
				await setRole.mutateAsync({ userId: user.id, role });
			}
			await setClients.mutateAsync({
				userId: user.id,
				clientIds: scope === "all" ? null : picked,
			});
			onClose();
		} catch (e) {
			setError(e.message);
		}
	};

	const doReset = async () => {
		setPwError(null);
		try {
			await resetPassword.mutateAsync({ userId: user.id, newPassword: pw });
			setPw("");
			setPwDone(true);
		} catch (e) {
			setPwError(e.message);
		}
	};

	const radio = (value, label, hint) => (
		<label
			key={value}
			className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 transition-colors ${
				scope === value
					// Border and the radio's own dot carry the brand colour; the
					// panel stays neutral. A tinted fill on a red brand reads as
					// a warning rather than a selection.
					? "border-brand bg-card"
					: "border-border hover:border-content-subtle"
			}`}
		>
			<input
				type="radio"
				name="scope"
				checked={scope === value}
				onChange={() => setScope(value)}
				className="mt-0.5 accent-brand"
			/>
			<span>
				<span className="block text-sm font-medium text-content">{label}</span>
				<span className="block text-xs text-content-muted">{hint}</span>
			</span>
		</label>
	);

	return (
		<Modal
			open={open}
			onClose={onClose}
			title={user ? user.email : "Edit user"}
			subtitle="Takes up to a minute to apply to a signed-in user."
			footer={
				<div className="flex items-center justify-end gap-2">
					<Button variant="ghost" onClick={onClose}>
						Cancel
					</Button>
					<Button
						variant="brandSolid"
						onClick={save}
						disabled={
							setClients.isPending ||
							setRole.isPending ||
							(scope === "listed" && picked.length === 0)
						}
					>
						{setClients.isPending || setRole.isPending
							? "Saving…"
							: "Save changes"}
					</Button>
				</div>
			}
		>
			<div className="flex flex-col gap-3">
				<label className="flex flex-col gap-1.5">
					<span className="text-xs font-semibold tracking-wide text-content-subtle uppercase">
						Role
					</span>
					<select
						value={role}
						onChange={(e) => setRoleValue(e.target.value)}
						className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-content focus:border-brand focus:outline-none"
					>
						<option value="member">
							Member — reads everything, changes nothing
						</option>
						<option value="admin">
							Admin — can also change budgets, bids and settings
						</option>
					</select>
				</label>

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
									onChange={() => toggle(c.id)}
									className="accent-brand"
								/>
								{c.name}
							</label>
						))}
					</div>
				)}

				{error && (
					<p className="rounded-lg border-2 border-danger/50 px-3 py-2 text-sm text-content">
						{error}
					</p>
				)}

				{/* Set a password for someone who cannot sign in. No email is
				    sent, so it has to be passed on directly. */}
				<div className="mt-1 flex flex-col gap-2 border-t border-border pt-3">
					<span className="text-xs font-semibold tracking-wide text-content-subtle uppercase">
						Reset their password
					</span>
					<div className="flex items-start gap-2">
						<input
							type="text"
							value={pw}
							onChange={(e) => {
								setPw(e.target.value);
								setPwDone(false);
								setPwError(null);
							}}
							placeholder="New password, at least 8 characters"
							className="flex-1 rounded-lg border border-border bg-card px-3 py-2 text-sm text-content transition-colors focus:border-brand focus:outline-none"
						/>
						<Button
							variant="secondary"
							onClick={doReset}
							disabled={pw.length < 8 || resetPassword.isPending}
						>
							{resetPassword.isPending ? "Setting…" : "Set"}
						</Button>
					</div>
					{pwError && <p className="text-xs text-danger">{pwError}</p>}
					{pwDone && (
						<p className="text-xs text-success">
							Password set. Share it with them directly — no email is sent.
						</p>
					)}
				</div>
			</div>
		</Modal>
	);
};
