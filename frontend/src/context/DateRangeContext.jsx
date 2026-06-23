import { createContext, useContext, useState, useCallback } from "react";
import {
	STORAGE_KEYS,
	DEFAULT_DAYS,
	DATE_RANGE_PRESETS,
} from "../lib/constants";

/**
 * Owns the global date window (`days`) that dashboard endpoints take as `?days=`.
 * Many pages depend on it, so it's app-owned state in Context — not duplicated
 * per page. Feature query hooks read `days` and put it in their queryKey, so
 * changing the range here refetches every page that uses it (same mechanism as
 * the client switcher).
 */
const DateRangeContext = createContext(null);

export const DateRangeProvider = ({ children }) => {
	const [days, setDaysState] = useState(() => {
		const stored = Number(localStorage.getItem(STORAGE_KEYS.dateRangeDays));
		return Number.isFinite(stored) && stored > 0 ? stored : DEFAULT_DAYS;
	});

	const setDays = useCallback((next) => {
		setDaysState(next);
		localStorage.setItem(STORAGE_KEYS.dateRangeDays, String(next));
	}, []);

	const value = { days, setDays, presets: DATE_RANGE_PRESETS };

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
