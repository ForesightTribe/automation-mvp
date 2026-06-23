/**
 * Tiny leveled logger. Use this instead of bare `console.*` so logging is
 * consistent and centrally controlled.
 *
 * Policy: in production EVERYTHING is silenced (including warn/error) — the
 * console stays clean for end users. In development everything logs. Flip the
 * `ENABLED` flag if you ever need errors in prod.
 */
const ENABLED = import.meta.env.DEV;
const PREFIX = "[foresight]";

const noop = () => {};
const sink = (fn) => (ENABLED ? (...args) => fn(PREFIX, ...args) : noop);

export const logger = {
	debug: sink(console.debug),
	info: sink(console.info),
	warn: sink(console.warn),
	error: sink(console.error),

	// API tracing — used by the axios interceptors in lib/axios.js.
	request: ENABLED
		? (method, url) =>
				console.debug(PREFIX, "→", method?.toUpperCase(), url)
		: noop,
	response: ENABLED
		? (method, url, status) =>
				console.debug(PREFIX, "←", status, method?.toUpperCase(), url)
		: noop,
};
