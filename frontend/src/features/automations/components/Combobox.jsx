import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";

/**
 * A typeahead that stays typeable: suggestions narrow as you type, and a value that matches
 * nothing is still accepted.
 *
 * ⚠️ Not a `<datalist>`. The browser draws that one itself, so it cannot take the app's
 * colours, its type or its radius, and on several browsers it gives no sign that suggestions
 * exist at all. This renders the list, so the highlighted row is a filled brand row like
 * every other chosen thing in this product.
 *
 * ⚠️ The panel is `position: fixed` and PORTALLED to the body, anchored to the input's own
 * rect. It lives inside a dialog whose body scrolls, which would clip an absolutely
 * positioned panel, and inside stacking contexts that a plain z-index cannot climb out of.
 * It flips above the field when there is no room below, and closes on scroll because the
 * coordinates are measured once.
 */
export const Combobox = ({
	value,
	onChange,
	options = [],
	placeholder,
	id = "combobox",
	invalid = false,
	className = "",
}) => {
	const [at, setAt] = useState(null);
	const [active, setActive] = useState(0);
	const wrap = useRef(null);
	const isOpen = at != null;

	// Substring, not prefix: "delhi" should find "New Delhi", which is how people recall a
	// place they half-remember.
	const matches = useMemo(() => {
		const q = String(value ?? "")
			.trim()
			.toLowerCase();
		if (!q) return options;
		return options.filter((o) => o.label.toLowerCase().includes(q));
	}, [options, value]);

	useEffect(() => setActive(0), [value, isOpen]);

	const place = () => {
		const r = wrap.current?.getBoundingClientRect();
		if (!r) return;
		const height = Math.min(matches.length * 34 + 8, 264);
		const below = window.innerHeight - r.bottom;
		setAt(
			below > height + 12
				? { left: r.left, top: r.bottom + 6, width: r.width }
				: {
						left: r.left,
						top: r.top - 6,
						width: r.width,
						flip: true,
					},
		);
	};
	const close = () => setAt(null);

	useEffect(() => {
		if (!isOpen) return;
		const onDown = (e) => {
			if (wrap.current && !wrap.current.contains(e.target)) close();
		};
		const onScroll = () => close();
		document.addEventListener("mousedown", onDown);
		window.addEventListener("scroll", onScroll, true);
		return () => {
			document.removeEventListener("mousedown", onDown);
			window.removeEventListener("scroll", onScroll, true);
		};
	}, [isOpen]);

	const choose = (label) => {
		onChange(label);
		close();
	};

	const onKeyDown = (e) => {
		if (e.key === "Escape") return close();
		if (e.key === "ArrowDown" || e.key === "ArrowUp") {
			e.preventDefault();
			if (!isOpen) return place();
			const step = e.key === "ArrowDown" ? 1 : -1;
			return setActive((i) =>
				matches.length
					? (i + step + matches.length) % matches.length
					: 0,
			);
		}
		if (e.key === "Enter" && isOpen && matches[active]) {
			e.preventDefault();
			choose(matches[active].label);
		}
	};

	return (
		<div ref={wrap} className={`relative ${className}`}>
			<input
				id={id}
				role="combobox"
				aria-expanded={isOpen}
				aria-controls={`${id}-list`}
				aria-autocomplete="list"
				aria-invalid={invalid}
				autoComplete="off"
				value={value ?? ""}
				placeholder={placeholder}
				onChange={(e) => {
					onChange(e.target.value);
					place();
				}}
				onFocus={place}
				onKeyDown={onKeyDown}
				className="w-full rounded-md border border-border bg-card px-2.5 py-1.5 pr-8 text-sm text-content transition-colors focus:border-brand focus:outline-none aria-[invalid=true]:border-danger"
			/>
			<button
				type="button"
				tabIndex={-1}
				aria-hidden="true"
				onClick={() => (isOpen ? close() : place())}
				className="absolute top-1/2 right-2 -translate-y-1/2 text-content-subtle"
			>
				<ChevronDown size={13} />
			</button>

			{isOpen &&
				createPortal(
					<ul
						id={`${id}-list`}
						role="listbox"
						style={{
							left: at.left,
							top: at.top,
							width: at.width,
							transform: at.flip
								? "translateY(-100%)"
								: undefined,
						}}
						className="fixed z-[75] max-h-64 overflow-auto rounded-lg border border-border bg-card p-1 shadow-xl"
					>
						{matches.length === 0 ? (
							<li className="px-2.5 py-2 text-xs text-content-subtle">
								No match. You can still use what you typed.
							</li>
						) : (
							matches.map((o, i) => {
								const on = o.label === value;
								return (
									<li key={o.value ?? o.label}>
										<button
											type="button"
											role="option"
											aria-selected={on}
											onMouseEnter={() => setActive(i)}
											onClick={() => choose(o.label)}
											className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors ${
												i === active
													? "bg-brand font-medium text-on-brand"
													: "text-content hover:bg-muted"
											}`}
										>
											<span className="flex-1 truncate">
												{o.label}
											</span>
											{o.hint && (
												<span
													className={`shrink-0 text-xs ${i === active ? "text-on-brand/80" : "text-content-subtle"}`}
												>
													{o.hint}
												</span>
											)}
											<Check
												size={13}
												className={`shrink-0 ${on ? "" : "invisible"}`}
											/>
										</button>
									</li>
								);
							})
						)}
					</ul>,
					document.body,
				)}
		</div>
	);
};
