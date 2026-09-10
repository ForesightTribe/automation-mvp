import { useRef, useState } from "react";

/**
 * Tooltip in the app's own type and colour, replacing the browser's `title=`.
 *
 * A native tooltip is drawn by the OS: different font, different delay on every platform,
 * no way to style it, and it cannot show alongside a focus ring for keyboard users. This
 * renders the bubble ourselves.
 *
 * ⚠️ It is `position: fixed`, deliberately. These sit inside tables that scroll
 * (`overflow-auto`), and an absolutely-positioned bubble is clipped by that container —
 * the tooltip on the last column would simply not appear. Fixed escapes the clip; the
 * coordinates come from the trigger's own rect, measured when it is hovered.
 *
 * Shows on hover AND focus, so it is reachable by keyboard, and hides on Escape.
 */
export const Tooltip = ({ label, children, side = "top", className = "" }) => {
	const ref = useRef(null);
	const [at, setAt] = useState(null);

	const show = () => {
		const r = ref.current?.getBoundingClientRect();
		if (!r) return;
		setAt(
			side === "top"
				? { left: r.left + r.width / 2, top: r.top - 8, place: "top" }
				: {
						left: r.left + r.width / 2,
						top: r.bottom + 8,
						place: "bottom",
					},
		);
	};
	const hide = () => setAt(null);

	if (!label) return children;

	return (
		<span
			ref={ref}
			className={`inline-flex ${className}`}
			onMouseEnter={show}
			onMouseLeave={hide}
			onFocus={show}
			onBlur={hide}
			onKeyDown={(e) => e.key === "Escape" && hide()}
		>
			{children}
			{at && (
				<span
					role="tooltip"
					style={{
						left: at.left,
						top: at.top,
						transform: `translate(-50%, ${at.place === "top" ? "-100%" : "0"})`,
					}}
					className="pointer-events-none fixed z-[80] max-w-xs rounded-md bg-inverse px-2 py-1 text-xs leading-snug font-medium text-on-inverse shadow-lg"
				>
					{label}
				</span>
			)}
		</span>
	);
};
