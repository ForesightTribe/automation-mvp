import { useCallback, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { ChevronsLeft, ChevronsRight } from "lucide-react";
import { NAV_ITEMS } from "../config/nav";
import { Logo } from "./Logo";
import { useAuth } from "../context/AuthContext";
import { STORAGE_KEYS } from "../lib/constants";

/**
 * Left rail — primary navigation, rendered from config/nav.js.
 *
 * Two elements, two widths: the outer div reserves the column, the inner <aside>
 * is absolutely positioned inside it.
 *   - Toggle: changes both. Page reflows, choice persisted to localStorage.
 *   - Hover on a collapsed rail: changes only the aside. Overlays, no reflow.
 *
 * z-40 — above sticky table headers (z-30), below portalled drawers and dialogs.
 */
const ITEM_BASE =
	"flex h-12 w-11 items-center gap-3 overflow-hidden rounded-xl pl-3 transition-[width,background-color,color] duration-300 ease-out";
const ACTIVE = "bg-brand text-on-brand";
const ACTIVE_WIDE = "bg-linear-to-r from-brand to-brand-deep";
const IDLE =
	"text-content hover:bg-linear-to-r hover:from-[#fff0f0] hover:to-[#ffd6d8] hover:text-[#d41b25]";
const LABEL =
	"text-[15px] font-medium whitespace-nowrap transition-opacity duration-300 ease-out";

// The rail's two widths. Anything sized to the rail reads them from here.
const RAIL_OPEN = "w-56 lg:w-60";
const RAIL_SHUT = "w-16 lg:w-22";
const ITEM_OPEN = "w-full";

/**
 * The nav path that owns the current URL: an exact match or an ancestor of it,
 * longest wins. Keeps /products lit on /products/AB12, and gives /ads/insights
 * to the Ads child rather than to /ads. Exactly one entry is lit for any URL.
 */
const ownerOf = (pathname, items) =>
	items
		.flatMap((i) => [
			...(i.path ? [i.path] : []),
			...(i.children ?? []).map((c) => c.path),
		])
		.filter((p) => pathname === p || pathname.startsWith(`${p}/`))
		.sort((a, b) => b.length - a.length)[0] ?? null;

const NavGroup = ({ item, owner, open }) => {
	const Icon = item.icon;
	const onOwnPage = item.path === owner;
	const active = onOwnPage || item.children.some((c) => c.path === owner);

	return (
		// w-full: without it the wrapper is content-sized and the group indents.
		<div className="flex w-full flex-col items-center">
			{/* A group with a path links to its own page; otherwise it is a heading. */}
			{item.path ? (
				<NavLink
					to={item.path}
					title={item.label}
					className={`${ITEM_BASE} ${open ? ITEM_OPEN : ""} ${
						onOwnPage
							? `${ACTIVE} ${open ? ACTIVE_WIDE : ""}`
							: active
								? "text-brand"
								: IDLE
					}`}
				>
					<Icon size={19} strokeWidth={1.6} className="shrink-0" />
					<span
						className={`${LABEL} ${open ? "opacity-100" : "opacity-0"}`}
					>
						{item.label}
					</span>
				</NavLink>
			) : (
				<div
					title={item.label}
					aria-hidden="true"
					className={`${ITEM_BASE} ${open ? ITEM_OPEN : ""} ${active ? "text-brand" : "text-content"}`}
				>
					<Icon size={19} strokeWidth={1.6} className="shrink-0" />
					<span
						className={`${LABEL} ${open ? "opacity-100" : "opacity-0"}`}
					>
						{item.label}
					</span>
				</div>
			)}

			<div
				className={`${ITEM_OPEN} flex-col gap-0.5 pb-1 ${open ? "flex" : "hidden"}`}
			>
				{item.children.map((child) => (
					<NavLink
						key={child.path}
						to={child.path}
						title={child.label}
						// ml-10 lines a child's text up under its parent's.
						className={`ml-10 flex h-10 items-center rounded-lg px-3 text-sm font-medium whitespace-nowrap transition-colors ${
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
	const [hovered, setHovered] = useState(false);
	const [collapsed, setCollapsed] = useState(
		() => localStorage.getItem(STORAGE_KEYS.sidebarCollapsed) === "true",
	);

	const toggle = useCallback(
		() =>
			setCollapsed((was) => {
				localStorage.setItem(
					STORAGE_KEYS.sidebarCollapsed,
					String(!was),
				);
				return !was;
			}),
		[],
	);

	// How the rail looks, vs. how much room it takes. These differ only on hover.
	const open = !collapsed || hovered;
	const floating = collapsed && hovered;
	// Members don't see adminOnly items (e.g. Settings).
	const items = NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin);
	const owner = ownerOf(pathname, items);

	return (
		<div
			className={`relative h-full shrink-0 transition-[width] duration-300 ease-out ${
				collapsed ? RAIL_SHUT : RAIL_OPEN
			}`}
		>
			<aside
				style={{ scrollbarGutter: "stable" }}
				onMouseEnter={() => setHovered(true)}
				onMouseLeave={() => setHovered(false)}
				className={`absolute inset-y-0 left-0 z-40 flex flex-col items-center gap-1 overflow-x-hidden overflow-y-auto border-r border-border bg-card px-2.5 pb-4 gap-0.5 transition-[width,box-shadow] duration-300 ease-out ${
					open ? RAIL_OPEN : RAIL_SHUT
				} ${floating ? "shadow-xl" : ""}`}
			>
				{/* 57px matches the navbar height; the negative margin lets the
				    bottom rule span the rail's full width. */}
				<div
					className={`-mx-2.5 mb-3 flex h-[57px] w-[calc(100%+1.25rem)] shrink-0 items-center border-b border-border px-2.5 ${
						open ? "justify-between" : "justify-center"
					}`}
				>
					<Logo showWordmark={open} />
					{open && (
						<button
							type="button"
							onClick={toggle}
							aria-expanded={!collapsed}
							title={
								collapsed
									? "Expand sidebar"
									: "Collapse sidebar"
							}
							aria-label={
								collapsed
									? "Expand sidebar"
									: "Collapse sidebar"
							}
							className="rounded-md p-1.5 text-content-subtle transition-colors hover:bg-muted hover:text-brand"
						>
							{collapsed ? (
								<ChevronsRight size={16} strokeWidth={1.75} />
							) : (
								<ChevronsLeft size={16} strokeWidth={1.75} />
							)}
						</button>
					)}
				</div>

				{items.map((item) =>
					item.children ? (
						// Keyed on label: a group need not have a path.
						<NavGroup
							key={item.path ?? item.label}
							item={item}
							owner={owner}
							open={open}
						/>
					) : (
						<NavLink
							key={item.path}
							to={item.path}
							title={item.label}
							aria-label={item.label}
							className={`${ITEM_BASE} shrink-0 ${open ? ITEM_OPEN : ""} ${
								item.path === owner
									? `${ACTIVE} ${open ? ACTIVE_WIDE : ""}`
									: IDLE
							}`}
						>
							<item.icon
								size={18}
								strokeWidth={1.5}
								className="shrink-0"
								aria-hidden="true"
							/>
							<span
								className={`${LABEL} ${open ? "opacity-100" : "opacity-0"}`}
							>
								{item.label}
							</span>
							{/* Expanded only — a collapsed row has no room for it. */}
							{item.badge && open && (
								<span
									// -ml-1 keeps the longest label + badge inside the rail.
									className={`badge-new -ml-1 shrink-0 rounded-full bg-linear-to-r from-info to-primary px-1 py-0.5 text-[9px] font-semibold tracking-wide text-on-primary uppercase ${
										// Ring separates the blue from the active row's red.
										item.path === owner
											? "ring-1 ring-on-brand/70"
											: ""
									}`}
								>
									{item.badge}
								</span>
							)}
						</NavLink>
					),
				)}
			</aside>
		</div>
	);
};
