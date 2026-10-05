import {
	createContext,
	useContext,
	useMemo,
	useState,
	useCallback,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/axios";
import { STORAGE_KEYS } from "../lib/constants";
import { useAuth } from "./AuthContext";
import { useClient } from "./ClientContext";

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
 * The selection is remembered PER CLIENT, and "All" is remembered as itself (see
 * `ALL`). Clients differ in which marketplaces they have, so one shared list of slugs
 * meant whatever was picked for one brand was misread for the next.
 *
 * Two more selections live here, each the ONE marketplace a page that cannot blend
 * acts on, remembered separately so visiting the page never narrows the rest of the
 * dashboard:
 *   - `automation` — the automation pages: every campaign-manager address names one.
 *   - `orders` — Purchase orders: each marketplace's POs are read separately.
 */
const MarketplaceContext = createContext(null);

/**
 * The stored choice meaning "every marketplace this client has".
 *
 * ⚠️ Never stored as the list it currently resolves to. As a list, a one-marketplace
 * client's "All" and its only pill were the same value, so that pill could never light;
 * and the list followed you to the next client, where it meant "only these".
 */
const ALL = "all";

/** The per-client choices: `{ [clientId]: "all" | slug[] }`. */
const loadChoices = () => {
	try {
		const stored = JSON.parse(
			localStorage.getItem(STORAGE_KEYS.marketplaces),
		);
		// A bare array is the old, client-blind format. It is dropped rather than
		// guessed at, so every client starts again on "All".
		if (stored && typeof stored === "object" && !Array.isArray(stored))
			return stored;
	} catch {
		// fall through to default
	}
	return {};
};

const loadSlug = (key) => {
	try {
		return localStorage.getItem(key);
	} catch {
		return null;
	}
};

/**
 * A page-local, one-of choice among `candidates`, remembered under `storageKey`.
 * Resolves to the remembered slug while it is still a candidate, else the first
 * candidate — shown lit on the navbar, so never a silent default.
 */
const useSingleChoice = (storageKey, candidates) => {
	const [choice, setChoice] = useState(() => loadSlug(storageKey));
	const select = useCallback(
		(slug) => {
			if (!candidates.includes(slug)) return;
			setChoice(slug);
			try {
				localStorage.setItem(storageKey, slug);
			} catch {
				// a remembered choice is a convenience; the page works without it
			}
		},
		[candidates, storageKey],
	);
	const current = candidates.includes(choice)
		? choice
		: (candidates[0] ?? null);
	return [current, select];
};

export const MarketplaceProvider = ({ children }) => {
	const { isAuthenticated } = useAuth();
	const [choices, setChoices] = useState(loadChoices);

	const { activeClientId } = useClient();
	const { data, isLoading, error, refetch } = useQuery({
		queryKey: ["marketplaces", activeClientId],
		queryFn: () =>
			api.get("/reference/marketplaces", {
				params: { client_id: activeClientId },
			}),
		enabled: isAuthenticated && Boolean(activeClientId),
		// The server caches this list for 10 minutes; holding it forever here meant a
		// newly connected marketplace stayed hidden until a full reload.
		staleTime: 10 * 60 * 1000,
	});
	const marketplaces = useMemo(() => data ?? [], [data]);

	const connected = useMemo(
		() => marketplaces.filter((m) => m.connected).map((m) => m.slug),
		[marketplaces],
	);

	const choice = choices[activeClientId] ?? ALL;

	const persist = useCallback(
		(next) => {
			const updated = { ...choices, [activeClientId]: next };
			setChoices(updated);
			try {
				localStorage.setItem(
					STORAGE_KEYS.marketplaces,
					JSON.stringify(updated),
				);
			} catch {
				// a remembered choice is a convenience; the page works without it
			}
		},
		[choices, activeClientId],
	);

	// What was picked that this client actually has. Empty — "All", or a pick made for
	// marketplaces it no longer (or never) had — resolves to everything, never to
	// nothing: an empty selection used to leave Overview on its loading screen forever.
	const picked = useMemo(
		() =>
			Array.isArray(choice)
				? choice.filter((slug) => connected.includes(slug))
				: [],
		[choice, connected],
	);
	const effectiveSelected = picked.length ? picked : connected;

	// "All" is only a distinct state when there is more than one marketplace to blend.
	// With one, its pill IS the selection: it lights, and "All" is not offered.
	const allSelected =
		connected.length > 1 && effectiveSelected.length === connected.length;

	const toggle = useCallback(
		(slug) => {
			if (!connected.includes(slug)) return; // can't select unconnected
			const next = effectiveSelected.includes(slug)
				? effectiveSelected.filter((s) => s !== slug)
				: [...effectiveSelected, slug];
			if (!next.length) return; // nothing selected would read as "All"
			persist(next.length === connected.length ? ALL : next);
		},
		[effectiveSelected, connected, persist],
	);

	const selectAll = useCallback(() => persist(ALL), [persist]);

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

	// ⚠️ Until THIS client's marketplace list arrives, `connected` is empty and so is
	// `effectiveSelected` — which reads as "no channels", not "every channel".
	// Queries scoped by marketplace must wait for this rather than run twice and
	// show a channel-less page in between. Keyed on the DATA, not the query status:
	// a failed background refetch keeps the list it had and must not blank the page.
	const ready = data !== undefined;

	// ── The single-marketplace pages ────────────────────────────────────────────
	//
	// Automation: selectable = connected AND driven by the campaign manager (`automations`,
	// from the adapter registry — so a marketplace gains its pill the day it gains an
	// adapter). Orders: any connected marketplace.
	const automatable = useMemo(
		() =>
			marketplaces
				.filter((m) => m.connected && m.automations)
				.map((m) => m.slug),
		[marketplaces],
	);
	const [automation, selectAutomation] = useSingleChoice(
		STORAGE_KEYS.automationMarketplace,
		automatable,
	);
	const [orders, selectOrders] = useSingleChoice(
		STORAGE_KEYS.ordersMarketplace,
		connected,
	);

	// Entering a single-marketplace page while the navbar shows exactly ONE marketplace
	// means that marketplace was being looked at, so the page opens on it. Otherwise the
	// page keeps the last one used there. Called by the navbar on ENTRY only (this provider
	// sits outside the router, so it cannot see the route itself) — once on the page, its
	// own pills decide.
	const enter = useCallback(
		(candidates, select) => {
			if (
				effectiveSelected.length === 1 &&
				candidates.includes(effectiveSelected[0])
			) {
				select(effectiveSelected[0]);
			}
		},
		[effectiveSelected],
	);
	const enterAutomationPage = useCallback(
		() => enter(automatable, selectAutomation),
		[enter, automatable, selectAutomation],
	);
	const enterOrdersPage = useCallback(
		() => enter(connected, selectOrders),
		[enter, connected, selectOrders],
	);

	const automationInfo = marketplaces.find((m) => m.slug === automation);
	const ordersInfo = marketplaces.find((m) => m.slug === orders);

	const value = {
		marketplaces, // full list incl. unconnected, for the picker
		connected, // slugs this client has data for
		selected: effectiveSelected, // connected + selected slugs (for queryKeys)
		ready,
		isLoading,
		error, // the list failed to load: nothing scoped by marketplace can run
		refetch,
		allSelected,
		toggle,
		selectOnly,
		selectAll,
		automatable,
		enterAutomationPage,
		automation,
		automationInfo,
		selectAutomation,
		enterOrdersPage,
		orders,
		ordersInfo,
		selectOrders,
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
