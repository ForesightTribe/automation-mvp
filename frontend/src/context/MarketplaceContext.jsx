import {
	createContext,
	useContext,
	useEffect,
	useMemo,
	useState,
	useCallback,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/axios";
import { STORAGE_KEYS } from "../lib/constants";
import { useAuth } from "./AuthContext";

/**
 * Owns the global marketplace selection. Same split as ClientContext: the *list*
 * of marketplaces is server data (React Query, with a `connected` flag per MP),
 * the *selected* slugs are app-owned state (Context). Feature hooks read
 * `selected` and put it in their queryKey so toggling a marketplace refetches.
 *
 * Only `connected` marketplaces can be selected — the rest show in the picker but
 * are disabled ("coming soon") until their scrapers land. The default selection
 * is every connected marketplace ("All").
 */
const MarketplaceContext = createContext(null);

const loadSelection = () => {
	try {
		const stored = JSON.parse(
			localStorage.getItem(STORAGE_KEYS.marketplaces),
		);
		if (Array.isArray(stored)) return stored;
	} catch {
		// fall through to default
	}
	return null; // null = "not chosen yet" -> default to all connected once loaded
};

export const MarketplaceProvider = ({ children }) => {
	const { isAuthenticated } = useAuth();
	const [selected, setSelected] = useState(loadSelection);

	const { data: marketplaces = [], isLoading } = useQuery({
		queryKey: ["marketplaces"],
		queryFn: () => api.get("/reference/marketplaces"),
		enabled: isAuthenticated,
		staleTime: Infinity, // reference data; rarely changes
	});

	const connected = useMemo(
		() => marketplaces.filter((m) => m.connected).map((m) => m.slug),
		[marketplaces],
	);

	const persist = useCallback((next) => {
		setSelected(next);
		localStorage.setItem(STORAGE_KEYS.marketplaces, JSON.stringify(next));
	}, []);

	// Default to all connected once the list arrives and nothing is chosen yet.
	useEffect(() => {
		if (selected === null && connected.length > 0) {
			setSelected(connected);
		}
	}, [selected, connected]);

	// Drop any selection that's no longer connected (config/data changed).
	const effectiveSelected = useMemo(
		() => (selected ?? []).filter((slug) => connected.includes(slug)),
		[selected, connected],
	);

	const toggle = useCallback(
		(slug) => {
			if (!connected.includes(slug)) return; // can't select unconnected
			const next = effectiveSelected.includes(slug)
				? effectiveSelected.filter((s) => s !== slug)
				: [...effectiveSelected, slug];
			persist(next);
		},
		[effectiveSelected, connected, persist],
	);

	const selectAll = useCallback(
		() => persist(connected),
		[connected, persist],
	);

	const allSelected =
		connected.length > 0 && effectiveSelected.length === connected.length;

	const value = {
		marketplaces, // full list incl. unconnected, for the picker
		selected: effectiveSelected, // connected + selected slugs (for queryKeys)
		isLoading,
		allSelected,
		toggle,
		selectAll,
	};

	return (
		<MarketplaceContext.Provider value={value}>
			{children}
		</MarketplaceContext.Provider>
	);
};

export const useMarketplaces = () => {
	const ctx = useContext(MarketplaceContext);
	if (!ctx)
		throw new Error(
			"useMarketplaces must be used within <MarketplaceProvider>",
		);
	return ctx;
};
