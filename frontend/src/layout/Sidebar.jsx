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
 * the icon keeps a left inset and the label is simply revealed by the item
 * widening under `overflow-hidden`. Symmetric in both directions as a result.
 *
 * The inset is `(box width − icon width) / 2`, computed by hand per
 * breakpoint since it can't be `justify-center` (see above): 14px centers a
 * 16px icon in the 44px box; at 2xl the icon grows to 22px, so the inset
 * drops to 11px to keep it centered rather than drifting off toward one edge.
 */
export const Sidebar = () => {
	const { isAdmin } = useAuth();
	// Members don't see adminOnly items (e.g. Settings).
	const items = NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin);

	return (
		<>
			{/* Reserves the collapsed footprint only — must match the rail's
			    collapsed width at every breakpoint. */}
			<div className="w-12 shrink-0 lg:w-16" aria-hidden="true" />

			{/* The scrollbar is hidden rather than gutter-reserved: any reserved
			    gutter takes real width off one side and breaks the icons' symmetry.
			    The rail still scrolls, it just doesn't show a bar. */}
			<aside
				className="group absolute inset-y-0 left-0 z-20 flex w-12 flex-col items-center gap-1 overflow-x-hidden overflow-y-auto border-r [scrollbar-width:none] [&::-webkit-scrollbar]:hidden border-border bg-card pt-3 pb-4 transition-[width,box-shadow] duration-300 ease-out hover:w-56 lg:w-16 lg:pt-4 lg:hover:w-60 xl:pt-5 2xl:pt-6 2xl:hover:w-80"
			>
				{items.map(({ label, path, icon: Icon }) => (
					<NavLink
						key={path}
						to={path}
						title={label}
						aria-label={label}
						className={({ isActive }) =>
							`flex h-11 w-11 items-center gap-3 overflow-hidden rounded-xl pl-3.5 transition-[width,background-color,color] duration-300 ease-out group-hover:w-52 2xl:pl-2.75 2xl:group-hover:w-72 ${
								isActive
									? "bg-brand text-on-brand group-hover:bg-linear-to-r group-hover:from-brand group-hover:to-brand-deep"
									: "text-content hover:bg-linear-to-r hover:from-[#fff0f0] hover:to-[#ffd6d8] hover:text-[#d41b25]"
							}`
						}
					>
						<Icon
							strokeWidth={1.5}
							className="h-4 w-4 shrink-0 2xl:h-5.5 2xl:w-5.5"
							aria-hidden="true"
						/>
						<span className="text-[13px] font-medium whitespace-nowrap opacity-0 transition-opacity duration-300 ease-out group-hover:opacity-100 2xl:text-lg">
							{label}
						</span>
					</NavLink>
				))}
			</aside>
		</>
	);
};
