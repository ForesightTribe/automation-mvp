import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { Button } from "../ui/Button";

/**
 * Login as a modal over the landing page (no standalone /login route). The only
 * place a password is entered (no public signup). On success it navigates to
 * `from` — the protected route the user was bounced from, else /overview.
 */
export const LoginModal = ({ open, onClose, from = "/overview" }) => {
	const { login } = useAuth();
	const navigate = useNavigate();

	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [error, setError] = useState(null);
	const [submitting, setSubmitting] = useState(false);

	// Close on Escape while open.
	useEffect(() => {
		if (!open) return;
		const onKey = (e) => e.key === "Escape" && onClose();
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [open, onClose]);

	if (!open) return null;

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
		"w-full rounded-md border border-border bg-card px-3 py-2 text-sm text-content outline-none focus:border-brand";

	return (
		// Backdrop — click outside to dismiss.
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
			onClick={onClose}
			role="presentation"
		>
			<div
				className="w-full max-w-sm rounded-xl border border-border bg-card p-6"
				onClick={(e) => e.stopPropagation()}
				role="dialog"
				aria-modal="true"
				aria-label="Log in"
			>
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
							autoFocus
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

					<div className="flex items-center justify-end gap-2">
						<Button
							type="button"
							variant="secondary"
							onClick={onClose}
							disabled={submitting}
						>
							Cancel
						</Button>
						<Button type="submit" variant="brand-solid" disabled={submitting}>
							{submitting ? "Signing in…" : "Sign in"}
						</Button>
					</div>
				</form>
			</div>
		</div>
	);
};
