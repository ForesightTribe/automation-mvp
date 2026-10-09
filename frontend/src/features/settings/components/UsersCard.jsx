import { useState } from "react";
import { Pencil, UserPlus } from "lucide-react";
import {
	useAccountUsers,
	useDeleteAccountUser,
	useSetUserActive,
} from "../hooks";
import { useAuth } from "../../../context/AuthContext";
import { Card } from "../../../components/ui/Card";
import { Button } from "../../../components/ui/Button";
import { Select } from "../../../components/ui/Select";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { AddUserModal } from "./AddUserModal";
import { UserEditModal } from "./UserEditModal";

/**
 * Who can sign in to this account, what they may change, and which clients
 * they can see.
 *
 * The table reads; one Edit button per row writes. Role and access used to be
 * editable inline, which meant a dropdown applying a permission change the
 * moment it was touched — no chance to reconsider, and three affordances per
 * row competing for the same glance.
 *
 * Deactivating and deleting sit in their own section below. Both are
 * destructive and neither belongs one mis-click from a row someone is reading.
 */
export const UsersCard = () => {
	const { data, isLoading, error, refetch } = useAccountUsers();
	const { user: me } = useAuth();
	const setActive = useSetUserActive();
	const removeUser = useDeleteAccountUser();
	const [adding, setAdding] = useState(false);
	const [editing, setEditing] = useState(null);
	const [dangerId, setDangerId] = useState("");
	const [confirm, setConfirm] = useState(null); // { user, kind }
	const [confirmError, setConfirmError] = useState(null);

	const rows = data ?? [];
	const target = rows.find((u) => u.id === dangerId) ?? null;

	const accessLabel = (u) =>
		u.client_scope === "all"
			? "All clients"
			: u.clients.length
				? u.clients.map((c) => c.name).join(", ")
				: "No clients";

	const runConfirmed = async () => {
		setConfirmError(null);
		try {
			if (confirm.kind === "delete") {
				await removeUser.mutateAsync({ userId: confirm.user.id });
				setDangerId("");
			} else {
				await setActive.mutateAsync({
					userId: confirm.user.id,
					isActive: !confirm.user.is_active,
				});
			}
			setConfirm(null);
		} catch (e) {
			setConfirmError(e.message);
		}
	};

	return (
		<Card
			title="Users & access"
			actions={
				<Button size="sm" variant="brandSolid" onClick={() => setAdding(true)}>
					<UserPlus size={14} /> Add user
				</Button>
			}
		>
			{isLoading ? (
				<Loading label="Loading users…" />
			) : error ? (
				<ErrorState message={error.message} onRetry={refetch} />
			) : (
				<>
					<div className="overflow-auto">
						<table className="w-full border-collapse text-sm">
							<thead className="sticky top-0 z-10 bg-card">
								<tr className="border-b border-border">
									{["User", "Role", "Client access", ""].map((h) => (
										<th
											key={h}
											className="px-3 py-2 text-left text-[11px] font-medium tracking-wide text-content-subtle uppercase"
										>
											{h}
										</th>
									))}
								</tr>
							</thead>
							<tbody>
								{rows.map((u) => (
									<tr
										key={u.id}
										className="border-b border-border/60 last:border-0"
									>
										<td className="px-3 py-2.5">
											<span className="font-medium text-content">
												{u.full_name || u.email}
												{u.email === me?.email && (
													<span className="ml-2 text-xs text-content-subtle">
														you
													</span>
												)}
											</span>
											<span className="block text-xs text-content-muted">
												{u.email}
											</span>
											{!u.is_active && (
												<span className="mt-1 inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-content-muted uppercase">
													deactivated
												</span>
											)}
										</td>
										<td className="px-3 py-2.5 capitalize text-content">
											{u.role}
										</td>
										<td className="max-w-[20rem] truncate px-3 py-2.5 text-content">
											{accessLabel(u)}
										</td>
										<td className="px-3 py-2.5 text-right">
											<Button
												size="xs"
												variant="secondary"
												onClick={() => setEditing(u)}
											>
												<Pencil size={12} /> Edit
											</Button>
										</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>

					{/* Deliberately not per-row: picking the person is part of the
					    decision, and both actions here are hard or impossible to
					    undo. */}
					<div className="mt-5 rounded-xl border-2 border-danger/50 p-4">
						<p className="text-xs font-semibold tracking-wide text-danger uppercase">
							Danger zone
						</p>
						<p className="mt-1 text-xs text-content-muted">
							Deactivating blocks sign-in and can be undone. Deleting
							removes the user from the system and is not recoverable.
						</p>
						<div className="mt-3 flex flex-wrap items-center gap-2">
							<Select
								ariaLabel="User to act on"
								value={dangerId}
								onChange={setDangerId}
								options={[
									["", "Select a user…"],
									...rows.map((u) => [
										u.id,
										`${u.email}${u.is_active ? "" : " (deactivated)"}`,
									]),
								]}
							/>
							<Button
								size="sm"
								variant="secondary"
								disabled={!target}
								onClick={() =>
									setConfirm({ user: target, kind: "active" })
								}
							>
								{target && !target.is_active ? "Reactivate" : "Deactivate"}
							</Button>
							<Button
								size="sm"
								variant="danger"
								disabled={!target}
								onClick={() => setConfirm({ user: target, kind: "delete" })}
							>
								Delete user
							</Button>
						</div>
					</div>
				</>
			)}

			<ConfirmDialog
				open={confirm != null}
				danger={confirm?.kind === "delete" || confirm?.user?.is_active}
				title={
					confirm?.kind === "delete"
						? "Delete this user?"
						: confirm?.user?.is_active
							? "Deactivate this user?"
							: "Reactivate this user?"
				}
				body={
					confirm?.kind === "delete"
						? `${confirm?.user?.email} will be removed from the system, along with their client access. This is not recoverable. Deactivating keeps the record and can be reversed.`
						: confirm?.user?.is_active
							? `${confirm?.user?.email} will not be able to sign in. Their attempts will look like a wrong password, so tell them.`
							: `${confirm?.user?.email} will be able to sign in again with their existing password.`
				}
				confirmLabel={
					confirm?.kind === "delete"
						? "Delete permanently"
						: confirm?.user?.is_active
							? "Deactivate"
							: "Reactivate"
				}
				pending={removeUser.isPending || setActive.isPending}
				error={confirmError}
				onConfirm={runConfirmed}
				onCancel={() => {
					setConfirm(null);
					setConfirmError(null);
				}}
			/>

			<AddUserModal open={adding} onClose={() => setAdding(false)} />
			<UserEditModal
				user={editing}
				open={editing != null}
				onClose={() => setEditing(null)}
			/>
		</Card>
	);
};
