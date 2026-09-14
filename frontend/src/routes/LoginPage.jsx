import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Eye, EyeOff, ArrowRight, ShieldCheck } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { Logo } from "../layout/Logo";

/**
 * Sign in. A page rather than a modal over the landing screen: this is the front
 * door of a paid product, and a dialog floating on a placeholder reads as
 * unfinished. It is also the only place a password is entered — there is no
 * public signup, accounts are provisioned per account-holder.
 *
 * Two panels. The left states what the product is, for the one person in ten who
 * arrives here without knowing; it is decoration only and is dropped below `lg`,
 * where the form deserves the whole screen. The right is the form, and nothing
 * competes with it.
 *
 * The panel is a matte near-black, not brand red. Red is this product's accent and
 * only works as one: covering half the screen in it shouts, and the thing being
 * shouted over is the only control on the page. On this ground the red lockup carries
 * the brand on its own.
 *
 * ⚠️ Not `--color-inverse` (#3f3b39). That token is for small dark surfaces — tooltips,
 * grand-total rows — where a warm mid-grey reads as raised. Across half a screen it
 * reads as washed out rather than deliberate, so this is a deeper, flatter value. Kept
 * warm (a touch of red in it) so it sits with the cream surface beside it instead of
 * looking like a different product's black.
 */
const PROOF = [
	"Sales, inventory, ads and competitors in one place",
	"Blinkit and Zepto, refreshed every day",
	"Bid and budget automation that runs while you sleep",
];

export const LoginPage = () => {
	const { login } = useAuth();
	const navigate = useNavigate();
	const location = useLocation();
	// Where the reader was headed before the session check bounced them. Sending them
	// on to it afterwards is the difference between signing in and starting again.
	const from = location.state?.from?.pathname ?? "/overview";

	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [reveal, setReveal] = useState(false);
	const [capsOn, setCapsOn] = useState(false);
	const [error, setError] = useState(null);
	const [submitting, setSubmitting] = useState(false);
	const emailRef = useRef(null);

	useEffect(() => emailRef.current?.focus(), []);

	const onSubmit = async (e) => {
		e.preventDefault();
		if (submitting) return;
		setError(null);
		setSubmitting(true);
		try {
			await login(email.trim(), password);
			navigate(from, { replace: true });
		} catch (err) {
			setError(err.message);
			setSubmitting(false);
		}
		// Deliberately no `finally`: on success this component is unmounting, and
		// setting state on the way out is a warning for no benefit.
	};

	/**
	 * ⚠️ Focus and error cannot both be "red border". The brand is red and so is
	 * `--color-danger`, so at a glance a focused field looked like a rejected one.
	 * Focus is a soft halo with a neutral border; an invalid field keeps the red
	 * border AND is named in the alert below, so the state is never carried by
	 * colour alone.
	 */
	const field =
		"w-full rounded-lg border bg-card px-3.5 py-2.5 text-sm text-content transition-[border-color,box-shadow] outline-none placeholder:text-content-subtle";
	const fieldState = error
		? "border-danger focus:ring-4 focus:ring-danger/15"
		: "border-border focus:border-content-subtle focus:ring-4 focus:ring-brand/12";

	return (
		<div className="flex min-h-screen">
			{/* The brand half. `aria-hidden`: every word here is also said elsewhere, and a
			    screen reader should reach the form without wading through a poster. */}
			<aside
				aria-hidden="true"
				className="hidden w-[40%] max-w-xl flex-col justify-between bg-[#18140f] p-12 lg:flex xl:p-14"
			>
				<Logo size="lg" />

				<div>
					<h2 className="font-display text-[2.1rem] leading-[1.12] font-extrabold tracking-[-0.03em] text-on-inverse xl:text-[2.6rem]">
						Know what your shelf
						<br />
						is doing today.
					</h2>
					<ul className="mt-8 flex flex-col gap-3.5">
						{PROOF.map((line) => (
							<li
								key={line}
								className="flex items-start gap-3 text-[15px] leading-snug text-on-inverse/80"
							>
								<span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-brand" />
								{line}
							</li>
						))}
					</ul>
				</div>

				<p className="text-xs text-on-inverse/60">
					© {new Date().getFullYear()} Foresight
				</p>
			</aside>

			<main className="flex flex-1 flex-col justify-center bg-surface px-6 py-12 sm:px-12">
				<div className="mx-auto w-full max-w-sm">
					{/* The mark carries the brand on narrow screens, where the panel is gone. */}
					<div className="mb-10 lg:hidden">
						<Logo size="lg" />
					</div>

					<h1 className="font-display text-2xl font-extrabold tracking-[-0.02em] text-content">
						Sign in
					</h1>
					<p className="mt-1.5 text-sm text-content-muted">
						Welcome back. Enter your details to reach your
						dashboard.
					</p>

					<form
						onSubmit={onSubmit}
						className="mt-8 flex flex-col gap-5"
					>
						<div>
							<label
								htmlFor="email"
								className="mb-1.5 block text-xs font-semibold tracking-wide text-content-muted uppercase"
							>
								Email
							</label>
							<input
								id="email"
								ref={emailRef}
								type="email"
								value={email}
								onChange={(e) => setEmail(e.target.value)}
								required
								autoComplete="email"
								placeholder="you@company.com"
								aria-invalid={Boolean(error)}
								className={`${field} ${fieldState}`}
							/>
						</div>

						<div>
							<label
								htmlFor="password"
								className="mb-1.5 block text-xs font-semibold tracking-wide text-content-muted uppercase"
							>
								Password
							</label>
							<div className="relative">
								<input
									id="password"
									type={reveal ? "text" : "password"}
									value={password}
									onChange={(e) =>
										setPassword(e.target.value)
									}
									// Caps lock is the single most common reason a correct
									// password is rejected, and the field hides the evidence.
									onKeyUp={(e) =>
										setCapsOn(
											e.getModifierState?.("CapsLock") ??
												false,
										)
									}
									required
									autoComplete="current-password"
									placeholder="••••••••"
									aria-invalid={Boolean(error)}
									className={`${field} ${fieldState} pr-11`}
								/>
								<button
									type="button"
									onClick={() => setReveal((r) => !r)}
									aria-label={
										reveal
											? "Hide password"
											: "Show password"
									}
									className="absolute top-1/2 right-1 -translate-y-1/2 rounded-md p-2 text-content-subtle transition-colors hover:text-content"
								>
									{reveal ? (
										<EyeOff size={16} strokeWidth={1.75} />
									) : (
										<Eye size={16} strokeWidth={1.75} />
									)}
								</button>
							</div>
							{capsOn && (
								<p className="mt-1.5 text-xs text-warning">
									Caps lock is on.
								</p>
							)}
						</div>

						{/* role=alert, so the failure is announced rather than only shown. */}
						{error && (
							<p
								role="alert"
								className="rounded-lg border border-danger/30 bg-danger-soft px-3 py-2.5 text-sm text-danger"
							>
								{error}
							</p>
						)}

						<button
							type="submit"
							disabled={submitting}
							className="group mt-1 flex w-full items-center justify-center gap-2 rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-on-brand shadow-sm transition-all hover:bg-brand-hover hover:shadow active:translate-y-px disabled:cursor-not-allowed disabled:opacity-60"
						>
							{submitting ? "Signing in…" : "Sign in"}
							{!submitting && (
								<ArrowRight
									size={16}
									strokeWidth={2}
									className="transition-transform group-hover:translate-x-0.5"
								/>
							)}
						</button>
					</form>

					{/* There is no public signup, so this replaces the "Create an account"
					    link a reader expects to find. Saying who to ask beats a dead end. */}
					<p className="mt-8 flex items-start gap-2 text-xs leading-relaxed text-content-subtle">
						<ShieldCheck
							size={14}
							strokeWidth={1.75}
							className="mt-0.5 shrink-0"
						/>
						Accounts are created by your Foresight administrator. If
						you need access, or cannot get in, contact your account
						manager.
					</p>
				</div>
			</main>
		</div>
	);
};
