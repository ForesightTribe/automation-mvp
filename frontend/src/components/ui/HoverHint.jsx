import { useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * A short explanation that appears when the reader points at something, with no icon of its
 * own. Wrap any element and it becomes the trigger, so a table header can explain itself
 * without carrying an ⓘ in every column.
 *
 * A dark bubble on a light page, which is what `--color-inverse` is for ("dark fill — grand
 * total rows, tooltips"). It reads as an overlay rather than as another card: a white panel
 * with a border looks like part of the page it is floating over, and on a table of white
 * cards it competes with them. Small type, tight padding and a 4px radius keep it a label
 * rather than a second surface.
 *
 * Positioned FIXED and anchored to the trigger's own rect: these sit inside cards and tables
 * that clip their overflow, and an absolutely-positioned bubble would be cut off. Opens on
 * hover and on focus (React's onFocus bubbles, so a button inside still triggers it), and
 * closes on Escape.
 *
 * ⚠️ It tries BESIDE the trigger before below it. Dropping straight down from an ⓘ in a card
 * header lands the panel squarely on the number that ⓘ is explaining, so the reader loses
 * the thing they were asking about at the moment they ask. Right, then left, then below,
 * then above: the first placement that fits the viewport wins.
 *
 * ⚠️ `whitespace-normal` is load-bearing. Table headers carry `whitespace-nowrap` so their
 * labels never break mid-column, and the panel INHERITS it: the text then refuses to wrap,
 * ignores the panel's width and runs straight off the side of the screen. The panel has to
 * opt back in to wrapping wherever it is mounted.
 *
 * ⚠️ The panel is rendered through a PORTAL to `document.body`, not inside the trigger.
 * `position: fixed` escapes overflow, but it does not escape a stacking context: a sticky
 * table header sets its own `z-index`, which makes every z-index inside it relative to that
 * header, so the panel could be painted under a neighbouring frozen cell no matter how high
 * its own z went. Mounted on the body it has no competing ancestor to lose to.
 *
 * Pass `tabIndex={0}` where the wrapped content is not already focusable, so the hint stays
 * reachable by keyboard.
 */
const GAP = 10;
const EDGE = 8;

const place = (r, w, h) => {
	const vw = window.innerWidth;
	const vh = window.innerHeight;
	// Vertically centred on the trigger, then pulled inside the viewport.
	const mid = Math.min(
		Math.max(EDGE, r.top + r.height / 2 - h / 2),
		vh - h - EDGE,
	);

	if (r.right + GAP + w <= vw - EDGE)
		return { left: r.right + GAP, top: mid };
	if (r.left - GAP - w >= EDGE) return { left: r.left - GAP - w, top: mid };

	const left = Math.min(Math.max(EDGE, r.left), vw - w - EDGE);
	if (r.bottom + GAP + h <= vh - EDGE) return { left, top: r.bottom + GAP };
	return { left, top: Math.max(EDGE, r.top - GAP - h) };
};

export const HoverHint = ({
	label,
	children,
	className = "",
	tabIndex,
	width = 260,
}) => {
	const ref = useRef(null);
	const panel = useRef(null);
	const [at, setAt] = useState(null);

	const show = () => {
		const r = ref.current?.getBoundingClientRect();
		if (!r || !label) return;
		// A first pass with an estimated height, corrected once the panel has measured itself.
		setAt(place(r, width, 96));
		requestAnimationFrame(() => {
			const rr = ref.current?.getBoundingClientRect();
			const h = panel.current?.offsetHeight;
			if (rr && h) setAt(place(rr, width, h));
		});
	};
	const hide = () => setAt(null);

	return (
		<span
			ref={ref}
			tabIndex={tabIndex}
			className={`inline-flex ${className}`}
			onMouseEnter={show}
			onMouseLeave={hide}
			onFocus={show}
			onBlur={hide}
			onKeyDown={(e) => e.key === "Escape" && hide()}
		>
			{children}
			{at &&
				createPortal(
					<span
						ref={panel}
						role="tooltip"
						style={{ left: at.left, top: at.top, width }}
						className="pointer-events-none fixed z-[80] rounded bg-inverse px-2.5 py-1.5 text-[11px] leading-[1.45] font-normal normal-case tracking-normal whitespace-normal text-on-inverse shadow-lg"
					>
						{label}
					</span>,
					document.body,
				)}
		</span>
	);
};
