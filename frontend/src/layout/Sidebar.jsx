import { NavLink } from "react-router-dom";
import { NAV_ITEMS } from "../config/nav";
import { useAuth } from "../context/AuthContext";

/** Left rail. Renders entirely from config/nav.js — add a page there, not here. */
export const Sidebar = () => {
	const { isAdmin } = useAuth();
	// Members don't see adminOnly items (e.g. Settings).
	const items = NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin);

	return (
		<aside className="flex w-60 shrink-0 flex-col border-r border-border bg-card">
			<div className="flex h-14 items-center px-5 font-display text-lg font-bold text-content">
				Foresight
			</div>
			<nav className="flex flex-col gap-1 p-3">
				{items.map((item) => (
					<NavLink
						key={item.path}
						to={item.path}
						className={({ isActive }) =>
							`flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
								isActive
									? "bg-primary-soft text-primary"
									: "text-content-muted hover:bg-muted hover:text-content"
							}`
						}
					>
						<span className="w-4 text-center" aria-hidden="true">
							{item.icon}
						</span>
						{item.label}
					</NavLink>
				))}
			</nav>
		</aside>
	);
};
