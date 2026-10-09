import { useState } from "react";
import { KeyRound, LogOut } from "lucide-react";
import { useAuth } from "../../../context/AuthContext";
import { Card } from "../../../components/ui/Card";
import { Button } from "../../../components/ui/Button";
import { ChangePasswordModal } from "../../account/ChangePasswordModal";

/**
 * Your own account: who you are signed in as, your password, and the way out.
 *
 * Shown to everyone, which is why Settings is no longer admin-only — a member
 * who could not reach this page would have no way to change the password an
 * admin chose for them, nor to sign out.
 */
export const AccountCard = () => {
	const { user, logout } = useAuth();
	const [pwOpen, setPwOpen] = useState(false);

	return (
		<Card title="Your account">
			<div className="flex flex-wrap items-end justify-between gap-4">
				<div className="flex flex-col gap-1">
					<span className="text-[11px] tracking-wide text-content-subtle uppercase">
						Signed in as
					</span>
					{/* The email is the only unambiguous identifier, so it wraps
					    rather than being truncated away. */}
					<span className="text-sm leading-snug font-medium break-all text-content">
						{user?.email ?? "—"}
					</span>
					<span className="text-xs text-content-muted capitalize">
						{user?.role ?? "—"}
					</span>
				</div>

				<div className="flex items-center gap-2">
					<Button variant="secondary" onClick={() => setPwOpen(true)}>
						<KeyRound size={14} /> Change password
					</Button>
					<Button variant="secondary" onClick={logout}>
						<LogOut size={14} /> Log out
					</Button>
				</div>
			</div>

			<ChangePasswordModal open={pwOpen} onClose={() => setPwOpen(false)} />
		</Card>
	);
};
