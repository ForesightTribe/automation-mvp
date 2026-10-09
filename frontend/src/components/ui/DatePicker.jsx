import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";

/**
 * A date field in the app's own colours.
 *
 * ⚠️ Not `<input type="date">`. The browser draws that calendar itself, so it takes none of
 * the theme's type, colour or radius, and it looks like a different product every time it
 * opens. The field below is a button that renders the date, and the calendar is ours.
 *
 * `active` marks the field as the one in force — the calendar icon goes brand.
 *
 * ⚠️ `allowClear={false}` for a field that must always hold a date. Clearing writes "" and
 * every consumer then has to survive it: the global range does not, because an empty end
 * makes the window unmeasurable and each page computes its days from it.
 *
 * ⚠️ The panel is `position: fixed` and PORTALLED to the body, anchored to the field's rect.
 * It opens inside a dialog whose body scrolls, which would clip an absolutely positioned
 * panel, and inside stacking contexts a plain z-index cannot climb out of. It flips above
 * the field when there is no room below, and closes on scroll because the coordinates are
 * measured once.
 */
const DOW = ["S", "M", "T", "W", "T", "F", "S"];
const MONTHS = [
	"January",
	"February",
	"March",
	"April",
	"May",
	"June",
	"July",
	"August",
	"September",
	"October",
	"November",
	"December",
];

/** Local fields, never toISOString(): that converts to UTC first, and local midnight in
 *  IST is 18:30 the previous evening, so every date would land a day early. */
const toIso = (d) =>
	`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const fromIso = (iso) => (iso ? new Date(`${iso}T00:00:00`) : null);

const label = (iso) => {
	const d = fromIso(iso);
	return d && !Number.isNaN(d.getTime())
		? d.toLocaleDateString("en-IN", {
				day: "numeric",
				month: "short",
				year: "numeric",
			})
		: null;
};

export const DatePicker = ({
	value,
	onChange,
	min,
	max,
	disabled = false,
	allowClear = true,
	active = false,
	placeholder = "Pick a date",
	ariaLabel = "Date",
	className = "",
}) => {
	const [at, setAt] = useState(null);
	const [month, setMonth] = useState(() => fromIso(value) ?? new Date());
	const wrap = useRef(null);
	const panel = useRef(null);
	const isOpen = at != null;

	useEffect(() => {
		const d = fromIso(value);
		if (d && !Number.isNaN(d.getTime())) setMonth(d);
	}, [value]);

	const open = () => {
		const r = wrap.current?.getBoundingClientRect();
		if (!r || disabled) return;
		const height = 320;
		const below = window.innerHeight - r.bottom;
		setAt(
			below > height + 12
				? { left: r.left, top: r.bottom + 6 }
				: { left: r.left, top: r.top - 6, flip: true },
		);
	};
	const close = () => setAt(null);

	useEffect(() => {
		if (!isOpen) return;
		const onDown = (e) => {
			if (
				!wrap.current?.contains(e.target) &&
				!panel.current?.contains(e.target)
			)
				close();
		};
		const onKey = (e) => e.key === "Escape" && close();
		// Same guard as the other panels: a scroll starting inside must not close it.
		const onScroll = (e) => {
			if (panel.current?.contains(e.target)) return;
			close();
		};
		document.addEventListener("mousedown", onDown);
		document.addEventListener("keydown", onKey);
		window.addEventListener("scroll", onScroll, true);
		return () => {
			document.removeEventListener("mousedown", onDown);
			document.removeEventListener("keydown", onKey);
			window.removeEventListener("scroll", onScroll, true);
		};
	}, [isOpen]);

	// The cells of the shown month, padded with blanks so the 1st lands on its weekday.
	const cells = useMemo(() => {
		const first = new Date(month.getFullYear(), month.getMonth(), 1);
		const days = new Date(
			month.getFullYear(),
			month.getMonth() + 1,
			0,
		).getDate();
		return [
			...Array(first.getDay()).fill(null),
			...Array.from(
				{ length: days },
				(_, i) =>
					new Date(month.getFullYear(), month.getMonth(), i + 1),
			),
		];
	}, [month]);

	const todayIso = toIso(new Date());
	const blocked = (iso) => (min && iso < min) || (max && iso > max);

	return (
		<div ref={wrap} className={`relative ${className}`}>
			<button
				type="button"
				disabled={disabled}
				aria-label={ariaLabel}
				onClick={() => (isOpen ? close() : open())}
				className={`flex w-full cursor-pointer items-center justify-between gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-left text-sm transition-colors hover:border-content-subtle focus:border-brand focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${
					value ? "text-content" : "text-content-subtle"
				}`}
			>
				{label(value) ?? placeholder}
				<CalendarDays
					size={14}
					className={`shrink-0 ${active || isOpen ? "text-brand" : "text-content-subtle"}`}
				/>
			</button>

			{isOpen &&
				createPortal(
					<div
						ref={panel}
						style={{
							left: at.left,
							top: at.top,
							transform: at.flip
								? "translateY(-100%)"
								: undefined,
						}}
						className="fixed z-[75] w-72 rounded-lg border border-border bg-card p-3 shadow-xl"
					>
						<div className="mb-2 flex items-center justify-between">
							<button
								type="button"
								aria-label="Previous month"
								onClick={() =>
									setMonth(
										new Date(
											month.getFullYear(),
											month.getMonth() - 1,
											1,
										),
									)
								}
								className="cursor-pointer rounded p-1 text-content-muted transition-colors hover:bg-muted hover:text-content"
							>
								<ChevronLeft size={16} />
							</button>
							<span className="font-display text-sm font-semibold text-content">
								{MONTHS[month.getMonth()]} {month.getFullYear()}
							</span>
							<button
								type="button"
								aria-label="Next month"
								onClick={() =>
									setMonth(
										new Date(
											month.getFullYear(),
											month.getMonth() + 1,
											1,
										),
									)
								}
								className="cursor-pointer rounded p-1 text-content-muted transition-colors hover:bg-muted hover:text-content"
							>
								<ChevronRight size={16} />
							</button>
						</div>

						<div className="grid grid-cols-7 gap-0.5">
							{DOW.map((d, i) => (
								<span
									key={i}
									className="py-1 text-center text-[10px] font-semibold tracking-wide text-content-subtle uppercase"
								>
									{d}
								</span>
							))}
							{cells.map((d, i) => {
								if (!d) return <span key={`b${i}`} />;
								const iso = toIso(d);
								const on = iso === value;
								const off = blocked(iso);
								return (
									<button
										key={iso}
										type="button"
										disabled={off}
										aria-current={
											iso === todayIso
												? "date"
												: undefined
										}
										onClick={() => {
											onChange(iso);
											close();
										}}
										className={`cursor-pointer rounded-md py-1.5 text-sm tabular-nums transition-colors disabled:cursor-not-allowed disabled:text-content-subtle/40 ${
											on
												? "bg-brand font-semibold text-on-brand"
												: iso === todayIso
													? "font-semibold text-brand hover:bg-muted"
													: "text-content hover:bg-muted"
										}`}
									>
										{d.getDate()}
									</button>
								);
							})}
						</div>

						{/* Clearing matters where an end date is optional: without it the only
						    way back to "no end" is the checkbox beside the field. Where a date
						    is mandatory it is left out, so there is no way to empty it. */}
						<div
							className={`mt-2 flex border-t border-border pt-2 ${allowClear ? "justify-between" : "justify-start"}`}
						>
							<button
								type="button"
								onClick={() => {
									onChange(todayIso);
									close();
								}}
								className="cursor-pointer text-xs font-medium text-brand hover:underline"
							>
								Today
							</button>
							{allowClear && (
								<button
									type="button"
									onClick={() => {
										onChange("");
										close();
									}}
									className="cursor-pointer text-xs text-content-muted transition-colors hover:text-content"
								>
									Clear
								</button>
							)}
						</div>
					</div>,
					document.body,
				)}
		</div>
	);
};
