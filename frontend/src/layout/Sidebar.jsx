import { NavLink, useLocation } from "react-router-dom";
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
 *
 * Groups: an item may carry `children`, in which case its own row is a heading
 * rather than a link and the children are revealed with the labels on hover.
 * This branch runs ONLY for items that declare `children`; an item without it
 * takes the plain-link path. A collapsed rail has no room to show a submenu,
 * which is why the children appear with the labels rather than needing a
 * separate expand affordance.
 */
const ITEM_BASE =
	"flex h-11 w-11 items-center gap-3 overflow-hidden rounded-xl pl-3 transition-[width,background-color,color] duration-300 ease-out group-hover:w-52";
const ACTIVE =
	"bg-brand text-on-brand group-hover:bg-linear-to-r group-hover:from-brand group-hover:to-brand-deep";
const IDLE =
	"text-content hover:bg-linear-to-r hover:from-[#fff0f0] hover:to-[#ffd6d8] hover:text-[#d41b25]";
const LABEL =
	"text-sm font-medium whitespace-nowrap opacity-0 transition-opacity duration-300 ease-out group-hover:opacity-100";

/**
 * Which nav path owns the current URL.
 *
 * A path owns the URL when the URL is that path or sits beneath it, and where several
 * qualify the LONGEST one wins. Both halves matter: `/products` has to stay lit on
 * `/products/AB12`, which it only does by claiming what sits beneath it, while
 * `/ads/insights` has to belong to the AdsBeta child rather than to `/ads`, which it only
 * does because the child's path is longer. Exactly one entry is lit for any URL.
 */
const ownerOf = (pathname, items) =>
	items
		.flatMap((i) => [
			...(i.path ? [i.path] : []),
			...(i.children ?? []).map((c) => c.path),
		])
		.filter((p) => pathname === p || pathname.startsWith(`${p}/`))
		.sort((a, b) => b.length - a.length)[0] ?? null;

const NavGroup = ({ item, owner }) => {
	const Icon = item.icon;
	// The heading highlights when the current page is the group's own or any child's, so a
	// collapsed rail still shows which section you are in.
	const onOwnPage = item.path === owner;
	const active = onOwnPage || item.children.some((c) => c.path === owner);

	return (
		<div className="flex flex-col items-center">
			{/* The parent is the section's OWN page when it has a path, so a group does not
			    hide the page it is named after; it falls back to a plain heading otherwise. */}
			{item.path ? (
				<NavLink
					to={item.path}
					title={item.label}
					className={`${ITEM_BASE} ${onOwnPage ? ACTIVE : active ? "text-brand" : IDLE}`}
				>
					<Icon size={18} strokeWidth={1.5} className="shrink-0" />
					<span className={LABEL}>{item.label}</span>
				</NavLink>
			) : (
				<div
					title={item.label}
					aria-hidden="true"
					className={`${ITEM_BASE} ${active ? "text-brand" : "text-content"}`}
				>
					<Icon size={18} strokeWidth={1.5} className="shrink-0" />
					<span className={LABEL}>{item.label}</span>
				</div>
			)}

			<div className="hidden w-52 flex-col gap-0.5 pb-1 group-hover:flex">
				{item.children.map((child) => (
					<NavLink
						key={child.path}
						to={child.path}
						title={child.label}
						className={`ml-6 flex h-9 items-center rounded-lg px-3 text-sm font-medium whitespace-nowrap transition-colors ${
							child.path === owner
								? "bg-brand text-on-brand"
								: "text-content-muted hover:bg-muted hover:text-content"
						}`}
					>
						{child.label}
					</NavLink>
				))}
			</div>
		</div>
	);
};

export const Sidebar = () => {
	const { isAdmin } = useAuth();
	const { pathname } = useLocation();
	// Members don't see adminOnly items (e.g. Settings).
	const items = NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin);
	const owner = ownerOf(pathname, items);

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
				{items.map((item) =>
					item.children ? (
						// A group need not have a page of its own, so its label is the stable key.
						<NavGroup
							key={item.path ?? item.label}
							item={item}
							owner={owner}
						/>
					) : (
						<NavLink
							key={item.path}
							to={item.path}
							title={item.label}
							aria-label={item.label}
							className={`${ITEM_BASE} ${item.path === owner ? ACTIVE : IDLE}`}
						>
							<item.icon
								size={18}
								strokeWidth={1.5}
								className="shrink-0"
								aria-hidden="true"
							/>
							<span className={LABEL}>{item.label}</span>
						</NavLink>
					),
				)}
			</aside>
		</>
	);
};
