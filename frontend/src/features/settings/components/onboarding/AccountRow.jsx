import { useState } from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { Button } from "../../../../components/ui/Button";
import { StatusPill } from "../StatusPill";
import { useLoginJob, useSaveCredentials, useStartLogin } from "../../hooks";

const DONE = new Set(["success", "failed"]);

/**
 * One marketplace account: its login details, a Connect button that saves them and
 * starts the sign-in, and a status line for what the sign-in is doing.
 */
export const AccountRow = ({ platform }) => {
	const save = useSaveCredentials();
	const login = useStartLogin();
	const [jobId, setJobId] = useState(null);
	const { data: job, error: jobError } = useLoginJob(jobId);

	const [email, setEmail] = useState(platform.login_email ?? "");
	const [password, setPassword] = useState("");
	const [error, setError] = useState(null);

	const changed = email.trim() !== (platform.login_email ?? "") || password;
	const needsPassword = platform.needs_password && !platform.has_password;
	// Drives this row only — the sign-in runs on the server whatever the poll says.
	const running = Boolean(jobId) && !jobError && !DONE.has(job?.status);
	const busy = save.isPending || login.isPending || running;

	const connect = async () => {
		setError(null);
		try {
			if (changed || !platform.has_credentials) {
				await save.mutateAsync({
					platform: platform.platform,
					email: email.trim(),
					// An empty string would store a blank password, or wipe a saved one.
					password: password || undefined,
				});
				setPassword("");
			}
			const res = await login.mutateAsync(platform.platform);
			setJobId(res.job_id);
		} catch (err) {
			setError(err.message);
		}
	};

	const field =
		"w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-content outline-none transition-colors placeholder:text-content-subtle focus:border-content-subtle focus:ring-4 focus:ring-brand/12";
	const label = "mb-1.5 block text-xs font-medium text-content-muted";

	return (
		<article className="overflow-hidden rounded-xl border border-border">
			<header className="flex items-center justify-between gap-3 border-b border-border bg-muted/40 px-4 py-2.5">
				<h4 className="truncate text-sm font-semibold text-content">
					{platform.name}
				</h4>
				<StatusPill platform={platform} />
			</header>

			<div className="flex flex-col gap-4 px-4 py-4">
				<div
					className={`grid gap-3 ${platform.needs_password ? "sm:grid-cols-2" : ""}`}
				>
					<label className="block">
						<span className={label}>Login email</span>
						<input
							type="email"
							value={email}
							onChange={(e) => setEmail(e.target.value)}
							placeholder="the address this marketplace emails"
							className={field}
							autoComplete="off"
						/>
					</label>
					{platform.needs_password && (
						<label className="block">
							<span className={label}>Password</span>
							<input
								type="password"
								value={password}
								onChange={(e) => setPassword(e.target.value)}
								placeholder={
									platform.has_password
										? "saved · type to replace"
										: "required"
								}
								className={field}
								autoComplete="new-password"
							/>
						</label>
					)}
				</div>

				<div className="flex flex-wrap items-center justify-between gap-3">
					{/* Waiting, connected, failed, or what has to happen first. */}
					<p className="min-w-0 flex-1 text-xs text-content-muted">
						{running && (
							<span className="flex items-center gap-1.5">
								<Loader2 size={13} className="animate-spin" />
								Waiting for the sign-in email to reach us —
								usually under a minute.
							</span>
						)}
						{!running && job?.status === "success" && (
							<span
								className={`flex items-center gap-1.5 ${
									platform.connected
										? "text-success"
										: "text-warning"
								}`}
							>
								<CheckCircle2 size={13} />
								{platform.connected
									? "Connected."
									: "Signed in, but no session came back. Check forwarding, then try again."}
							</span>
						)}
						{!running && job?.status === "failed" && (
							<span className="flex items-center gap-1.5 text-danger">
								<XCircle size={13} />
								Couldn't sign in
								{job.error ? `: ${job.error}` : "."}
							</span>
						)}
						{!running && jobError && !error && (
							<span className="flex items-center gap-1.5">
								<CheckCircle2 size={13} />
								Sign-in started. Its result can't be shown here
								yet — the status above updates when it
								completes.
							</span>
						)}
						{!running &&
							!jobError &&
							!job &&
							!error &&
							platform.connected && (
								<>
									Connected. Reconnect only if sign-in has
									stopped working.
								</>
							)}
						{!running &&
							!jobError &&
							!job &&
							!error &&
							!platform.connected && (
								<>
									Forwarding must be set up before this can
									succeed.
								</>
							)}
						{error && <span className="text-danger">{error}</span>}
					</p>

					<Button
						variant={
							platform.connected ? "secondary" : "brandSolid"
						}
						size="md"
						disabled={
							!email.trim() ||
							(needsPassword && !password) ||
							busy
						}
						onClick={connect}
					>
						{busy && <Loader2 size={14} className="animate-spin" />}
						{platform.connected ? "Reconnect" : "Connect"}
					</Button>
				</div>
			</div>
		</article>
	);
};
