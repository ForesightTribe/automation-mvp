import { createContext, useContext, useState, useCallback } from "react";
import {
	STORAGE_KEYS,
	DATE_RANGE_PRESETS,
	DEFAULT_DAYS,
} from "../lib/constants";
import {
	rangeFromDays,
	rangeFromPresetKey,
	presetKeyForRange,
	daysInRange,
} from "../lib/dates";

/**
 * Owns the global reporting window. The canonical value is a { from, to } pair
 * of YYYY-MM-DD strings that endpoints take as `?start=&end=` (via PeriodDep).
 * Presets (7/30/90d) are shortcuts that set such a window ending today; a custom
 * range sets from/to directly. App-owned state -> Context (no React Query):
 * feature hooks read `range` and key on it, so changing the window here refetches
 * every page that uses it (same mechanism as the client switcher).
 *
 * `days` is a derived convenience for endpoints not yet migrated to start/end.
 */
const DateRangeContext = createContext(null);

const loadRange = () => {
	try {
		const stored = JSON.parse(localStorage.getItem(STORAGE_KEYS.dateRange));
		if (stored?.from && stored?.to) return stored;
	} catch {
		// fall through to default
	}
	return rangeFromDays(DEFAULT_DAYS);
};

export const DateRangeProvider = ({ children }) => {
	const [range, setRange] = useState(loadRange);

	const persist = useCallback((next) => {
		setRange(next);
		localStorage.setItem(STORAGE_KEYS.dateRange, JSON.stringify(next));
	}, []);

	// Select a preset by key ("7d" | "30d" | "90d").
	const setPreset = useCallback(
		(key) => persist(rangeFromPresetKey(key)),
		[persist],
	);

	// Select an explicit { from, to } window.
	const setCustomRange = useCallback(
		(from, to) => persist({ from, to }),
		[persist],
	);

	const value = {
		range, // { from, to } — canonical, send as ?start=&end=
		days: daysInRange(range), // derived, for endpoints still on ?days=
		activePreset: presetKeyForRange(range), // for chip highlighting
		presets: DATE_RANGE_PRESETS,
		setPreset,
		setCustomRange,
	};

	return (
		<DateRangeContext.Provider value={value}>
			{children}
		</DateRangeContext.Provider>
	);
};

export const useDateRange = () => {
	const ctx = useContext(DateRangeContext);
	if (!ctx)
		throw new Error("useDateRange must be used within <DateRangeProvider>");
	return ctx;
};
