import { useEffect } from "react";

/**
 * A right-hand slide-over for detail views — the "go deep without cluttering the
 * page" layer. One shell for every drawer (store, product, …) so they stay
 * consistent and roomy instead of each reinventing a cramped panel.
 *
 * Layout is three fixed regions: a header, an optional stat strip, and a scrolling
 * body — the body is the only thing that scrolls, so the header and stats stay put.
 * Renders nothing until `open`, and Esc / scrim-click both close it.
 */
export const Drawer = ({ open, onClose, title, subtitle, stats, children }) => {
	useEffect(() => {
		if (!open) return;
		const onKey = (e) => e.key === "Escape" && onClose?.();
		window.addEventListener("keydown", onKey);
		// Lock the page behind the drawer so only the panel scrolls.
		document.body.style.overflow = "hidden";
		return () => {
			window.removeEventListener("keydown", onKey);
			document.body.style.overflow = "";
		};
	}, [open, onClose]);

	if (!open) return null;

	return (
		<div className="fixed inset-0 z-50 flex justify-end">
			<button
				type="button"
				aria-label="Close"
				className="absolute inset-0 bg-black/40 backdrop-blur-[1px]"
				onClick={onClose}
			/>
			<aside className="relative flex h-full w-full max-w-xl flex-col overflow-hidden border-l border-border bg-card shadow-2xl">
				<header className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
					<div className="min-w-0">
						<h2 className="truncate font-display text-lg font-bold text-content">
							{title}
						</h2>
						{subtitle && (
							<p className="mt-0.5 truncate text-xs text-content-subtle">
								{subtitle}
							</p>
						)}
					</div>
					<button
						type="button"
						onClick={onClose}
						className="shrink-0 rounded-md p-1.5 text-content-subtle hover:bg-surface-subtle hover:text-content"
						aria-label="Close"
					>
						<svg width="18" height="18" viewBox="0 0 20 20" fill="none">
							<path
								d="M5 5l10 10M15 5L5 15"
								stroke="currentColor"
								strokeWidth="1.6"
								strokeLinecap="round"
							/>
						</svg>
					</button>
				</header>

				{stats && (
					<div className="grid grid-cols-3 gap-px border-b border-border bg-border">
						{stats}
					</div>
				)}

				<div className="flex-1 overflow-auto px-6 py-5">{children}</div>
			</aside>
		</div>
	);
};

/** One figure in a drawer's stat strip. `hint` carries the plain-language unit — a
 *  raw count like "292" is ambiguous without "product×store not carried". */
export const DrawerStat = ({ label, value, hint, tone }) => (
	<div className="bg-card px-4 py-3">
		<p className="text-[11px] uppercase tracking-wide text-content-subtle">
			{label}
		</p>
		<p
			className={`mt-0.5 font-display text-xl font-bold ${
				tone === "danger"
					? "text-danger"
					: tone === "warning"
						? "text-warning"
						: tone === "success"
							? "text-success"
							: "text-content"
			}`}
		>
			{value}
		</p>
		{hint && <p className="mt-0.5 text-[11px] leading-tight text-content-subtle">{hint}</p>}
	</div>
);

/** Shared three-state pill: in stock / out of stock / not carried. */
export const AvailabilityPill = ({ listed, inStock }) => {
	if (!listed)
		return (
			<span className="whitespace-nowrap rounded-full bg-surface-subtle px-2.5 py-0.5 text-xs text-content-subtle">
				Not carried
			</span>
		);
	if (!inStock)
		return (
			<span className="whitespace-nowrap rounded-full bg-danger/10 px-2.5 py-0.5 text-xs font-medium text-danger">
				Out of stock
			</span>
		);
	return (
		<span className="whitespace-nowrap rounded-full bg-success/10 px-2.5 py-0.5 text-xs font-medium text-success">
			In stock
		</span>
	);
};
