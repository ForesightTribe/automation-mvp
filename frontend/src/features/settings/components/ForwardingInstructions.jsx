import { useState } from "react";

/**
 * How a brand forwards its marketplace sign-in mail to us, per mail provider. The
 * destination address is handed over separately and is not shown here.
 */
const PROVIDERS = {
	Gmail: [
		"Open Gmail, then Settings → See all settings → Forwarding and POP/IMAP.",
		"Click Add a forwarding address and paste the address you were given.",
		"Gmail sends a confirmation code to that address. Enter the code in Gmail once you have it.",
		"Add a filter for the marketplace emails and tick Forward it to that address, then Save.",
	],
	Outlook: [
		"Open Outlook, then Settings → Mail → Forwarding.",
		"Turn on Enable forwarding and paste the address you were given.",
		"Tick Keep a copy of forwarded messages, then Save.",
	],
	Other: [
		"Open your mail provider's forwarding or filter settings.",
		"Forward the marketplace emails to the address you were given, keeping a copy in your inbox.",
		"If your provider asks to verify the address, enter the confirmation code it sends.",
	],
};

export const ForwardingInstructions = () => {
	const [tab, setTab] = useState("Gmail");

	return (
		<div className="flex flex-col gap-4">
			<div
				className="inline-flex self-start rounded-lg border border-border p-0.5"
				role="tablist"
			>
				{Object.keys(PROVIDERS).map((k) => (
					<button
						key={k}
						type="button"
						role="tab"
						aria-selected={tab === k}
						onClick={() => setTab(k)}
						className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
							tab === k
								? "bg-inverse text-on-inverse"
								: "text-content-muted hover:bg-muted"
						}`}
					>
						{k}
					</button>
				))}
			</div>
			<ol className="flex flex-col gap-2">
				{PROVIDERS[tab].map((step, i) => (
					<li key={step} className="flex gap-3 text-sm text-content">
						<span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-semibold text-content-muted">
							{i + 1}
						</span>
						<span className="leading-relaxed">{step}</span>
					</li>
				))}
			</ol>
		</div>
	);
};
