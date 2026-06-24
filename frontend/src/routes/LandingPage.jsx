import { useState } from "react";
import { useLocation } from "react-router-dom";
import { Button } from "../components/ui/Button";
import { LoginModal } from "../components/auth/LoginModal";

/**
 * Public marketing page at `/` for logged-out visitors. Dummy placeholder for
 * now — a hero + a "Log in" CTA that opens the LoginModal (there is no separate
 * /login route). Sits outside RequireAuth; logged-in users are bounced to
 * /overview by RedirectIfAuth before they ever see it.
 *
 * When RequireAuth bounces a logged-out user here, it passes the attempted route
 * as `location.state.from`; we auto-open the modal and hand `from` to it so the
 * user lands back where they were headed after signing in.
 */
export const LandingPage = () => {
	const location = useLocation();
	const from = location.state?.from;
	const [showLogin, setShowLogin] = useState(Boolean(from));

	return (
		<div className="flex min-h-screen flex-col">
			<header className="flex h-14 shrink-0 items-center justify-between px-6">
				<span className="font-display text-lg font-bold text-content">
					Foresight
				</span>
				<Button
					variant="secondary"
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
				<Button size="lg" onClick={() => setShowLogin(true)}>
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
