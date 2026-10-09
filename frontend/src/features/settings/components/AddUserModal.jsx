import { useEffect, useState } from "react";
import { Modal } from "../../../components/ui/Modal";
import { Button } from "../../../components/ui/Button";
import { useCreateAccountUser } from "../hooks";

/**
 * Add a login to the account.
 *
 * The admin sets the first password and passes it on themselves: there is no
 * transactional email in this system, so an invite link is not an option. Said
 * plainly on the form, because an admin who assumes an email went out will
 * leave someone unable to sign in.
 */
export const AddUserModal = ({ open, onClose }) => {
	const create = useCreateAccountUser();
	const [form, setForm] = useState({
		email: "",
		full_name: "",
		password: "",
		role: "member",
	});
	const [error, setError] = useState(null);

	useEffect(() => {
		if (!open) return;
		setForm({ email: "", full_name: "", password: "", role: "member" });
		setError(null);
	}, [open]);

	const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
	const ready = form.email.includes("@") && form.password.length >= 8;

	const submit = async () => {
		setError(null);
		try {
			await create.mutateAsync(form);
			onClose();
		} catch (e) {
			setError(e.message);
		}
	};

	const field = (label, key, type = "text", placeholder = "") => (
		<label className="flex flex-col gap-1.5">
			<span className="text-xs font-medium text-content-muted">{label}</span>
			<input
				type={type}
				value={form[key]}
				onChange={set(key)}
				placeholder={placeholder}
				className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-content transition-colors focus:border-brand focus:outline-none"
			/>
		</label>
	);

	return (
		<Modal
			open={open}
			onClose={onClose}
			title="Add a user"
			subtitle="They can sign in straight away with the password you set here."
			footer={
				<div className="flex items-center justify-end gap-2">
					<Button variant="ghost" onClick={onClose}>
						Cancel
					</Button>
					<Button
						variant="brandSolid"
						onClick={submit}
						disabled={!ready || create.isPending}
					>
						{create.isPending ? "Adding…" : "Add user"}
					</Button>
				</div>
			}
		>
			<div className="flex flex-col gap-3">
				{field("Email", "email", "email", "name@company.com")}
				{field("Full name", "full_name", "text", "Optional")}
				{field("Initial password", "password", "text", "At least 8 characters")}

				<label className="flex flex-col gap-1.5">
					<span className="text-xs font-medium text-content-muted">Role</span>
					<select
						value={form.role}
						onChange={set("role")}
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

				{/* Shown rather than left implicit: no email is sent, so the admin
				    has to pass the password on or the user cannot get in. */}
				<p className="rounded-lg border border-border bg-surface px-3 py-2 text-xs text-content-muted">
					No invitation email is sent. Share the password with them
					directly, and ask them to change it after signing in.
				</p>

				{error && (
					<p className="rounded-lg border-2 border-danger/50 px-3 py-2 text-sm text-content">
						{error}
					</p>
				)}
			</div>
		</Modal>
	);
};
