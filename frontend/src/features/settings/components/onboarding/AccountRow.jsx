import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { Button } from "../../../../components/ui/Button";
import { StatusPill } from "../StatusPill";
import { useLoginJob, useSaveCredentials, useStartLogin } from "../../hooks";

const DONE = new Set(["success", "failed"]);

// How long to keep waiting before saying the mail never arrived. The inbox itself
// gives up at 120s; this allows for the job queue and the forward on top.
const WAIT_LIMIT_MS = 4 * 60 * 1000;

/**
 * One marketplace account: its login details, a Connect button that saves them and
 * starts the sign-in, and a waiting state that replaces the form while it runs.
 *
 * A second attempt during that wait would race the first for the same single-use code.
 */
export const AccountRow = ({ platform }) => {
	const save = useSaveCredentials();
	const login = useStartLogin();
	const [jobId, setJobId] = useState(null);
	const { data: job, error: jobError } = useLoginJob(jobId);

	const [email, setEmail] = useState(platform.login_email ?? "");
	const [password, setPassword] = useState("");
	const [error, setError] = useState(null);
	const [startedAt, setStartedAt] = useState(null);
	const [gaveUp, setGaveUp] = useState(false);

	const changed = email.trim() !== (platform.login_email ?? "") || password;
	const needsPassword = platform.needs_password && !platform.has_password;
	// Waiting ends when the session appears (the platform list is polled while this is
	// open), when the job reports back, or when the wait has gone on too long.
	const running =
		Boolean(startedAt) &&
		!gaveUp &&
		!platform.connected &&
		(jobError || !DONE.has(job?.status));

	useEffect(() => {
		if (!startedAt) return;
		const timer = setTimeout(() => setGaveUp(true), WAIT_LIMIT_MS);
		return () => clearTimeout(timer);
	}, [startedAt]);

	// A session appearing is the only proof the sign-in worked; stop waiting on it.
	useEffect(() => {
		if (platform.connected) setStartedAt(null);
	}, [platform.connected]);
	const busy = save.isPending || login.isPending || running;

	const connect = async () => {
		setError(null);
		setGaveUp(false);
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
			setStartedAt(Date.now());
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

			{running ? (
				<div className="flex flex-col items-center gap-3 px-4 py-10 text-center">
					<Loader2
						size={28}
						strokeWidth={1.75}
						className="animate-spin text-brand"
					/>
					<p className="text-sm font-medium text-content">
						Signing in to {platform.name.split(" (")[0]}…
					</p>
				</div>
			) : (
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
									onChange={(e) =>
										setPassword(e.target.value)
									}
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
						<p className="min-w-0 flex-1 text-xs text-content-muted">
							{platform.connected && (
								<span className="flex items-center gap-1.5 text-success">
									<CheckCircle2 size={13} />
									Connected. Reconnect only if sign-in has
									stopped working.
								</span>
							)}
							{!platform.connected && gaveUp && (
								<span className="flex items-center gap-1.5 text-danger">
									<XCircle size={13} />
									No sign-in email reached us. Check that
									forwarding is set up for this address, then
									try again.
								</span>
							)}
							{!platform.connected &&
								!gaveUp &&
								job?.status === "failed" && (
									<span className="flex items-center gap-1.5 text-danger">
										<XCircle size={13} />
										Couldn't sign in
										{job.error ? `: ${job.error}` : "."}
									</span>
								)}
							{!platform.connected &&
								!gaveUp &&
								!job &&
								!error && (
									<>
										Forwarding must be set up before this
										can succeed.
									</>
								)}
							{error && (
								<span className="text-danger">{error}</span>
							)}
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
							{busy && (
								<Loader2 size={14} className="animate-spin" />
							)}
							{platform.connected ? "Reconnect" : "Connect"}
						</Button>
					</div>
				</div>
			)}
		</article>
	);
};
