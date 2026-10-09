import { useEffect, useRef, useState } from "react";
import { LogOut, User } from "lucide-react";
import { useAuth } from "../context/AuthContext";

/**
 * Who is signed in, and the way out — an icon in the navbar, everything else behind
 * a click.
 *
 * The email is not worth a permanent slot in the bar: it is looked at when something
 * seems wrong, not while reading a page, and spelled out in full it takes more width
 * than any control that actually does something. The icon holds the place; the panel
 * answers the question.
 */
export const ProfileMenu = () => {
	const { user, logout } = useAuth();
	const [open, setOpen] = useState(false);
	const wrap = useRef(null);

	useEffect(() => {
		if (!open) return;
		const onDown = (e) => {
			if (!wrap.current?.contains(e.target)) setOpen(false);
		};
		const onEsc = (e) => e.key === "Escape" && setOpen(false);
		document.addEventListener("mousedown", onDown);
		document.addEventListener("keydown", onEsc);
		return () => {
			document.removeEventListener("mousedown", onDown);
			document.removeEventListener("keydown", onEsc);
		};
	}, [open]);

	const initial = (user?.email ?? "?").trim().charAt(0).toUpperCase();

	return (
		<div ref={wrap} className="relative">
			<button
				type="button"
				onClick={() => setOpen((o) => !o)}
				aria-haspopup="menu"
				aria-expanded={open}
				aria-label="Account"
				title={user?.email ?? "Account"}
				className={`flex h-8 w-8 items-center justify-center rounded-full border transition-colors ${
					open
						? "border-content-subtle bg-inverse text-on-inverse"
						: "border-border bg-card text-content-muted hover:border-content-subtle hover:text-content"
				}`}
			>
				{user ? (
					<span className="text-xs font-semibold">{initial}</span>
				) : (
					<User size={16} strokeWidth={1.75} />
				)}
			</button>

			{open && (
				<div
					role="menu"
					className="absolute right-0 z-50 mt-2 w-60 rounded-xl border border-border bg-card p-1.5 shadow-xl"
				>
					<div className="px-2.5 py-2">
						<p className="text-[11px] text-content-subtle">
							Signed in as
						</p>
						{/* The email is the only unambiguous identifier here, so it wraps
						    rather than being truncated away. */}
						<p className="text-sm leading-snug font-medium break-all text-content">
							{user?.email ?? "—"}
						</p>
					</div>
					<div className="my-1 border-t border-border" />
					<button
						type="button"
						role="menuitem"
						onClick={logout}
						className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm font-medium text-content transition-colors hover:bg-danger hover:text-on-primary"
					>
						<LogOut size={15} strokeWidth={1.75} />
						Log out
					</button>
				</div>
			)}
		</div>
	);
};
