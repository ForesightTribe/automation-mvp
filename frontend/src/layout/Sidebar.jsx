import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { ChevronsLeft, ChevronsRight } from "lucide-react";
import { NAV_ITEMS } from "../config/nav";
import { Logo } from "./Logo";
import { useAuth } from "../context/AuthContext";
import { STORAGE_KEYS } from "../lib/constants";

/**
 * Left rail — labels and all by default, collapsible to icons. Renders entirely from
 * config/nav.js: add a page there, not here. It also owns the CLIENT picker, which
 * sits here rather than in the navbar because the client scopes the whole app, the
 * way the rail itself does.
 *
 * Layout rule: the rail owns the shell's whole left COLUMN, top-left corner and
 * all. It reserves its width as an ordinary flex child, so the navbar and the page
 * are simply the space left over and collapsing it widens both.
 *
 * It carries the product mark and the navigation, and nothing else. Brand, dates,
 * marketplaces and account all live in the navbar beside it: those change what is on
 * screen, while this only changes where you are.
 *
 * It opens two ways, and they are deliberately different:
 *
 *  - The TOGGLE is a decision, so it PUSHES. The reserved width grows, the navbar
 *    and page reflow once, and the choice is remembered across reloads. Open is
 *    the default; collapsing is the deliberate act, so that is what gets stored.
 *  - HOVER is transient, so it OVERLAYS. The reserved width does not change and
 *    nothing reflows: a pointer drifting past the left edge must not move the page
 *    under the reader, and every chart on screen resizes when its column does.
 *
 * ⚠️ That is why the visible panel is absolutely positioned INSIDE the element that
 * reserves the space, rather than being that element. Two widths: the outer one
 * answers "how much room does the rail take", the inner one "how wide does it
 * look right now".
 *
 * The panel needs a z-index above anything a page can raise. Sticky table headers
 * and frozen first columns sit at z-30, so a lower rail lets a table paint over
 * it. It stays below the portalled layers (drawers, dialogs, selects, hints),
 * which are meant to cover the whole chrome.
 */
// h-12 and a 15px label, not the 14px used inside pages: these are the product's
// top-level destinations and the rail has the room, so they carry a little more
// weight than a control in a card header.
const ITEM_BASE =
	"flex h-12 w-11 items-center gap-3 overflow-hidden rounded-xl pl-3 transition-[width,background-color,color] duration-300 ease-out";
const ACTIVE = "bg-brand text-on-brand";
const ACTIVE_WIDE = "bg-linear-to-r from-brand to-brand-deep";
const IDLE =
	"text-content hover:bg-linear-to-r hover:from-[#fff0f0] hover:to-[#ffd6d8] hover:text-[#d41b25]";
const LABEL =
	"text-[15px] font-medium whitespace-nowrap transition-opacity duration-300 ease-out";

// The rail's two widths, at each breakpoint. Everything sized to the rail — the items,
// the submenus, the client tile — reads them from here so the column has one source of
// truth for how wide it is.
const RAIL_OPEN = "w-56 lg:w-60";
const RAIL_SHUT = "w-16 lg:w-22";
// Drag limits for the open rail. Below MIN there is not room for the longest label,
// and past MAX the rail starts taking space the page needs; dragging under SNAP
// collapses it, which is what a hard pull to the left means.
const MIN_W = 200;
const MAX_W = 420;
const SNAP_W = 150;
// Open, every row fills the rail's padded width, so the client tile, the nav labels
// and the submenu all start on the same left edge. Collapsed, a row is just the
// 44px icon box.
const ITEM_OPEN = "w-full";

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

const NavGroup = ({ item, owner, open }) => {
	const Icon = item.icon;
	// The heading highlights when the current page is the group's own or any child's, so a
	// collapsed rail still shows which section you are in.
	const onOwnPage = item.path === owner;
	const active = onOwnPage || item.children.some((c) => c.path === owner);

	return (
		// ⚠️ `w-full`. Without it this wrapper is content-sized, and the heading's own
		// full-width row resolves against the wrapper rather than the rail — so a group
		// sat indented from every plain link beside it.
		<div className="flex w-full flex-col items-center">
			{/* The parent is the section's OWN page when it has a path, so a group does not
			    hide the page it is named after; it falls back to a plain heading otherwise. */}
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
						// ml-10 puts a child's text under its parent's text: the row's own
						// pl-3, the 19px icon and the 12px gap come to ~43px.
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
	// A width the reader chose by dragging. Null means "whatever the class says",
	// so an untouched rail keeps its responsive default.
	const [width, setWidth] = useState(() => {
		const stored = Number(localStorage.getItem(STORAGE_KEYS.sidebarWidth));
		return stored >= MIN_W && stored <= MAX_W ? stored : null;
	});
	const [dragging, setDragging] = useState(false);
	const frame = useRef(0);

	// Drag on the window, not the handle: the pointer routinely outruns a 6px strip,
	// and a resize that stops when the cursor slips off it feels broken.
	useEffect(() => {
		if (!dragging) return;
		const onMove = (e) => {
			cancelAnimationFrame(frame.current);
			frame.current = requestAnimationFrame(() => {
				const next = Math.round(e.clientX);
				if (next < SNAP_W) {
					setCollapsed(true);
					localStorage.setItem(STORAGE_KEYS.sidebarCollapsed, "true");
					setDragging(false);
					return;
				}
				const clamped = Math.min(MAX_W, Math.max(MIN_W, next));
				setWidth(clamped);
				if (collapsed) {
					setCollapsed(false);
					localStorage.setItem(
						STORAGE_KEYS.sidebarCollapsed,
						"false",
					);
				}
			});
		};
		const stop = () => setDragging(false);
		window.addEventListener("pointermove", onMove);
		window.addEventListener("pointerup", stop);
		// The whole window takes the resize cursor, and text stops selecting under it.
		const prev = document.body.style.cssText;
		document.body.style.cursor = "col-resize";
		document.body.style.userSelect = "none";
		return () => {
			window.removeEventListener("pointermove", onMove);
			window.removeEventListener("pointerup", stop);
			cancelAnimationFrame(frame.current);
			document.body.style.cssText = prev;
		};
	}, [dragging, collapsed]);

	// Persist only when the drag ends, not on every frame.
	useEffect(() => {
		if (!dragging && width) {
			localStorage.setItem(STORAGE_KEYS.sidebarWidth, String(width));
		}
	}, [dragging, width]);

	// Double-click the handle to go back to the default width.
	const resetWidth = useCallback(() => {
		setWidth(null);
		localStorage.removeItem(STORAGE_KEYS.sidebarWidth);
	}, []);

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

	// What the rail LOOKS like versus how much room it TAKES. They differ only while
	// a collapsed rail is hovered, which is exactly the case that must not reflow.
	const open = !collapsed || hovered;
	const floating = collapsed && hovered;
	// Members don't see adminOnly items (e.g. Settings).
	const items = NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin);
	const owner = ownerOf(pathname, items);

	// A dragged width only applies to the open rail: collapsed is a fixed icon strip,
	// and the hover overlay must not change the room the column reserves.
	const sized = width && !collapsed ? { width } : undefined;
	const motion = dragging ? "" : "transition-[width] duration-300 ease-out";

	return (
		<div
			style={sized}
			className={`relative h-full shrink-0 ${motion} ${
				width && !collapsed ? "" : collapsed ? RAIL_SHUT : RAIL_OPEN
			}`}
		>
			<aside
				style={{
					scrollbarGutter: "stable",
					...(width && open ? { width } : {}),
				}}
				onMouseEnter={() => setHovered(true)}
				onMouseLeave={() => setHovered(false)}
				className={`absolute inset-y-0 left-0 z-40 flex flex-col items-center gap-1 overflow-x-hidden overflow-y-auto border-r border-border bg-card px-2.5 pb-4 gap-0.5 ${
					dragging
						? ""
						: "transition-[width,box-shadow] duration-300 ease-out"
				} ${width && open ? "" : open ? RAIL_OPEN : RAIL_SHUT} ${
					floating ? "shadow-xl" : ""
				}`}
			>
				{/* The corner the rail owns, at exactly the navbar's height and
				    carrying the same bottom rule, so the two read as one bar across the top
				    and the first menu item starts on the page's own top line. The negative
				    margin lets that rule reach both edges of the rail rather than stopping
				    at its padding.

				    The chevrons point the way the column is about to move; the toggle shows
				    only once the rail is open, since a collapsed one has no room for a
				    control whose whole purpose is changing how wide it is, and hovering
				    reveals it. */}
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
						// A group need not have a page of its own, so its label is the stable key.
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
						</NavLink>
					),
				)}
			</aside>

			{/* The drag edge. It sits on the rail's right border, not inside the scrolling
			    panel, so it stays put while the menu scrolls. Keyboard users get the same
			    range with the arrow keys; double-click returns the default width. */}
			<div
				role="separator"
				aria-orientation="vertical"
				aria-label="Resize sidebar"
				aria-valuenow={width ?? undefined}
				aria-valuemin={MIN_W}
				aria-valuemax={MAX_W}
				tabIndex={0}
				title="Drag to resize · double-click to reset"
				onPointerDown={(e) => {
					e.preventDefault();
					setDragging(true);
				}}
				onDoubleClick={resetWidth}
				onKeyDown={(e) => {
					const step = e.shiftKey ? 32 : 8;
					if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
						e.preventDefault();
						const base = width ?? 240;
						setWidth(
							Math.min(
								MAX_W,
								Math.max(
									MIN_W,
									base +
										(e.key === "ArrowRight" ? step : -step),
								),
							),
						);
					}
				}}
				className={`group absolute inset-y-0 right-0 z-50 w-1.5 translate-x-1/2 cursor-col-resize focus-visible:outline-none ${
					collapsed && !hovered ? "hidden" : ""
				}`}
			>
				<span
					aria-hidden
					className={`absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 rounded-full transition-colors ${
						dragging
							? "bg-brand"
							: "bg-transparent group-hover:bg-brand/40 group-focus-visible:bg-brand"
					}`}
				/>
			</div>
		</div>
	);
};
