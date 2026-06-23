import { QueryClient } from "@tanstack/react-query";

/**
 * Global React Query config. `staleTime` is the heart of it: data is treated as
 * fresh (served from cache, no refetch) for this long; after it, the next
 * trigger (remount, window focus, queryKey change) refetches in the background.
 *
 * Dashboard data is scraped roughly daily, so a generous 5-minute default
 * avoids needless refetching. Override per-query where something must be fresher
 * (pass `staleTime` to useQuery), or set `refetchInterval` for true polling.
 */
export const queryClient = new QueryClient({
	defaultOptions: {
		queries: {
			staleTime: 5 * 60 * 1000, // 5 minutes
			retry: 1,
			refetchOnWindowFocus: false,
		},
	},
});
