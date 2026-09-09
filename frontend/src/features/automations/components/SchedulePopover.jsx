import { useEffect, useRef, useState } from "react";
import { StatusPill } from "./StatusPill";
import { describeWindow, nextOpening, windowsOf, WHEN } from "../automation";
import { formatCurrency } from "../../../lib/format";

/**
 * The status pill, clickable: "Scheduled" answers the obvious question, which is scheduled
 * for WHEN. The windows are already on the row, so this needs no request.
 *
 * Only rows that actually carry a window become clickable. A pill that opens an empty
 * popover would be worse than one that does nothing.
 */
export const SchedulePopover = ({ row }) => {
	const [at, setAt] = useState(null); // viewport coords, or null when closed
	const wrap = useRef(null);
	const open = at != null;

	// ⚠️ Positioned FIXED, not absolute. The table body is an `overflow-auto` container, which
	// clips an absolutely-positioned panel — on the lower rows it would be cut off or hidden
	// entirely. Fixed escapes the clip; the coordinates come from the pill's own rect, and the
	// panel flips above the pill when there is no room below.
	const toggle = () => {
		if (open) return setAt(null);
		const r = wrap.current?.getBoundingClientRect();
		if (!r) return;
		const below = window.innerHeight - r.bottom;
		setAt(
			below > 220
				? { left: r.left, top: r.bottom + 6, place: "below" }
				: { left: r.left, top: r.top - 6, place: "above" },
		);
	};
	const windows = windowsOf(row);
	const next = nextOpening(row);

	useEffect(() => {
		if (!open) return;
		const onDown = (e) => {
			if (wrap.current && !wrap.current.contains(e.target)) setAt(null);
		};
		const onKey = (e) => e.key === "Escape" && setAt(null);
		// The panel is anchored to a rect measured once, so it must not linger while the
		// page or the table scrolls out from under it.
		const onScroll = () => setAt(null);
		window.addEventListener("scroll", onScroll, true);
		document.addEventListener("mousedown", onDown);
		document.addEventListener("keydown", onKey);
		return () => {
			document.removeEventListener("mousedown", onDown);
			document.removeEventListener("keydown", onKey);
			window.removeEventListener("scroll", onScroll, true);
		};
	}, [open]);

	if (!windows.length) return <StatusPill status={row.status} />;

	return (
		<span ref={wrap} className="relative inline-flex">
			<button
				type="button"
				aria-expanded={open}
				onClick={toggle}
				title="See when this runs"
				className="rounded-full transition-opacity hover:opacity-80"
			>
				<StatusPill status={row.status} />
			</button>

			{open && (
				<span
					style={{
						left: at.left,
						top: at.top,
						transform:
							at.place === "above"
								? "translateY(-100%)"
								: undefined,
					}}
					className="fixed z-[70] w-72 rounded-lg border border-border bg-card p-3 text-left shadow-xl"
				>
					<span className="mb-1.5 block text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
						{windows.length === 1
							? "Window"
							: `${windows.length} windows`}
					</span>
					<ul className="space-y-1">
						{windows.map((w, i) => (
							<li key={i} className="text-sm text-content">
								{describeWindow(w)}
								{w.budget != null && (
									<span className="text-content-muted">
										{" "}
										at {formatCurrency(w.budget)}
									</span>
								)}
							</li>
						))}
					</ul>
					<span className="mt-2 block border-t border-border pt-2 text-xs text-content-muted">
						{next
							? `Next opens ${WHEN.format(next)}`
							: "No upcoming opening"}
					</span>
				</span>
			)}
		</span>
	);
};
