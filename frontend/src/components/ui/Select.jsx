import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";

/**
 * A dropdown that looks like the rest of the app.
 *
 * A native `<select>` is styled by the browser, not by us: its font, row height, tick and
 * open animation come from the platform, so it sat in a row of our own buttons looking like
 * it belonged to a different product. This is a button plus a panel, built from the same
 * tokens as everything beside it.
 *
 * ⚠️ The panel is `position: fixed`, anchored to the trigger's rect. These live in card
 * headers above `overflow-auto` tables, and an absolutely positioned panel gets clipped by
 * them. Fixed escapes the clip, flips above when there is no room below, and closes on
 * scroll because the coordinates are measured once.
 *
 * Keyboard: Enter or Space opens, Escape closes, arrows move, Enter picks.
 *
 * `options` is [value, label, hint] triples. The trigger shows the LABEL only; the `hint`
 * (a count, say) belongs in the open list, where it helps you choose. Once chosen it is
 * noise on a control whose job is to say what is being filtered to.
 */
export const Select = ({
	value,
	options,
	onChange,
	ariaLabel,
	className = "",
}) => {
	const ref = useRef(null);
	const [at, setAt] = useState(null);
	const [active, setActive] = useState(0);

	const current = options.find(([v]) => v === value);
	const label = current?.[1] ?? options[0]?.[1] ?? "";

	const open = () => {
		const r = ref.current?.getBoundingClientRect();
		if (!r) return;
		const below = window.innerHeight - r.bottom;
		const height = Math.min(options.length * 34 + 8, 280);
		setActive(
			Math.max(
				0,
				options.findIndex(([v]) => v === value),
			),
		);
		setAt(
			below > height + 12
				? {
						left: r.left,
						top: r.bottom + 6,
						width: r.width,
						place: "below",
					}
				: {
						left: r.left,
						top: r.top - 6,
						width: r.width,
						place: "above",
					},
		);
	};
	const close = () => setAt(null);

	useEffect(() => {
		if (!at) return;
		const onDown = (e) => {
			if (!ref.current?.parentElement?.contains(e.target)) close();
		};
		const onScroll = () => close();
		document.addEventListener("mousedown", onDown);
		window.addEventListener("scroll", onScroll, true);
		return () => {
			document.removeEventListener("mousedown", onDown);
			window.removeEventListener("scroll", onScroll, true);
		};
	}, [at]);

	const pick = (v) => {
		onChange(v);
		close();
	};

	const onKeyDown = (e) => {
		if (!at) {
			if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") {
				e.preventDefault();
				open();
			}
			return;
		}
		if (e.key === "Escape") return close();
		if (e.key === "ArrowDown") {
			e.preventDefault();
			setActive((i) => Math.min(options.length - 1, i + 1));
		} else if (e.key === "ArrowUp") {
			e.preventDefault();
			setActive((i) => Math.max(0, i - 1));
		} else if (e.key === "Enter") {
			e.preventDefault();
			pick(options[active][0]);
		}
	};

	return (
		<div className="relative inline-flex">
			<button
				ref={ref}
				type="button"
				aria-label={ariaLabel}
				aria-haspopup="listbox"
				aria-expanded={Boolean(at)}
				onClick={() => (at ? close() : open())}
				onKeyDown={onKeyDown}
				className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors ${
					at
						? "border-content-subtle text-content"
						: "border-border text-content-muted hover:border-content-subtle hover:text-content"
				} ${className}`}
			>
				{label}
				<ChevronDown
					size={13}
					className={`text-content-subtle transition-transform ${at ? "rotate-180" : ""}`}
				/>
			</button>

			{at && (
				<ul
					role="listbox"
					style={{
						left: at.left,
						top: at.top,
						minWidth: Math.max(at.width, 160),
						transform:
							at.place === "above"
								? "translateY(-100%)"
								: undefined,
					}}
					className="fixed z-[75] max-h-72 overflow-auto rounded-lg border border-border bg-card p-1 shadow-xl"
				>
					{options.map(([v, l, hint], i) => {
						const on = v === value;
						return (
							<li key={v}>
								<button
									type="button"
									role="option"
									aria-selected={on}
									onMouseEnter={() => setActive(i)}
									onClick={() => pick(v)}
									className={`flex w-full items-center gap-3 rounded-md px-2.5 py-1.5 text-left text-xs font-medium transition-colors ${
										i === active
											? "bg-muted text-content"
											: "text-content-muted"
									}`}
								>
									<span className="flex-1 truncate">{l}</span>
									{hint != null && (
										<span className="shrink-0 text-content-subtle tabular-nums">
											{hint}
										</span>
									)}
									<Check
										size={13}
										className={`shrink-0 ${on ? "text-brand" : "invisible"}`}
									/>
								</button>
							</li>
						);
					})}
				</ul>
			)}
		</div>
	);
};
