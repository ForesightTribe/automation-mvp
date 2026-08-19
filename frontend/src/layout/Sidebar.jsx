import { NavLink } from "react-router-dom";
import { NAV_ITEMS } from "../config/nav";
import { useAuth } from "../context/AuthContext";

/**
 * Left rail — icon-only at rest, expanding to show labels on hover. Renders
 * entirely from config/nav.js: add a page there, not here.
 *
 * Layout rule: the rail is an OVERLAY. A spacer reserves only its collapsed
 * width, so the workspace never moves; the rail itself is absolutely positioned,
 * so expanding it covers the content rather than pushing it. Requires a
 * `relative` ancestor — see AppLayout.
 *
 * Animation rule: ONLY `width` and `opacity` move. Everything else is identical
 * in both states, because the tempting alternatives don't interpolate —
 * `width: 0 → auto` and `justify-content: center → start` both snap in one
 * frame, which made the label pop in and the icon jump ahead of the panel. So
 * the icon keeps a constant 12px left inset (1px off-centre in a 44px box, not
 * perceptible) and the label is simply revealed by the item widening under
 * `overflow-hidden`. Symmetric in both directions as a result.
 */
export const Sidebar = () => {
	const { isAdmin } = useAuth();
	// Members don't see adminOnly items (e.g. Settings).
	const items = NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin);

	return (
		<>
			{/* Reserves the collapsed footprint only — must match the rail's
			    collapsed width at every breakpoint. */}
			<div className="w-16 shrink-0 lg:w-22" aria-hidden="true" />

			{/* `scrollbar-gutter: stable` reserves the scrollbar's space whether or
			    not it is showing, so a short viewport can't shift the icons. */}
			<aside
				style={{ scrollbarGutter: "stable" }}
				className="group absolute inset-y-0 left-0 z-20 flex w-16 flex-col items-center gap-1 overflow-x-hidden overflow-y-auto border-r border-border bg-card pt-6 pb-4 transition-[width,box-shadow] duration-300 ease-out hover:w-56 lg:w-22 lg:pt-10 lg:hover:w-60 xl:pt-12 2xl:pt-14"
			>
				{items.map(({ label, path, icon: Icon }) => (
					<NavLink
						key={path}
						to={path}
						title={label}
						aria-label={label}
						className={({ isActive }) =>
							`flex h-11 w-11 items-center gap-3 overflow-hidden rounded-xl pl-3 transition-[width,background-color,color] duration-300 ease-out group-hover:w-52 ${
								isActive
									? "bg-brand text-on-brand group-hover:bg-linear-to-r group-hover:from-brand group-hover:to-brand-deep"
									: "text-content hover:bg-linear-to-r hover:from-[#fff0f0] hover:to-[#ffd6d8] hover:text-[#d41b25]"
							}`
						}
					>
						<Icon
							size={18}
							strokeWidth={1.5}
							className="shrink-0"
							aria-hidden="true"
						/>
						<span className="text-sm font-medium whitespace-nowrap opacity-0 transition-opacity duration-300 ease-out group-hover:opacity-100">
							{label}
						</span>
					</NavLink>
				))}
			</aside>
		</>
	);
};
