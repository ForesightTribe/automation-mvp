import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Navbar } from "./Navbar";
import { Footer } from "./Footer";
import { ErrorBoundary } from "../components/feedback/ErrorBoundary";

/**
 * The app shell. Sidebar (left) + a stacked Navbar / main / Footer column.
 * Each route renders into <Outlet/>. The ErrorBoundary wraps only the page
 * content, so a crash in one page keeps the nav usable.
 */
export const AppLayout = () => {
	return (
		<div className="flex h-screen overflow-hidden">
			<Sidebar />
			<div className="flex min-w-0 flex-1 flex-col">
				<Navbar />
				<main className="flex-1 overflow-y-auto p-6">
					<ErrorBoundary>
						<Outlet />
					</ErrorBoundary>
				</main>
				<Footer />
			</div>
		</div>
	);
};
