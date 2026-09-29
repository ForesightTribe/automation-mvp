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
 *
 * A SECOND selection lives here too: the one marketplace the automation pages act on
 * (`automation`). Those pages cannot show "All" — every campaign-manager address names
 * one marketplace — so they keep their own single choice, remembered separately. Picking
 * Zepto on the Automations page never narrows what Overview shows, and vice versa.
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

const loadAutomation = () => {
	try {
		return localStorage.getItem(STORAGE_KEYS.automationMarketplace);
	} catch {
		return null;
	}
};

export const MarketplaceProvider = ({ children }) => {
	const { isAuthenticated } = useAuth();
	const [selected, setSelected] = useState(loadSelection);
	const [automationChoice, setAutomationChoice] = useState(loadAutomation);

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

	// A pill row is a choice between marketplaces, not a set of independent checkboxes:
	// clicking one means "show me this one", and "All" is how you get back to everything.
	// `toggle` stays for any caller that wants the additive behaviour.
	const selectOnly = useCallback(
		(slug) => {
			if (!connected.includes(slug)) return;
			persist([slug]);
		},
		[connected, persist],
	);

	// ── The automation pages' single marketplace ────────────────────────────────
	//
	// Selectable = connected AND driven by the campaign manager (`automations`, from the
	// adapter registry — so a marketplace gains its pill the day it gains an adapter).
	const automatable = useMemo(
		() =>
			marketplaces
				.filter((m) => m.connected && m.automations)
				.map((m) => m.slug),
		[marketplaces],
	);

	const selectAutomation = useCallback(
		(slug) => {
			if (!automatable.includes(slug)) return;
			setAutomationChoice(slug);
			try {
				localStorage.setItem(STORAGE_KEYS.automationMarketplace, slug);
			} catch {
				// a remembered choice is a convenience; the page works without it
			}
		},
		[automatable],
	);

	// Entering an automation page while the navbar shows exactly ONE marketplace means that
	// marketplace was being looked at, so the page opens on it. Otherwise the page keeps the
	// last one used there. Called by the navbar on ENTRY only (this provider sits outside the
	// router, so it cannot see the route itself) — once on the page, its own pills decide.
	const enterAutomationPage = useCallback(() => {
		if (
			effectiveSelected.length === 1 &&
			automatable.includes(effectiveSelected[0])
		) {
			selectAutomation(effectiveSelected[0]);
		}
	}, [effectiveSelected, automatable, selectAutomation]);

	// The choice actually in force: the remembered one while it is still selectable, else
	// the first selectable marketplace. It is shown lit on the navbar, so it is never a
	// silent default — the page says which marketplace it is acting on.
	const automation = automatable.includes(automationChoice)
		? automationChoice
		: (automatable[0] ?? null);
	const automationInfo = marketplaces.find((m) => m.slug === automation);

	const value = {
		marketplaces, // full list incl. unconnected, for the picker
		selected: effectiveSelected, // connected + selected slugs (for queryKeys)
		isLoading,
		allSelected,
		toggle,
		selectOnly,
		selectAll,
		automatable,
		enterAutomationPage,
		automation,
		automationInfo,
		selectAutomation,
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

/**
 * The ONE marketplace the automation pages act on, with what those pages need to know
 * about it: its slug (part of every campaign-manager address), its display name for copy,
 * and its published minimum daily budget (Zepto ₹500, Blinkit none).
 *
 * `marketplace` is null until the reference list loads; callers keep their queries
 * disabled until then rather than guessing one.
 */
export const useAutomationMarketplace = () => {
	const { automation, automationInfo } = useMarketplaces();
	return {
		marketplace: automation,
		name: automationInfo?.name ?? "the marketplace",
		minDailyBudget: automationInfo?.min_daily_budget ?? null,
		// Why keyword-bid automations are off on this marketplace (Zepto, for now), or null
		// when they are available. From the server, so switching it back on needs no deploy.
		keywordBiddingOff: automationInfo?.keyword_bidding_off ?? null,
	};
};
