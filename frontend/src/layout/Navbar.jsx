import { useAuth } from "../context/AuthContext";
import { useClient } from "../context/ClientContext";
import { Button } from "../components/ui/Button";
import { DateRangePicker } from "./DateRangePicker";
import { MarketplacePicker } from "./MarketplacePicker";
import { ChevronDown } from "lucide-react";
import { Logo } from "./Logo";

/**
 * Top bar, in three zones: brand mark (left), the global selectors (centred),
 * account (right). The selector group takes the space between the flanks and
 * centres itself in it, so it stays visually mid-bar as the flanks change width.
 * Each selector writes to its own Context; because feature queries key on those
 * selections, changing one here triggers a refetch automatically.
 *
 * Responsive: one row on laptop, wraps to two on tablet — the row height grows
 * with `min-h` rather than being fixed, and the account email drops out below
 * `lg` where it costs more width than it earns.
 */
export const Navbar = () => {
	const { user, logout } = useAuth();
	const { clients, activeClientId, setActiveClient, clientsLoading } =
		useClient();

	return (
		<header className="flex min-h-14 shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-border bg-card px-4 py-2 lg:px-6 xl:px-8 2xl:px-10">
			<div className="shrink-0">
				<Logo />
			</div>

			<div className="flex flex-1 flex-wrap items-center justify-center gap-x-3 gap-y-2">
				<div className="flex items-center gap-2">
					<label className="text-sm font-normal text-content-muted">
						Client:
					</label>
					{/* `appearance-none` drops the browser's own arrow so the
					    chevron matches MarketplacePicker's. pr-9 leaves room for
					    it: 12px padding + 16px icon + 8px gap. */}
					<div className="relative">
						<select
							value={activeClientId ?? ""}
							onChange={(e) => setActiveClient(e.target.value)}
							disabled={clientsLoading || clients.length === 0}
							className="appearance-none rounded-md border border-border bg-card py-1.5 pr-9 pl-3 text-sm font-normal text-content disabled:opacity-50"
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
						<ChevronDown
							size={16}
							strokeWidth={1.5}
							aria-hidden="true"
							className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-content-subtle"
						/>
					</div>
				</div>

				<MarketplacePicker />

				<DateRangePicker />
			</div>

			<div className="flex shrink-0 items-center gap-3">
				{user && (
					<span className="hidden text-xs text-content-muted lg:inline">
						{user.email}
					</span>
				)}
				<Button variant="brand" size="sm" onClick={logout}>
					Log out
				</Button>
			</div>
		</header>
	);
};
