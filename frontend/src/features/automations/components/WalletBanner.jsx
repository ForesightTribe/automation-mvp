import { AlertTriangle, Wallet } from "lucide-react";
import { useAutomationMarketplace } from "../../../context/MarketplaceContext";
import { formatCurrency } from "../../../lib/format";
import { useWalletNote } from "../hooks";

// A wallet note older than this is history, not news: the engine writes one at most every
// six hours while the balance stays low, so a day without one means it has recovered (or
// nothing has run to look).
const FRESH_MS = 24 * 60 * 60 * 1000;

/**
 * The ad wallet running low or empty, said at the top of the page (ZC-E6 / C12).
 *
 * No endpoint reads the wallet: the engine checks it on every budget and bid run and, when
 * the balance is low, files a `kind=wallet` row in History (at most every 6h). This shows
 * the latest such row if it is recent. On a marketplace that never writes one (Blinkit has
 * no prepaid wallet) it simply never appears.
 *
 * A warning, never a block — the engine carries on too. An empty wallet does not make a
 * budget change wrong; it makes it pointless until the wallet is topped up.
 */
export const WalletBanner = () => {
	const { name } = useAutomationMarketplace();
	const { data: row } = useWalletNote();
	if (!row) return null;
	if (Date.now() - new Date(row.timestamp).getTime() > FRESH_MS) return null;

	const empty = row.action === "error";
	const when = new Date(row.timestamp).toLocaleString("en-IN", {
		day: "numeric",
		month: "short",
		hour: "numeric",
		minute: "2-digit",
	});
	return (
		<div
			role="status"
			className={`flex items-start gap-2.5 rounded-md border px-3 py-2 text-sm text-content ${
				empty
					? "border-danger/30 bg-danger-soft"
					: "border-warning/30 bg-warning-soft"
			}`}
		>
			{empty ? (
				<AlertTriangle
					size={16}
					className="mt-0.5 shrink-0 text-danger"
				/>
			) : (
				<Wallet size={16} className="mt-0.5 shrink-0 text-warning" />
			)}
			<span>
				<b>
					{name} ad wallet{" "}
					{row.new_value != null
						? `at ${formatCurrency(row.new_value)}`
						: empty
							? "empty"
							: "low"}
				</b>{" "}
				(checked {when}).{" "}
				{empty
					? `Campaigns cannot spend until it is topped up on ${name}. Budget and bid changes still go through, but they do nothing until then.`
					: `Top it up on ${name} before it runs out — campaigns stop delivering when it is empty.`}
			</span>
		</div>
	);
};
