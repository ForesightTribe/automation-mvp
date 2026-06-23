import { useAuth } from "../context/AuthContext";
import { useClient } from "../context/ClientContext";
import { Button } from "../components/ui/Button";
import { DateRangePicker } from "./DateRangePicker";

/**
 * Top bar: client switcher (left) + user/logout (right). The switcher writes to
 * ClientContext; because feature queries key on the active client id, changing
 * it here triggers their refetch automatically.
 */
export const Navbar = () => {
	const { user, logout } = useAuth();
	const { clients, activeClientId, setActiveClient, clientsLoading } =
		useClient();

	return (
		<header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-card px-6">
			<div className="flex items-center gap-3">
				<label className="text-xs font-medium text-content-subtle">
					Client
				</label>
				<select
					value={activeClientId ?? ""}
					onChange={(e) => setActiveClient(e.target.value)}
					disabled={clientsLoading || clients.length === 0}
					className="rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium text-content disabled:opacity-50"
				>
					{clients.length === 0 && (
						<option value="">No clients</option>
					)}
					{clients.map((c) => (
						<option key={c.id} value={c.id}>
							{c.name}
						</option>
					))}
				</select>

				<DateRangePicker />
			</div>

			<div className="flex items-center gap-4">
				{user && (
					<span className="text-sm text-content-muted">
						{user.email}
					</span>
				)}
				<Button variant="secondary" size="sm" onClick={logout}>
					Log out
				</Button>
			</div>
		</header>
	);
};
