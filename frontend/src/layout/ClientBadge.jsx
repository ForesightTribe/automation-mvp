import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { useClient } from "../context/ClientContext";

/**
 * The brand whose numbers are on screen.
 *
 * It shows the CLIENT rather than a field asking for one: the name is the answer, and
 * a "Client" caption above it only repeats what the value already says.
 *
 * Its chip is NEUTRAL, not brand red. Red is the product's accent — the mark, the
 * active nav item, the one obvious action on a screen — and spending it on a label
 * that never changes leaves the bar with two competing reds and no hierarchy.
 *
 * ⚠️ It is only a control when there is something to control. On an account with one
 * client there is nothing to pick, so it renders as a plain chip with no chevron and
 * nothing to click — a dropdown holding a single option is a dead end dressed up as a
 * choice. The list appears from two clients up.
 */
export const ClientBadge = () => {
	const { clients, activeClientId, setActiveClient, isLoading } = useClient();
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

	if (isLoading) return null;

	const active = clients.find((c) => c.id === activeClientId);
	const name = active?.name ?? "No client";
	const initial = name.trim().charAt(0).toUpperCase();

	const avatar = (
		<span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-inverse text-[11px] font-bold text-on-inverse">
			{initial}
		</span>
	);

	if (clients.length <= 1)
		return (
			<div className="flex items-center gap-2 rounded-lg border border-transparent px-2 py-1">
				{avatar}
				<span className="text-sm font-semibold text-content">
					{name}
				</span>
			</div>
		);

	return (
		<div ref={wrap} className="relative">
			<button
				type="button"
				onClick={() => setOpen((o) => !o)}
				aria-haspopup="listbox"
				aria-expanded={open}
				aria-label="Brand"
				className={`flex items-center gap-2 rounded-lg border px-2 py-1 transition-colors ${
					open
						? "border-content-subtle bg-muted"
						: "border-border bg-card hover:border-content-subtle"
				}`}
			>
				{avatar}
				<span className="text-sm font-semibold text-content">
					{name}
				</span>
				<ChevronDown
					size={14}
					className={`text-content-subtle transition-transform ${open ? "rotate-180" : ""}`}
				/>
			</button>

			{open && (
				<div
					role="listbox"
					className="absolute right-0 z-50 mt-2 w-56 rounded-xl border border-border bg-card p-1.5 shadow-xl"
				>
					{clients.map((c) => {
						const on = c.id === activeClientId;
						return (
							<button
								key={c.id}
								type="button"
								role="option"
								aria-selected={on}
								onClick={() => {
									setActiveClient(c.id);
									setOpen(false);
								}}
								className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors ${
									on
										? "bg-muted font-semibold text-content"
										: "font-medium text-content hover:bg-muted"
								}`}
							>
								<span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-muted text-[11px] font-bold text-content-muted">
									{c.name.trim().charAt(0).toUpperCase()}
								</span>
								<span className="flex-1 text-left">
									{c.name}
								</span>
								{on && <Check size={14} strokeWidth={2.5} />}
							</button>
						);
					})}
				</div>
			)}
		</div>
	);
};
