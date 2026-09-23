import { useEffect } from "react";
import { X } from "lucide-react";

/**
 * A centred dialog for a task with more than one step. Header and footer are fixed;
 * the body scrolls. Esc and the close button call `onClose`; the scrim does not.
 */
export const Modal = ({
	open,
	onClose,
	title,
	subtitle,
	footer,
	size = "lg",
	bleed = false,
	children,
}) => {
	useEffect(() => {
		if (!open) return;
		const onKey = (e) => e.key === "Escape" && onClose?.();
		window.addEventListener("keydown", onKey);
		document.body.style.overflow = "hidden";
		return () => {
			window.removeEventListener("keydown", onKey);
			document.body.style.overflow = "";
		};
	}, [open, onClose]);

	if (!open) return null;

	const width = { md: "max-w-lg", lg: "max-w-3xl", xl: "max-w-5xl" }[size];

	return (
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-[1px]"
			role="dialog"
			aria-modal="true"
			aria-label={typeof title === "string" ? title : undefined}
		>
			<div
				className={`flex max-h-[min(90vh,52rem)] w-full ${width} flex-col overflow-hidden rounded-xl border border-border bg-card shadow-2xl`}
			>
				<header className="flex items-start justify-between gap-4 border-b border-border px-6 py-4 md:px-7">
					<div className="min-w-0">
						<h2 className="font-display text-lg font-bold text-content">
							{title}
						</h2>
						{subtitle && (
							<p className="mt-0.5 text-sm text-content-muted">
								{subtitle}
							</p>
						)}
					</div>
					<button
						type="button"
						onClick={onClose}
						aria-label="Close"
						className="rounded-md p-1.5 text-content-subtle transition-colors hover:bg-muted hover:text-content"
					>
						<X size={18} />
					</button>
				</header>
				{/* `bleed`: the child supplies its own padding. */}
				<div
					className={`min-h-0 flex-1 overflow-y-auto ${bleed ? "" : "px-6 py-5"}`}
				>
					{children}
				</div>
				{footer && (
					<footer className="border-t border-border bg-muted/40 px-6 py-3.5 md:px-7">
						{footer}
					</footer>
				)}
			</div>
		</div>
	);
};
