import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Navbar } from "./Navbar";
import { Footer } from "./Footer";
import { ErrorBoundary } from "../components/feedback/ErrorBoundary";

/**
 * The app shell. A full-width Navbar across the top (it carries the brand mark,
 * so it owns the left edge), then a row of Sidebar + main/Footer beneath it.
 * Each route renders into <Outlet/>. The ErrorBoundary wraps only the page
 * content, so a crash in one page keeps the nav usable.
 */
export const AppLayout = () => {
	return (
		<div className="flex h-screen flex-col overflow-hidden">
			<Navbar />
			{/* `relative` anchors the overlay rail — see Sidebar.jsx. */}
			<div className="relative flex min-h-0 flex-1">
				<Sidebar />
				<div className="flex min-w-0 flex-1 flex-col">
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
		</div>
	);
};
