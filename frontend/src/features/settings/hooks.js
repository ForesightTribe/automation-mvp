import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import {
	getPlatforms,
	saveCredentials,
	startLogin,
	disconnect,
	getJob,
} from "./api";

const PLATFORMS = "connections-platforms";

/**
 * The client's marketplace connections.
 *
 * `watch` re-reads them every few seconds. A sign-in finishes on the server with
 * nothing to announce it, so while one is running the screen asks again until the
 * session shows up, rather than waiting for someone to reload the page.
 */
export const usePlatforms = ({ watch = false } = {}) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: [PLATFORMS, activeClientId],
		queryFn: () => getPlatforms(activeClientId),
		enabled: Boolean(activeClientId),
		refetchInterval: watch ? 4000 : false,
	});
};

const useInvalidate = () => {
	const { activeClientId } = useClient();
	const qc = useQueryClient();
	return () =>
		qc.invalidateQueries({ queryKey: [PLATFORMS, activeClientId] });
};

export const useSaveCredentials = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate();
	return useMutation({
		mutationFn: ({ platform, ...body }) =>
			saveCredentials(activeClientId, platform, body),
		onSuccess: invalidate,
	});
};

export const useStartLogin = () => {
	const { activeClientId } = useClient();
	return useMutation({
		mutationFn: (platform) => startLogin(activeClientId, platform),
	});
};

export const useDisconnect = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate();
	return useMutation({
		mutationFn: (platform) => disconnect(activeClientId, platform),
		onSuccess: invalidate,
	});
};

/**
 * Poll a login until it settles, then re-read the platforms. A finished job is not a
 * connected platform: it can exit cleanly having never found the mail.
 */
export const useLoginJob = (jobId) => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate();
	return useQuery({
		queryKey: ["connections-job", activeClientId, jobId],
		queryFn: async () => {
			const job = await getJob(activeClientId, jobId);
			if (job.status === "success" || job.status === "failed")
				invalidate();
			return job;
		},
		enabled: Boolean(activeClientId && jobId),
		// The only job route today serves `cm.*` jobs; `auth.login` 404s here
		// (docs/onboarding.md). One attempt — a failure means "result unknown".
		retry: false,
		refetchInterval: (q) => {
			const s = q.state.data?.status;
			return s === "success" || s === "failed" ? false : 2000;
		},
	});
};
