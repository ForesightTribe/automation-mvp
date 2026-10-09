import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Navbar } from "./Navbar";
import { ErrorBoundary } from "../components/feedback/ErrorBoundary";
import { ErrorState } from "../components/feedback/ErrorState";
import { Loading } from "../components/feedback/Loading";
import { useClient } from "../context/ClientContext";
import { useMarketplaces } from "../context/MarketplaceContext";

/**
 * The app shell. The Sidebar owns the ENTIRE left column, full height, including
 * the top-left corner; everything else — Navbar and page — stacks in the
 * column beside it. Each route renders into <Outlet/>. The ErrorBoundary wraps
 * only the page content, so a crash in one page keeps the nav usable.
 *
 * The rail being a sibling of that column, rather than a layer over it, is what
 * makes collapsing it widen the navbar as well as the page: both are simply the
 * space left over.
 */
export const AppLayout = () => {
	const { activeClientId } = useClient();
	const { ready, error, refetch } = useMarketplaces();

	// ⚠️ Pages wait for the client's marketplace list. Their queries are scoped by it and
	// stay disabled until it lands — and a disabled query reports `isLoading: false`, so a
	// page drawn before then shows its EMPTY state ("No data yet") rather than a loader.
	// One gate here instead of one per page. No client at all means nothing to wait for.
	const page =
		!activeClientId || ready ? (
			<Outlet />
		) : error ? (
			<ErrorState message={error.message} onRetry={refetch} />
		) : (
			<Loading label="Loading…" />
		);

	return (
		<div className="flex h-screen overflow-hidden">
			<Sidebar />
			<div className="flex min-h-0 min-w-0 flex-1 flex-col">
				<Navbar />
				{/* Content gutter. 36px is the 1920 value (2xl); it steps down
				    with the viewport — see the scale in Sidebar.jsx. */}
				<main className="flex-1 overflow-y-auto px-4 py-4 lg:px-6 lg:py-6 xl:px-8 2xl:px-9 2xl:py-8">
					<ErrorBoundary>{page}</ErrorBoundary>
				</main>
			</div>
		</div>
	);
};
