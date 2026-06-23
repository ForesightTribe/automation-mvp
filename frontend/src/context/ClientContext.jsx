import {
	createContext,
	useContext,
	useEffect,
	useState,
	useCallback,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/axios";
import { STORAGE_KEYS } from "../lib/constants";
import { useAuth } from "./AuthContext";

/**
 * Owns the *active client* selection (the Account -> Client switcher). The
 * selected id is app-owned state -> Context. The *list* of clients is server
 * data -> fetched with React Query. This is the canonical split: Context holds
 * "which client", React Query holds "the data for that client", and feature
 * queries put `clientId` in their queryKey so switching auto-refetches.
 */
const ClientContext = createContext(null);

export const ClientProvider = ({ children }) => {
	const { isAuthenticated } = useAuth();
	const [activeClientId, setActiveClientId] = useState(() =>
		localStorage.getItem(STORAGE_KEYS.activeClientId),
	);

	// The account's clients — server data, cached by React Query.
	const { data: clients = [], isLoading } = useQuery({
		queryKey: ["clients"],
		queryFn: () => api.get("/clients"),
		enabled: isAuthenticated, // don't fetch until logged in
	});

	const setActiveClient = useCallback((id) => {
		setActiveClientId(id);
		localStorage.setItem(STORAGE_KEYS.activeClientId, id);
	}, []);

	// Default the active client to the first one once the list arrives.
	useEffect(() => {
		if (!activeClientId && clients.length > 0) {
			setActiveClient(clients[0].id);
		}
	}, [clients, activeClientId, setActiveClient]);

	const activeClient = clients.find((c) => c.id === activeClientId) ?? null;

	const value = {
		clients,
		clientsLoading: isLoading,
		activeClientId,
		activeClient,
		setActiveClient,
	};

	return (
		<ClientContext.Provider value={value}>
			{children}
		</ClientContext.Provider>
	);
};

export const useClient = () => {
	const ctx = useContext(ClientContext);
	if (!ctx) throw new Error("useClient must be used within <ClientProvider>");
	return ctx;
};
