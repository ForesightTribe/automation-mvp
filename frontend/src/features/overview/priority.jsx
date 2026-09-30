import {
	createContext,
	useCallback,
	useContext,
	useEffect,
	useState,
} from "react";

/**
 * Load order for the Overview: the day block first, everything else after.
 *
 * Every panel's request is cheap on its own, but they all draw from one
 * connection pool and the competition and reach reads take tens of seconds on a
 * large tenant. Fired together, the day block — which reads only sales and ads,
 * and answers in about a second — waits behind them for no reason.
 *
 * So the panels below hold until the day block has what it needs. Nothing is
 * made faster; the fastest and most-read thing simply stops queueing behind the
 * slowest.
 *
 * ⚠️ The gate also opens on a timer. A tenant whose day block finds no sales
 * would otherwise leave the rest of the page waiting forever on a signal that
 * is never sent.
 */
const FALLBACK_MS = 4000;

const PriorityContext = createContext({ ready: true, release: () => {} });

export const PriorityProvider = ({ children }) => {
	const [ready, setReady] = useState(false);
	const release = useCallback(() => setReady(true), []);

	useEffect(() => {
		const t = setTimeout(release, FALLBACK_MS);
		return () => clearTimeout(t);
	}, [release]);

	return (
		<PriorityContext.Provider value={{ ready, release }}>
			{children}
		</PriorityContext.Provider>
	);
};

/** True once the day block is served and the rest may load. */
export const useSecondaryReady = () => useContext(PriorityContext).ready;

/** Called by the day block once its own data has arrived. */
export const useReleaseSecondary = () => useContext(PriorityContext).release;
