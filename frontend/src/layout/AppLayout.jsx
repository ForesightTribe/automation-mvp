import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Navbar } from "./Navbar";
import { Footer } from "./Footer";
import { ErrorBoundary } from "../components/feedback/ErrorBoundary";

/**
 * The app shell. The Sidebar owns the ENTIRE left column, full height, including
 * the top-left corner; everything else — Navbar, page, Footer — stacks in the
 * column beside it. Each route renders into <Outlet/>. The ErrorBoundary wraps
 * only the page content, so a crash in one page keeps the nav usable.
 *
 * The rail being a sibling of that column, rather than a layer over it, is what
 * makes collapsing it widen the navbar as well as the page: both are simply the
 * space left over.
 */
export const AppLayout = () => {
	return (
		<div className="flex h-screen overflow-hidden">
			<Sidebar />
			<div className="flex min-h-0 min-w-0 flex-1 flex-col">
				<Navbar />
				{/* Content gutter. 36px is the 1920 value (2xl); it steps down
				    with the viewport — see the scale in Sidebar.jsx. */}
				<main className="flex-1 overflow-y-auto px-4 py-4 lg:px-6 lg:py-6 xl:px-8 2xl:px-9 2xl:py-8">
					<ErrorBoundary>
						<Outlet />
					</ErrorBoundary>
				</main>
				<Footer />
			</div>
		</div>
	);
};
