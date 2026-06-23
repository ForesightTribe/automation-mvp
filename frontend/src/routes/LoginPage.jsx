import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";

/** Login screen. The only place a password is entered (no public signup). */
export const LoginPage = () => {
	const { login } = useAuth();
	const navigate = useNavigate();
	const location = useLocation();
	const from = location.state?.from?.pathname ?? "/";

	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [error, setError] = useState(null);
	const [submitting, setSubmitting] = useState(false);

	const onSubmit = async (e) => {
		e.preventDefault();
		setError(null);
		setSubmitting(true);
		try {
			await login(email, password);
			navigate(from, { replace: true });
		} catch (err) {
			setError(err.message);
		} finally {
			setSubmitting(false);
		}
	};

	const inputClass =
		"w-full rounded-md border border-border bg-card px-3 py-2 text-sm text-content outline-none focus:border-primary";

	return (
		<div className="flex h-screen items-center justify-center p-4">
			<Card className="w-full max-w-sm">
				<h1 className="mb-1 font-display text-xl font-bold text-content">
					Foresight
				</h1>
				<p className="mb-6 text-sm text-content-muted">
					Sign in to your dashboard.
				</p>

				<form onSubmit={onSubmit} className="flex flex-col gap-4">
					<div className="flex flex-col gap-1">
						<label className="text-xs font-medium text-content-muted">
							Email
						</label>
						<input
							type="email"
							value={email}
							onChange={(e) => setEmail(e.target.value)}
							required
							className={inputClass}
						/>
					</div>
					<div className="flex flex-col gap-1">
						<label className="text-xs font-medium text-content-muted">
							Password
						</label>
						<input
							type="password"
							value={password}
							onChange={(e) => setPassword(e.target.value)}
							required
							className={inputClass}
						/>
					</div>

					{error && <p className="text-sm text-danger">{error}</p>}

					<Button
						type="submit"
						disabled={submitting}
						className="w-full"
					>
						{submitting ? "Signing in…" : "Sign in"}
					</Button>
				</form>
			</Card>
		</div>
	);
};
