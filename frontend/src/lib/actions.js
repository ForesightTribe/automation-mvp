import { useMemo } from "react";
import {
	useInfiniteQuery,
	useQuery,
	useQueryClient,
} from "@tanstack/react-query";
import { api } from "./axios";
import { useClient } from "../context/ClientContext";
import { useAutomationMarketplace } from "../context/MarketplaceContext";
import { formatCurrency, parseIst } from "./format";
import { invalidateAfterWrite } from "./campaignData";
import { resultOf } from "./runLog";

/**
 * Actions a person asked for — what they are doing now, and what they actually DID.
 *
 * Shared because two pages need exactly the same answers: Ad Automation shows which rows are
 * busy, and One-time Ops lists its operations and puts each outcome on its campaign row.
 * Features must not import each other (see features/one-time-ops/api.js), so the common part
 * lives here — the same reason `campaignData.js` does. Getting "is this busy" or "what did
 * this run do" subtly different on two pages is how one of them ends up lying.
 *
 * Two sources, deliberately:
 *   - the JOB QUEUE (`/actions`) — exists from the moment an action is queued, so it can say
 *     "queued" and "running", which no history row ever can;
 *   - the RUN LOG (`/history?run_id=`) — what the run actually did, including why a write
 *     was refused. A job's `status: success` only means the process exited; the CM commands
 *     never set a non-zero exit code, so a refused write settles exactly like an accepted one.
 */

// The marketplace is part of every campaign-manager address, with no default on the server
// (ZC-D1): each marketplace's actions and runs are its own. Both pages that read this file —
// Ad Automation and One-time Ops — work on ONE marketplace at a time, the navbar's
// automation choice (`useAutomationMarketplace`), so the hooks below read it themselves.
const base = (clientId, mp) => `/clients/${clientId}/campaign-manager/${mp}`;

const useScope = () => {
	const { activeClientId } = useClient();
	const { marketplace: mp } = useAutomationMarketplace();
	return { activeClientId, mp, ready: Boolean(activeClientId && mp) };
};

export const ACTIVE_JOB_STATUSES = new Set(["pending", "running"]);
export const isActive = (action) => ACTIVE_JOB_STATUSES.has(action?.status);

/** The cache key prefix every recent-actions query shares — `invalidateRecentActions` hits
 *  all of them at once, filtered and not. */
const RECENT_ACTIONS = "recent-actions";

// ── API ─────────────────────────────────────────────────────────────────────

// One page: `{ items, has_more }`. `before` pages BACK by keyset — the `created_at` of the
// oldest item already shown — so a new action arriving at the top can never shift a page and
// show a row twice, which offset paging would do to a live list.
const getRecentActions = (clientId, mp, source, before) =>
	api.get(`${base(clientId, mp)}/actions`, {
		params: {
			...(source ? { source } : {}),
			...(before ? { before } : {}),
		},
	});

// `include_unchanged` is required: a refusal is a `skip` and a write that was not needed is
// a `no-op`, and "nothing changed, and here is why" is exactly the answer being looked for.
const getRunOutcome = (clientId, mp, runId) =>
	api.get(`${base(clientId, mp)}/history`, {
		params: { run_id: runId, limit: 100, include_unchanged: true },
	});

// ── Recent actions ──────────────────────────────────────────────────────────

/**
 * Mark the recent-actions list stale. Call it the moment an action is QUEUED.
 *
 * ⚠️ This is the fix for the list that never refreshed on its own. It only polls while it
 * already shows something in progress — and nothing ever told it a new action existed, so
 * after a click it kept its old all-finished state and never started. One refetch here and
 * the list sees the new job as `pending`, and its own interval takes over.
 *
 * Right on mutation success, unlike campaign data: the API creates the job row BEFORE it
 * answers, so the queue already knows. Campaign data only changes once the job finishes,
 * which is why that is invalidated on settle instead (`invalidateAfterWrite`).
 */
// The prefix — every marketplace's and every source's list for this client at once.
export const invalidateRecentActions = (queryClient, clientId) =>
	queryClient.invalidateQueries({ queryKey: [RECENT_ACTIONS, clientId] });

/**
 * Has any action finished since the list was last seen? Pure — the decision behind "refresh
 * what that action changed".
 *
 * `before` is the previously cached list, or `undefined` on the first load. The first load
 * only seeds: nothing was being watched, so nothing "just" finished — treating it otherwise
 * refetched all campaign data on every page load. After that, an action counts if it was
 * running before and is not now, OR if it is new and already finished — a job fast enough to
 * complete between two polls must still refresh what it changed.
 */
export const finishedSince = (before, actions) => {
	if (before === undefined) return false;
	const prev = new Map(before.map((a) => [a.id, a]));
	return actions.some(
		(a) => !isActive(a) && (!prev.has(a.id) || isActive(prev.get(a.id))),
	);
};

/**
 * How often to re-read the queue while something is unfinished — or `false` to stop.
 *
 * Backs off with the age of the NEWEST unfinished action, not a fixed 2s. A job can sit in the
 * queue for minutes behind a bid run (the lane is held for up to ~9 minutes), and polling every
 * 2s for all of that was ~150 requests — each one a database connection, on a pool that has
 * been exhausted before. So: fast while an action is fresh, when "is it working?" is the
 * question being watched; slower once it is clearly waiting.
 *
 *   under 20s  → 2s    a quick action still reads as instant
 *   under 60s  → 5s
 *   after that → 15s
 *
 * The NEWEST, so a click made while an older action is still waiting gets the fast rate at
 * once. Its age comes from the job's own `created_at` (read as IST — see `parseIst`), so the
 * rate is right after a reload too. It never stops while anything is unfinished: a clock the
 * browser has wrong can only make polling faster or slower, never silent.
 */
export const POLL_SCHEDULE = [
	{ under: 20_000, every: 2_000 },
	{ under: 60_000, every: 5_000 },
	{ under: Infinity, every: 15_000 },
];

export const pollInterval = (items, now = Date.now()) => {
	const active = (items ?? []).filter(isActive);
	if (!active.length) return false;
	const newest = Math.max(
		...active.map((a) => parseIst(a.created_at) ?? now),
	);
	const age = Math.max(0, now - newest);
	return POLL_SCHEDULE.find((step) => age < step.under).every;
};

/**
 * The NEWEST page of person-triggered actions (newest first) — what a row's busy state, a
 * row's inline outcome and a count badge all read. `source` narrows it to one page's own
 * (One-time Ops lists only what was started from it); omitted, it is every action.
 *
 * Only the newest page: those three only ever care about what just happened, and it is this
 * query that POLLS, so it stays one small request however long the history grows. The full
 * history is `useActionHistory`.
 *
 * Polls while anything is unfinished — backing off the longer it waits (`pollInterval`) —
 * and stops once everything has settled, so an idle page makes no requests.
 *
 * When an action finishes, everything it could have changed is refreshed. "Finished" is
 * judged against the PREVIOUS CACHED LIST, not a ref held by a component: several components
 * read this one query, and a per-component memory meant every already-finished action counted
 * as new on first mount — refetching all campaign data on every page load for nothing.
 */
export const useRecentActions = ({ source } = {}) => {
	const { activeClientId, mp, ready } = useScope();
	const qc = useQueryClient();
	const key = [RECENT_ACTIONS, activeClientId, mp, source ?? "all"];
	return useQuery({
		queryKey: key,
		queryFn: async () => {
			// The RAW cached page, not the `select`ed list — `getQueryData` sees the cache.
			const before = qc.getQueryData(key);
			const page = (await getRecentActions(
				activeClientId,
				mp,
				source,
			)) ?? {
				items: [],
				has_more: false,
			};
			if (finishedSince(before?.items, page.items))
				invalidateAfterWrite(qc, activeClientId);
			return page;
		},
		select: (page) => page?.items ?? [],
		enabled: ready,
		refetchInterval: (query) => pollInterval(query.state.data?.items),
	});
};

/**
 * The WHOLE history of person-triggered actions, paged — the One-time Ops panel. No time
 * window and no cap: `jobs` rows are never deleted, so every operation ever made is here.
 *
 * `fetchNextPage` loads the next-older page. While the newest page has anything unfinished it
 * polls on the same back-off as `useRecentActions`; an infinite query refetches its pages in
 * order and re-derives each cursor from the fresh page before it, so a new action arriving at
 * the top can neither duplicate a row nor open a gap between pages.
 *
 * ⚠️ Pass `enabled: false` while the panel is CLOSED. Its component stays mounted — the modal
 * only hides its markup — so without this the history polled all the time, in parallel with
 * `useRecentActions` reading the very same newest page: two identical requests per tick.
 */
export const useActionHistory = ({ source, enabled = true } = {}) => {
	const { activeClientId, mp, ready } = useScope();
	return useInfiniteQuery({
		queryKey: [
			RECENT_ACTIONS,
			activeClientId,
			mp,
			source ?? "all",
			"history",
		],
		queryFn: ({ pageParam }) =>
			getRecentActions(activeClientId, mp, source, pageParam),
		initialPageParam: null,
		getNextPageParam: (last) =>
			last?.has_more && last.items.length
				? last.items[last.items.length - 1].created_at
				: undefined,
		enabled: ready && enabled,
		refetchInterval: (query) =>
			pollInterval(query.state.data?.pages?.[0]?.items),
	});
};

/**
 * Which in-flight action, if any, is acting on a given row.
 *
 * The match is deliberately narrow:
 *   - a KEYWORD action (a bid reset) carries its keyword, so it marks only that rule busy.
 *     Matching on the campaign alone would freeze every bid rule on a campaign because one
 *     of its keywords was being reset.
 *   - a CAMPAIGN action (budget, start/stop) marks only campaign-kind rows. A budget write
 *     does not touch a keyword's bid.
 *
 * A row with no `kind` is treated as a campaign row, which is what One-time Ops' rows are.
 */
export const useActiveActionFor = ({ source } = {}) => {
	const { data: actions } = useRecentActions({ source });
	const live = useMemo(() => (actions ?? []).filter(isActive), [actions]);
	return (row) => {
		if (!row?.campaign_id) return null;
		const kind = row.kind ?? "campaign";
		return (
			live.find((a) =>
				a.campaign_id !== row.campaign_id
					? false
					: a.keyword
						? kind === "keyword" && row.keyword === a.keyword
						: kind === "campaign",
			) ?? null
		);
	};
};

/**
 * The most recent action on a campaign — running or finished. What a row shows inline: a
 * spinner while its operation runs, then what that operation did.
 */
export const useLatestActionFor = ({ source } = {}) => {
	const { data: actions } = useRecentActions({ source });
	return (campaignId) =>
		campaignId == null
			? null
			: ((actions ?? []).find((a) => a.campaign_id === campaignId) ??
				null);
};

// ── Run outcomes ────────────────────────────────────────────────────────────

/**
 * Every row one run recorded — what it actually did. Read once its job has settled.
 *
 * `enabled` is the settled flag on purpose: before then the run has written nothing, and an
 * empty answer would be indistinguishable from "it decided to change nothing".
 *
 * Cached for good once fetched. Keyed on the RUN, so no other action can ever share the key,
 * and a finished run's rows never change — the runner marks a job finished only after the
 * process has exited, and the process writes its history before exiting. (The old lookup
 * keyed on the CAMPAIGN had to refetch every time, because the next action on that campaign
 * would otherwise have been answered from this one's cache.)
 */
export const useRunOutcome = (runId, enabled) => {
	const { activeClientId, mp, ready } = useScope();
	return useQuery({
		queryKey: ["run-outcome", activeClientId, mp, runId],
		queryFn: () => getRunOutcome(activeClientId, mp, runId),
		enabled: Boolean(ready && runId && enabled),
		select: (page) => page?.items ?? [],
		staleTime: Infinity,
	});
};

/**
 * What a run's rows mean, in words — for a one-line status (a campaign row, the wizard).
 *
 * The WORDS come from `lib/runLog.js` (`resultOf`), the vocabulary Execution logs and Recent
 * operations use, so an operation reads the same inline as it does in the table. That also
 * gives it "Test mode": a tenant not armed for live writes runs every operation dry, the run
 * still records `apply`, and this used to say "Applied · now ₹700" when nothing was applied.
 *
 * Returns `{ className, text, detail }` — `text` short enough for a table cell, `detail` the
 * full sentence for a tooltip — or `null` while the rows have not arrived, so a caller never
 * shows a guess.
 */
export const describeOutcome = (rows) => {
	if (!rows) return null;

	// An EMPTY run is a real answer: the engines deliberately record no row for a tick that
	// changed nothing, so this is the hourly poll finding everything already correct.
	if (rows.length === 0)
		return {
			className: "text-content-subtle",
			text: "Nothing needed changing",
			detail: null,
		};

	if (rows.length === 1) {
		const r = rows[0];
		const result = resultOf(r);
		// The new value only where the change genuinely LANDED — a test-mode row carries one
		// too, and quoting it there is the lie this function used to tell.
		const applied = result.label === "Applied" && r.new_value != null;
		return {
			className: result.tone,
			text: applied
				? `Applied · now ${formatCurrency(r.new_value)}`
				: result.label,
			detail:
				r.reason ||
				(result.label === "Not applied"
					? "The platform did not accept this change."
					: null),
		};
	}

	// A run across several campaigns or keywords. Summarised rather than one row picked, with
	// refusals and errors kept visible: rounding "3 changed, 2 refused" up to a success would
	// hide exactly the part that needs attention.
	const count = (label) =>
		rows.filter((r) => resultOf(r).label === label).length;
	const applied = count("Applied");
	const refused = count("Not applied");
	const errors = count("Error");
	const test = count("Test mode");
	const extra = [
		refused && `${refused} not applied`,
		errors && `${errors} error${errors > 1 ? "s" : ""}`,
		test && `${test} in test mode`,
	].filter(Boolean);
	return {
		className: errors
			? "text-danger"
			: refused
				? "text-warning"
				: test
					? "text-warning"
					: "text-success",
		text: [`${applied} of ${rows.length} changed`, ...extra].join(" · "),
		detail: rows
			.map((r) =>
				[r.campaign_name, r.keyword, r.reason]
					.filter(Boolean)
					.join(" · "),
			)
			.join("\n"),
	};
};
