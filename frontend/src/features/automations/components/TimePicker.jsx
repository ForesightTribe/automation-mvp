import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * Time field that looks like the rest of the app — and can be TYPED into.
 *
 * `<input type="time">` is drawn by the browser and cannot be styled at all: different
 * shape, its own clock icon, a different popup on every platform. This renders the list
 * itself, but it stays a text input rather than a button, because a list alone would cap
 * you at the increments it happens to offer — 11:07 has to be reachable.
 *
 * Typing accepts what people actually type: "9", "9pm", "9:07 pm", "0907", "21:07".
 * The quarter-hour list is a shortcut, not the whole vocabulary.
 *
 * ⚠️ The VALUE stays "HH:MM" 24-hour, which is what the engine parses (`_parse_hhmm` in
 * bid.py / budget.py). Only the DISPLAY is 12-hour — never send what is shown.
 */
const pad = (n) => String(n).padStart(2, "0");

/** "14:30" → "2:30 PM". Empty stays empty so a blank field can mean "no time set". */
export const to12h = (hhmm) => {
	if (!hhmm) return "";
	const [h, m] = hhmm.split(":").map(Number);
	if (Number.isNaN(h)) return "";
	const suffix = h < 12 ? "AM" : "PM";
	return `${h % 12 === 0 ? 12 : h % 12}:${pad(m)} ${suffix}`;
};

/** "14:30" → "2:30". The AM/PM toggle states the half, so the input does not repeat it. */
const clockText = (hhmm) => {
	if (!hhmm) return "";
	const [h, m] = hhmm.split(":").map(Number);
	if (Number.isNaN(h)) return "";
	return `${h % 12 === 0 ? 12 : h % 12}:${pad(m)}`;
};

const periodOf = (hhmm) =>
	hhmm && Number(hhmm.slice(0, 2)) >= 12 ? "PM" : "AM";

/**
 * Anything a person plausibly types → "HH:MM", or null when it is not a time.
 * Returning null (rather than guessing) is what lets the field restore its previous
 * value on blur instead of silently storing something nobody meant.
 */
export const parseTime = (raw) => {
	const s = String(raw).trim().toLowerCase().replace(/\s+/g, "");
	if (!s) return "";
	const m = s.match(/^(\d{1,2})(?::|\.)?(\d{2})?(am|pm)?$/);
	if (!m) return null;
	let hour = Number(m[1]);
	const min = m[2] == null ? 0 : Number(m[2]);
	const period = m[3];
	// "0907" — four digits with no separator is HHMM, not hour 9 with stray minutes.
	if (m[1].length > 2) return null;
	if (period) {
		if (hour < 1 || hour > 12) return null;
		hour = period === "pm" ? (hour % 12) + 12 : hour % 12;
	}
	if (hour > 23 || min > 59) return null;
	return `${pad(hour)}:${pad(min)}`;
};

const buildOptions = (stepMinutes) => {
	const out = [];
	for (let m = 0; m < 24 * 60; m += stepMinutes)
		out.push(`${pad(Math.floor(m / 60))}:${pad(m % 60)}`);
	return out;
};

export const TimePicker = ({
	value = "",
	onChange,
	disabled = false,
	step = 15,
	placeholder = "--:--",
	allowClear = true,
	"aria-label": ariaLabel,
}) => {
	const [open, setOpen] = useState(false);
	/**
	 * ⚠️ The list is `position: fixed` and PORTALLED to the body, anchored to the field's own
	 * rect. The wizard body scrolls, and an absolutely-positioned panel is clipped by it,
	 * which leaves the suggestions inside the box where they have to be scrolled to.
	 * Re-measured on every open, and closed on scroll, because the coordinates are only
	 * true for where the field was at that moment.
	 */
	const [at, setAt] = useState(null);
	const panelRef = useRef(null);
	const place = () => {
		const r = wrap.current?.getBoundingClientRect();
		if (!r) return;
		const below = window.innerHeight - r.bottom;
		setAt(
			below > 240
				? { left: r.left, top: r.bottom + 4 }
				: { left: r.left, top: r.top - 4, flip: true },
		);
	};
	const [text, setText] = useState(clockText(value));
	const wrap = useRef(null);
	const listRef = useRef(null);
	const options = useMemo(() => buildOptions(step), [step]);

	// Follow the value while the field is closed; while it is open the user owns the text.
	useEffect(() => {
		if (!open) setText(clockText(value));
	}, [value, open]);

	useEffect(() => {
		if (!open) return;
		// ⚠️ Ignore scrolls that START INSIDE the panel. The listener is on the capture phase
		// so it sees the page move under a panel anchored to a rect measured once. The panel
		// scrolling its own list reaches the same handler, and closing on that would take the
		// list away as soon as anyone reaches for an option below the fold.
		const onScroll = (e) => {
			if (panelRef.current?.contains(e.target)) return;
			setOpen(false);
		};
		window.addEventListener("scroll", onScroll, true);
		return () => window.removeEventListener("scroll", onScroll, true);
	}, [open]);

	useEffect(() => {
		if (!open) return;
		const onDown = (e) => {
			const inField = wrap.current?.contains(e.target);
			const inPanel = panelRef.current?.contains(e.target);
			if (!inField && !inPanel) commit();
		};
		document.addEventListener("mousedown", onDown);
		return () => document.removeEventListener("mousedown", onDown);
	});

	// Open onto the current value — 96 options is a long scroll from midnight.
	useEffect(() => {
		if (!open || !listRef.current) return;
		const sel = listRef.current.querySelector("[data-selected='true']");
		if (sel) sel.scrollIntoView({ block: "center" });
	}, [open]);

	const period = periodOf(value);

	/**
	 * Accept what was typed, or put the field back to the last good value.
	 *
	 * A bare "9" is genuinely ambiguous, so it takes whichever half the toggle is showing.
	 * "9pm" and "21:07" say the half themselves and are left alone — otherwise typing a
	 * 24-hour time would be silently rewritten by a toggle the user never touched.
	 */
	const commit = () => {
		const raw = text.trim().toLowerCase();
		if (!raw) {
			if (value) onChange("");
			setOpen(false);
			return;
		}
		let parsed = parseTime(raw);
		if (parsed === null) {
			setText(clockText(value));
			setOpen(false);
			return;
		}
		const saysHalf = /am|pm/.test(raw);
		const h = Number(parsed.slice(0, 2));
		if (!saysHalf && h <= 12) {
			const h12 = h % 12;
			parsed = `${pad(period === "PM" ? h12 + 12 : h12)}${parsed.slice(2)}`;
		}
		if (parsed !== value) onChange(parsed);
		setOpen(false);
	};

	/** Flip the stored hour by 12. Only meaningful once there is a time to flip. */
	const setPeriod = (p) => {
		if (!value || p === period) return;
		const [h, m] = value.split(":").map(Number);
		const h12 = h % 12;
		onChange(`${pad(p === "PM" ? h12 + 12 : h12)}:${pad(m)}`);
	};

	const choose = (t) => {
		onChange(t);
		setText(clockText(t));
		setOpen(false);
	};

	// While typing, narrow the list to what matches — "9p" should not scroll past 96 rows.
	const typedPrefix = text.trim().toLowerCase();
	const shown = typedPrefix
		? options.filter((t) =>
				to12h(t)
					.toLowerCase()
					.replace(/\s+/g, "")
					.includes(typedPrefix.replace(/\s+/g, "")),
			)
		: options;

	return (
		<div ref={wrap} className="relative flex items-center gap-1">
			<input
				type="text"
				inputMode="numeric"
				aria-label={ariaLabel}
				aria-haspopup="listbox"
				aria-expanded={open}
				disabled={disabled}
				value={text}
				placeholder={placeholder}
				onChange={(e) => {
					setText(e.target.value);
					setOpen(true);
					place();
				}}
				onFocus={() => {
					setOpen(true);
					place();
				}}
				onKeyDown={(e) => {
					if (e.key === "Enter") {
						e.preventDefault();
						commit();
					}
					if (e.key === "Escape") {
						setText(clockText(value));
						setOpen(false);
					}
				}}
				className="w-20 rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-content focus:border-brand focus:outline-none disabled:cursor-not-allowed disabled:bg-muted disabled:text-content-subtle"
			/>

			{/* AM/PM as an explicit control rather than something you have to know to type.
			    It only flips an existing time. With the field empty there is no hour to put
			    in either half, so it stays inert until one is set. */}
			<div
				className="flex overflow-hidden rounded-md border border-border"
				role="group"
				aria-label="AM or PM"
			>
				{["AM", "PM"].map((p) => (
					<button
						key={p}
						type="button"
						disabled={disabled || !value}
						aria-pressed={value ? period === p : false}
						onClick={() => setPeriod(p)}
						title={value ? undefined : "Set a time first"}
						className={`px-2 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
							value && period === p
								? "bg-brand text-on-brand"
								: "bg-card text-content-muted hover:bg-muted"
						}`}
					>
						{p}
					</button>
				))}
			</div>

			{open &&
				!disabled &&
				at &&
				createPortal(
					<div
						ref={panelRef}
						style={{
							left: at.left,
							top: at.top,
							transform: at.flip
								? "translateY(-100%)"
								: undefined,
						}}
						className="fixed z-[75] w-32 rounded-lg border border-border bg-card shadow-xl"
					>
						{allowClear && (
							<button
								type="button"
								onClick={() => choose("")}
								className="w-full border-b border-border px-3 py-1.5 text-left text-xs text-content-subtle hover:bg-muted"
							>
								Clear
							</button>
						)}
						<ul
							ref={listRef}
							role="listbox"
							className="max-h-56 overflow-auto py-1"
						>
							{shown.length === 0 && (
								<li className="px-3 py-2 text-xs text-content-subtle">
									{parseTime(text)
										? "Press Enter to use this time"
										: "Not a time"}
								</li>
							)}
							{shown.map((t) => {
								const on = t === value;
								return (
									<li key={t}>
										<button
											type="button"
											role="option"
											aria-selected={on}
											data-selected={on}
											onClick={() => choose(t)}
											className={`w-full px-3 py-1.5 text-left text-sm ${
												on
													? "bg-muted font-medium text-brand"
													: "text-content hover:bg-muted"
											}`}
										>
											{to12h(t)}
										</button>
									</li>
								);
							})}
						</ul>
					</div>,
					document.body,
				)}
		</div>
	);
};
