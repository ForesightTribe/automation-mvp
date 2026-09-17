import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, Check, Mail, Plug } from "lucide-react";
import { Modal } from "../../../../components/ui/Modal";
import { Button } from "../../../../components/ui/Button";
import { Loading } from "../../../../components/feedback/Loading";
import { ErrorState } from "../../../../components/feedback/ErrorState";
import { useClient } from "../../../../context/ClientContext";
import { ForwardingInstructions } from "../ForwardingInstructions";
import { AccountRow } from "./AccountRow";
import { usePlatforms } from "../../hooks";

/**
 * Connecting one marketplace account, in four steps: what's involved, forward the login
 * mail, sign in, confirm. The account comes from the Connect button that opened it.
 *
 * Step ticks: Connect and Finish need a live session; Forward is the reader's own claim,
 * which a live session overrides and locks.
 */

const STEPS = [
	{ key: "intro", label: "Before you start", hint: "What this involves" },
	{ key: "forward", label: "Forward emails", hint: "One address, once" },
	{ key: "connect", label: "Connect account", hint: "Sign in" },
	{ key: "done", label: "Finish", hint: "Confirm and close" },
];

const HOW = [
	{
		icon: Mail,
		title: "Forward the login emails",
		body: "Marketplaces sign in with an emailed code. Forwarding it to us means we can keep the connection alive for you.",
	},
	{
		icon: Plug,
		title: "Connect the account",
		body: "Enter the login email and connect. Sessions renew themselves after that.",
	},
];

/** The sequence, and where the reader is in it. */
const Rail = ({ step, done, onSelect }) => (
	<nav
		aria-label="Onboarding steps"
		className="shrink-0 border-b border-border bg-muted/40 px-4 py-4 md:w-60 md:border-r md:border-b-0 md:px-5 md:py-7"
	>
		<ol className="relative flex gap-1 overflow-x-auto md:flex-col md:gap-0 md:overflow-visible">
			{STEPS.map((s, i) => {
				const active = i === step;
				const ticked = done[s.key];
				const last = i === STEPS.length - 1;
				return (
					<li
						key={s.key}
						className="relative shrink-0 md:pb-5 md:last:pb-0"
					>
						{/* The thread between markers: the sequence made visible. */}
						{!last && (
							<span
								aria-hidden
								className={`absolute top-7 bottom-1 left-[11px] hidden w-px md:block ${
									ticked ? "bg-success/50" : "bg-border"
								}`}
							/>
						)}
						<button
							type="button"
							onClick={() => onSelect(i)}
							aria-current={active ? "step" : undefined}
							className="group relative flex w-full items-start gap-3 rounded-md px-1.5 py-1 text-left md:px-0"
						>
							<span
								className={`mt-px flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold transition-colors ${
									ticked
										? "border-success bg-success text-on-primary"
										: active
											? "border-content bg-content text-card"
											: "border-border bg-card text-content-subtle group-hover:border-content-subtle"
								}`}
							>
								{ticked ? (
									<Check size={12} strokeWidth={3} />
								) : (
									i + 1
								)}
							</span>
							<span className="min-w-0">
								<span
									className={`block text-[13px] leading-5 whitespace-nowrap ${
										active
											? "font-semibold text-content"
											: "font-medium text-content-muted group-hover:text-content"
									}`}
								>
									{s.label}
								</span>
								<span className="hidden text-[11px] leading-4 text-content-subtle md:block">
									{s.hint}
								</span>
							</span>
						</button>
					</li>
				);
			})}
		</ol>
	</nav>
);

const Step = ({ title, lede, children }) => (
	<div className="flex flex-col gap-5">
		<header className="flex flex-col gap-1">
			<h3 className="font-display text-lg font-semibold text-content">
				{title}
			</h3>
			{lede && (
				<p className="max-w-prose text-sm leading-relaxed text-content-muted">
					{lede}
				</p>
			)}
		</header>
		{children}
	</div>
);

export const OnboardingModal = ({ open, platform, onClose }) => {
	const { activeClient } = useClient();
	const { data: platforms, isLoading, error, refetch } = usePlatforms();

	const [step, setStep] = useState(0);
	const [forwarded, setForwarded] = useState(false);

	// The account this was opened for. Read from the live list, so its status updates
	// while the modal is open (a sign-in finishing flips it to connected).
	const account =
		(platforms ?? []).find((p) => p.platform === platform) ?? null;
	const connected = Boolean(account?.connected);
	// Forwarding can't be observed from here, but a live session proves it works.
	const mailOk = forwarded || connected;

	// Start from the top each time it opens, for whichever account it opens on —
	// including the forwarding tick, which is a claim about THIS setup, not a
	// preference to carry into the next account.
	useEffect(() => {
		if (!open) return;
		setStep(0);
		setForwarded(false);
	}, [open, platform]);

	const done = {
		intro: step > 0,
		forward: mailOk,
		connect: connected,
		done: connected && step === 3,
	};

	const canContinue = step === 0 || (step === 1 && mailOk) || step === 2;

	const footer = (
		<div className="flex items-center justify-between gap-4">
			<Button
				variant="ghost"
				size="md"
				onClick={() => setStep((s) => s - 1)}
				className={step === 0 ? "pointer-events-none opacity-0" : ""}
			>
				<ArrowLeft size={14} /> Back
			</Button>
			<span className="text-xs text-content-subtle tabular-nums">
				{step + 1} / {STEPS.length}
			</span>
			{step < 3 ? (
				<Button
					variant="brandSolid"
					size="md"
					disabled={!canContinue}
					onClick={() => setStep((s) => s + 1)}
				>
					{step === 0 ? "Start" : "Continue"}
					<ArrowRight size={14} />
				</Button>
			) : (
				<Button variant="brandSolid" size="md" onClick={onClose}>
					Done
				</Button>
			)}
		</div>
	);

	return (
		<Modal
			open={open}
			onClose={onClose}
			title={account ? `Connect ${account.name}` : "Connect an account"}
			subtitle={activeClient?.name ?? undefined}
			footer={footer}
			bleed
		>
			{isLoading && (
				<div className="p-8">
					<Loading label="Loading…" />
				</div>
			)}
			{error && (
				<div className="p-8">
					<ErrorState message={error.message} onRetry={refetch} />
				</div>
			)}

			{!isLoading && !error && (
				<div className="flex min-h-[27rem] flex-col md:flex-row">
					<Rail step={step} done={done} onSelect={setStep} />

					<div className="min-w-0 flex-1 px-6 py-6 md:px-8 md:py-7">
						{step === 0 && (
							<Step title="How onboarding works">
								<ol className="flex flex-col divide-y divide-border">
									{HOW.map(
										({ icon: Icon, title, body }, i) => (
											<li
												key={title}
												className="flex gap-4 py-4 first:pt-0"
											>
												<span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-muted text-content-muted">
													<Icon
														size={16}
														strokeWidth={1.75}
													/>
												</span>
												<span className="min-w-0">
													<span className="block text-sm font-semibold text-content">
														{i + 1}. {title}
													</span>
													<span className="text-sm leading-relaxed text-content-muted">
														{body}
													</span>
												</span>
											</li>
										),
									)}
								</ol>
							</Step>
						)}

						{step === 1 && (
							<Step
								title="Forward the login emails to us"
								lede="Set this up once, in the mailbox that receives the marketplace emails. It covers every marketplace."
							>
								<ForwardingInstructions />
								{/* Self-declared: nothing here can observe a client's mail rules.
								    Only a successful sign-in proves forwarding works, which is
								    why a connected account ticks and locks this. */}
								<label className="flex items-center gap-3 rounded-xl border border-border px-4 py-3 text-sm text-content">
									<input
										type="checkbox"
										className="h-4 w-4 accent-inverse"
										checked={mailOk}
										disabled={connected}
										onChange={(e) =>
											setForwarded(e.target.checked)
										}
									/>
									<span>
										I've set up forwarding
										{connected && (
											<span className="block text-xs text-content-subtle">
												Confirmed — this account is
												already connected.
											</span>
										)}
									</span>
								</label>
							</Step>
						)}

						{step === 2 && (
							<Step
								title="Connect the account"
								lede="Enter the email this marketplace sends its login code to, then connect. We'll sign in and keep the session renewed."
							>
								{account ? (
									<AccountRow platform={account} />
								) : (
									<p className="rounded-xl border border-border px-4 py-3 text-sm text-content-muted">
										This marketplace is no longer available.
									</p>
								)}
							</Step>
						)}

						{step === 3 && (
							<Step
								title={
									connected
										? "Connected"
										: "Not connected yet"
								}
								lede={
									connected
										? `${account?.name} is connected. Its data usually appears within a few hours, and the session renews itself from here on.`
										: "The sign-in hasn't completed. Check the forwarding step, then try connecting again."
								}
							>
								{!connected && (
									<div>
										<Button
											variant="secondary"
											size="sm"
											onClick={() => setStep(2)}
										>
											Back to connecting
										</Button>
									</div>
								)}
							</Step>
						)}
					</div>
				</div>
			)}
		</Modal>
	);
};
