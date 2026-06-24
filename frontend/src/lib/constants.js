/** App-wide constant values. No logic, no React. */

// localStorage keys (the backend stores the JWT client-side; see api-reference).
export const STORAGE_KEYS = {
	token: "foresight.token",
	activeClientId: "foresight.activeClientId",
	dateRange: "foresight.dateRange",
	marketplaces: "foresight.marketplaces",
};

// Default `?days=` window for dashboard endpoints.
export const DEFAULT_DAYS = 30;

// Global date-range presets. A preset is just sugar for a {from,to} range ending
// today; "Custom" lets the user pick both ends. Drives the Navbar
// DateRangePicker. `key` is the persisted/active-chip identifier.
export const DATE_RANGE_PRESETS = [
	{ key: "7d", label: "Last 7 days", days: 7 },
	{ key: "30d", label: "Last 30 days", days: 30 },
	{ key: "90d", label: "Last 90 days", days: 90 },
];

// Marker for a user-defined {from,to} window (not one of the presets above).
export const CUSTOM_RANGE_KEY = "custom";

// Default pagination page size (backend caps at 100).
export const DEFAULT_PAGE_SIZE = 20;

// Window event the axios layer fires on a 401 so AuthContext can end the session
// (interceptors live outside React and can't touch context/router directly).
export const AUTH_EXPIRED_EVENT = "foresight:auth-expired";
