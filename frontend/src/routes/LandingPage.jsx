import { Link, useLocation } from "react-router-dom";
import { Button } from "../components/ui/Button";
import { Logo } from "../layout/Logo";

/**
 * Public marketing page at `/` for logged-out visitors. Placeholder for now: a
 * hero and a route to /login. Sits outside RequireAuth; logged-in users are
 * bounced to /overview by RedirectIfAuth before they ever see it.
 *
 * Signing in is a PAGE, not a dialog over this one. `from` is carried through
 * untouched, so a logged-out deep link still returns the reader to where they
 * were going.
 */
export const LandingPage = () => {
	const location = useLocation();
	const from = location.state?.from;
	const to = { pathname: "/login", state: from ? { from } : undefined };

	return (
		<div className="flex min-h-screen flex-col bg-surface">
			<header className="flex h-16 shrink-0 items-center justify-between px-6 lg:px-10">
				<Logo />
				<Link to="/login" state={to.state}>
					<Button variant="secondary" size="sm">
						Log in
					</Button>
				</Link>
			</header>

			<main className="flex flex-1 flex-col items-center justify-center gap-6 px-4 pb-20 text-center">
				<h1 className="max-w-3xl font-display text-4xl leading-[1.05] font-extrabold tracking-[-0.03em] text-content sm:text-6xl">
					Competitive intelligence for
					<br className="hidden sm:block" /> q-commerce brands.
				</h1>
				<p className="max-w-xl text-base text-content-muted sm:text-lg">
					Track your sales, inventory, ads and competitors across
					Blinkit and Zepto, in one dashboard.
				</p>
				<Link to="/login" state={to.state} className="mt-2">
					<Button variant="brandSolid" size="lg">
						Log in to your dashboard
					</Button>
				</Link>
			</main>
		</div>
	);
};
