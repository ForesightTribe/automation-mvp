import { useState } from "react";
import { Plug, Unplug } from "lucide-react";
import { PageHeader } from "../../components/ui/PageHeader";
import { Card } from "../../components/ui/Card";
import { Button } from "../../components/ui/Button";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { Loading } from "../../components/feedback/Loading";
import { ErrorState } from "../../components/feedback/ErrorState";
import { formatDate } from "../../lib/format";
import { StatusPill } from "./components/StatusPill";
import { OnboardingModal } from "./components/onboarding/OnboardingModal";
import { usePlatforms, useDisconnect } from "./hooks";

/**
 * Settings — the brand's marketplace accounts: status, and connect / reconnect /
 * disconnect. Connecting runs in a modal opened from the account it is about.
 */
export const SettingsPage = () => {
	const { data: platforms, isLoading, error, refetch } = usePlatforms();
	const disconnect = useDisconnect();
	// The account whose Connect button was pressed.
	const [connecting, setConnecting] = useState(null);
	const [confirmOff, setConfirmOff] = useState(null);

	return (
		<div className="flex flex-col gap-6">
			<PageHeader
				title="Settings"
				subtitle="Connect and manage the brand's marketplace accounts."
			/>

			<Card title="Marketplace connections">
				{isLoading && <Loading label="Loading connections…" />}
				{error && (
					<ErrorState message={error.message} onRetry={refetch} />
				)}
				{!isLoading && !error && (
					<ul className="-my-2 divide-y divide-border">
						{(platforms ?? []).map((p) => (
							<li
								key={p.platform}
								className="flex flex-wrap items-center justify-between gap-3 py-3"
							>
								<div className="min-w-0">
									<div className="flex flex-wrap items-center gap-2">
										<span className="text-sm font-medium text-content">
											{p.name}
										</span>
										<StatusPill platform={p} />
									</div>
									<div className="mt-0.5 text-xs text-content-subtle">
										{p.login_email ??
											"No login email saved"}
										{p.connected && p.connected_at
											? ` · renewed ${formatDate(p.connected_at)}`
											: ""}
									</div>
								</div>
								{p.wired && (
									<div className="flex gap-2">
										<Button
											variant="secondary"
											size="sm"
											onClick={() =>
												setConnecting(p.platform)
											}
										>
											<Plug size={12} />
											{p.connected
												? "Reconnect"
												: "Connect"}
										</Button>
										{p.connected && (
											<Button
												variant="ghost"
												size="sm"
												onClick={() => setConfirmOff(p)}
											>
												<Unplug size={12} /> Disconnect
											</Button>
										)}
									</div>
								)}
							</li>
						))}
					</ul>
				)}
			</Card>

			<OnboardingModal
				open={Boolean(connecting)}
				platform={connecting}
				onClose={() => setConnecting(null)}
			/>

			<ConfirmDialog
				open={Boolean(confirmOff)}
				title={
					confirmOff
						? `Disconnect ${confirmOff.name}?`
						: "Disconnect this account?"
				}
				confirmLabel="Yes, disconnect"
				danger
				body={
					confirmOff ? (
						<div className="flex flex-col gap-3">
							<p>
								You are about to disconnect this account.
								Foresight will stop signing in to it, which
								means:
							</p>
							<ul className="list-disc space-y-1 pl-5">
								<li>
									Sales, ads and inventory data from it{" "}
									<strong className="text-content">
										stop updating
									</strong>
									. Dashboards and reports will show gaps from
									today.
								</li>
								<li>
									Bid and budget automations on this account{" "}
									<strong className="text-content">
										stop running
									</strong>
									.
								</li>
								<li>
									Mail forwarding is{" "}
									<strong className="text-content">
										not turned off
									</strong>{" "}
									— it lives in your mailbox. Remove it there
									if you no longer want these emails sent to
									us.
								</li>
							</ul>
							<p>
								The saved login details are removed too, so this
								stays off until someone connects it again.
							</p>
						</div>
					) : null
				}
				pending={disconnect.isPending}
				error={disconnect.error?.message}
				onCancel={() => setConfirmOff(null)}
				onConfirm={async () => {
					await disconnect.mutateAsync(confirmOff.platform);
					setConfirmOff(null);
				}}
			/>
		</div>
	);
};
