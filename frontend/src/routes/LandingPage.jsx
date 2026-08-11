import { useState } from "react";
import { useLocation } from "react-router-dom";
import { Button } from "../components/ui/Button";
import { LoginModal } from "../components/auth/LoginModal";
import { Logo } from "../layout/Logo";

/**
 * Public marketing page at `/` for logged-out visitors. Dummy placeholder for
 * now — a hero + a "Log in" CTA that opens the LoginModal (there is no separate
 * /login route). Sits outside RequireAuth; logged-in users are bounced to
 * /overview by RedirectIfAuth before they ever see it.
 *
 * The modal only opens on an explicit "Log in" click — never automatically. (We
 * deliberately don't auto-open from `location.state.from`: that state survives a
 * refresh and would re-pop the modal after logout.) We still read `from` and
 * hand it to the modal so a logged-out deep-link returns the user there after
 * signing in.
 */
export const LandingPage = () => {
	const location = useLocation();
	const from = location.state?.from;
	const [showLogin, setShowLogin] = useState(false);

	return (
		<div className="flex min-h-screen flex-col">
			<header className="flex h-14 shrink-0 items-center justify-between px-4 lg:px-6 xl:px-8 2xl:px-10">
				<Logo />
				<Button
					variant="brand"
					size="sm"
					onClick={() => setShowLogin(true)}
				>
					Log in
				</Button>
			</header>

			<main className="flex flex-1 flex-col items-center justify-center gap-6 px-4 text-center">
				<h1 className="max-w-2xl font-display text-4xl font-bold text-content sm:text-5xl">
					Competitive intelligence for q-commerce brands.
				</h1>
				<p className="max-w-xl text-base text-content-muted">
					Track your sales, inventory, ads, and competitors across
					Blinkit, Instamart, and Zepto — in one dashboard.
				</p>
				<Button variant="brand-solid" size="lg" onClick={() => setShowLogin(true)}>
					Log in to your dashboard
				</Button>
			</main>

			<LoginModal
				open={showLogin}
				onClose={() => setShowLogin(false)}
				from={from?.pathname ?? "/overview"}
			/>
		</div>
	);
};
