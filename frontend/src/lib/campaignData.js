/**
 * Campaign data lives behind several query keys, in several features. This is the one
 * place that knows all of them.
 *
 * Why it exists. A campaign's budget, status and keyword bids are read by four different
 * screens, each with its own cache key and its own `staleTime`. When a write lands on the
 * VM, EVERY one of them is out of date — but the page that triggered the write only knew
 * about its own key, so the others kept serving the old value for minutes afterwards.
 *
 * The sharp case is Ads Insights, because its number is a RATIO. Budget utilisation is
 * spend ÷ daily_budget, so a stale denominator does not look stale — it produces a
 * confident, plausible, wrong percentage. Raise a budget from ₹200 to ₹700 and its card
 * reads ~90% utilised when the truth is ~26%.
 *
 * It lives in `lib/` rather than in a feature because features must not import each other
 * (see the note in features/one-time-ops/api.js). Both sides importing one neutral module
 * keeps that rule intact and gives the next consumer a single line to add.
 */

/**
 * Every query key prefix whose data a campaign write invalidates.
 *
 * Prefixes only — React Query matches by prefix, so each entry also covers that key's
 * variants (`["auto-campaigns", id, "range", days]`, `…, "bid-context", campaignId]`
 * and so on) without listing them.
 */
export const CAMPAIGN_DATA_KEYS = [
	"auto-campaigns", // features/automations — pickers, wizard prefill, bid context
	"ots-campaigns", // features/one-time-ops — the campaign table
	"ads-campaigns-all", // features/ads-insights — budget utilisation (the ratio, above)
	// Deprecated with the /campaign-manager page. Listed anyway because the page is still
	// routed and showing it a stale budget is worse than carrying one string; delete this
	// line when the page goes.
	"cm-campaigns",
];

/**
 * Mark every screen's campaign data stale after a write has landed.
 *
 * ⚠️ Call this when a JOB SETTLES, never when a mutation resolves. These writes happen on
 * the VM: the mutation only enqueues, so invalidating there refetches the value as it was
 * BEFORE the change and caches it as fresh — strictly worse than not invalidating at all.
 *
 * Invalidates rather than patches, deliberately. The engine applies its own guardrails
 * against a fresh read, so a job can settle having done something other than what was
 * asked; what the account now says is the only reliable answer.
 */
export const invalidateCampaignData = (queryClient, clientId) => {
	for (const key of CAMPAIGN_DATA_KEYS) {
		queryClient.invalidateQueries({ queryKey: [key, clientId] });
	}
};
