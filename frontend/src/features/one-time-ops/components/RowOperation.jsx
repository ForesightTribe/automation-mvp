import { useEffect, useState } from "react";
import { isActive } from "../../../lib/actions";
import { parseIst } from "../../../lib/format";
import { OperationStatus } from "./OperationStatus";

/**
 * How long a FINISHED operation's outcome stays on its campaign row. The full record is in
 * the Recent operations panel, with no time limit; the row only needs to answer "did the
 * thing I just did work", and an outcome that lingered all day would read as current.
 */
export const INLINE_OUTCOME_MINUTES = 5;

/**
 * True once `untilMs` has passed — re-rendering exactly then, not on a polling tick.
 *
 * The recent-actions query stops polling as soon as nothing is running, so nothing else
 * would ever re-render the row when the five minutes are up; the outcome would sit there
 * until some unrelated update. One timeout per visible outcome, cleared on unmount.
 */
const usePassed = (untilMs) => {
	const [, rerender] = useState(0);
	useEffect(() => {
		if (untilMs == null) return undefined;
		const left = untilMs - Date.now();
		if (left <= 0) return undefined;
		const t = setTimeout(() => rerender((n) => n + 1), left + 50);
		return () => clearTimeout(t);
	}, [untilMs]);
	return untilMs != null && Date.now() >= untilMs;
};

/**
 * A campaign row's own operation: a spinner for as long as it runs — however long that is,
 * since a job can wait minutes behind another in the queue — then its outcome for
 * `INLINE_OUTCOME_MINUTES` after it FINISHED, then nothing.
 *
 * The window runs from the job's finish time, not from when it was asked for, and that time
 * is read as IST (`parseIst`): the server sends naive IST values, and reading one as the
 * browser's own local time would put the window hours out on any machine not set to IST.
 */
export const RowOperation = ({ action }) => {
	const finished = Boolean(action) && !isActive(action);
	const finishedAt = finished
		? parseIst(action.completed_at ?? action.created_at)
		: null;
	const until =
		finishedAt == null
			? null
			: finishedAt + INLINE_OUTCOME_MINUTES * 60 * 1000;
	const expired = usePassed(until);

	if (!action) return null;
	if (finished && (until == null || expired)) return null;
	return <OperationStatus action={action} compact />;
};
