/**
 * Date-window helpers for the global date range. The canonical window is a
 * { from, to } pair of `YYYY-MM-DD` strings (inclusive), which the API takes as
 * `?start=&end=`. Presets are just shortcuts that compute such a window ending
 * today. Kept framework-free so contexts and hooks share one source of truth.
 */
import {
	DATE_RANGE_PRESETS,
	DEFAULT_DAYS,
	CUSTOM_RANGE_KEY,
} from "./constants";

/** Date -> "YYYY-MM-DD" in local time (avoids the UTC shift of toISOString). */
export const toISODate = (date) => {
	const y = date.getFullYear();
	const m = String(date.getMonth() + 1).padStart(2, "0");
	const d = String(date.getDate()).padStart(2, "0");
	return `${y}-${m}-${d}`;
};

/** Last `days` days ending today -> { from, to } inclusive. */
export const rangeFromDays = (days) => {
	const to = new Date();
	const from = new Date();
	from.setDate(from.getDate() - (days - 1));
	return { from: toISODate(from), to: toISODate(to) };
};

/** Inclusive day count of a { from, to } window (used as a legacy `days`). */
export const daysInRange = ({ from, to }) => {
	const ms = new Date(to).getTime() - new Date(from).getTime();
	return Math.round(ms / 86400000) + 1;
};

/** Build the canonical window for a preset key (falls back to the default). */
export const rangeFromPresetKey = (key) => {
	const preset =
		DATE_RANGE_PRESETS.find((p) => p.key === key) ??
		DATE_RANGE_PRESETS.find((p) => p.days === DEFAULT_DAYS);
	return rangeFromDays(preset.days);
};

/** Match a { from, to } to a preset key, else "custom" (for chip highlight). */
export const presetKeyForRange = (range) => {
	const match = DATE_RANGE_PRESETS.find((p) => {
		const r = rangeFromDays(p.days);
		return r.from === range.from && r.to === range.to;
	});
	return match ? match.key : CUSTOM_RANGE_KEY;
};
