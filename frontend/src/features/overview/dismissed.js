import { useCallback, useEffect, useState } from "react";

/**
 * Insights the reader has put aside.
 *
 * ⚠️ Dismissing hides a card; it resolves nothing and writes nothing back.
 * `localStorage` is this browser only — not this user, not this account.
 *
 * A dismissal lapses at the end of the day it was made, and is keyed on the
 * headline as well as the id. So a card comes back the next morning, and comes
 * back sooner if its counts move — the list is today's work, not a permanent
 * mute.
 */
const KEY = "overview.dismissed.v2";

/** Today's date plus the headline: either changing brings the card back. */
const stamp = (insight) =>
	`${new Date().toLocaleDateString("en-CA")}|${insight.title}`;

const read = () => {
	try {
		return JSON.parse(localStorage.getItem(KEY) ?? "{}") ?? {};
	} catch {
		// Private windows, cleared site data, blocked storage: an empty set is
		// the safe answer, since it shows too much rather than too little.
		return {};
	}
};

const write = (map) => {
	try {
		localStorage.setItem(KEY, JSON.stringify(map));
	} catch {
		// Nothing to do: the list simply does not persist this session.
	}
};

export const useDismissed = () => {
	const [map, setMap] = useState(read);

	// Another tab putting something aside should not leave this one out of step.
	useEffect(() => {
		const onStorage = (e) => e.key === KEY && setMap(read());
		window.addEventListener("storage", onStorage);
		return () => window.removeEventListener("storage", onStorage);
	}, []);

	const dismiss = useCallback((insight) => {
		setMap((prev) => {
			const next = { ...prev, [insight.id]: stamp(insight) };
			write(next);
			return next;
		});
	}, []);

	const dismissAll = useCallback((insights) => {
		setMap((prev) => {
			const next = { ...prev };
			for (const i of insights) next[i.id] = stamp(i);
			write(next);
			return next;
		});
	}, []);

	const restoreAll = useCallback(() => {
		setMap({});
		write({});
	}, []);

	const isDismissed = useCallback(
		(insight) => map[insight.id] === stamp(insight),
		[map],
	);

	return { isDismissed, dismiss, dismissAll, restoreAll };
};
