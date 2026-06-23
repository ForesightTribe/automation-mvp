/** App-wide constant values. No logic, no React. */

// localStorage keys (the backend stores the JWT client-side; see api-reference).
export const STORAGE_KEYS = {
	token: "foresight.token",
	activeClientId: "foresight.activeClientId",
	dateRangeDays: "foresight.dateRangeDays",
};

// Default `?days=` window for dashboard endpoints.
export const DEFAULT_DAYS = 30;

// Global date-range presets. The backend only takes `?days=`, so the range is a
// day count, not arbitrary from/to. Drives the Navbar DateRangePicker.
export const DATE_RANGE_PRESETS = [
	{ label: "Last 7 days", days: 7 },
	{ label: "Last 30 days", days: 30 },
	{ label: "Last 90 days", days: 90 },
];

// Default pagination page size (backend caps at 100).
export const DEFAULT_PAGE_SIZE = 20;

// Window event the axios layer fires on a 401 so AuthContext can end the session
// (interceptors live outside React and can't touch context/router directly).
export const AUTH_EXPIRED_EVENT = "foresight:auth-expired";
