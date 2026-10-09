import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import {
	getPlatforms,
	saveCredentials,
	startLogin,
	disconnect,
	getJob,
	getAccountUsers,
	createAccountUser,
	setUserRole,
	setUserActive,
	setUserClients,
	deleteAccountUser,
	resetUserPassword,
	changeOwnPassword,
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

// ── Account users ───────────────────────────────────────────────────────────

const USERS = "account-users";

export const useAccountUsers = () =>
	useQuery({ queryKey: [USERS], queryFn: getAccountUsers });

/** One invalidator for every write — they all change the same table. */
const useUsersInvalidate = () => {
	const qc = useQueryClient();
	return () => qc.invalidateQueries({ queryKey: [USERS] });
};

export const useCreateAccountUser = () => {
	const invalidate = useUsersInvalidate();
	return useMutation({ mutationFn: createAccountUser, onSuccess: invalidate });
};

export const useSetUserRole = () => {
	const invalidate = useUsersInvalidate();
	return useMutation({
		mutationFn: ({ userId, role }) => setUserRole(userId, role),
		onSuccess: invalidate,
	});
};

export const useSetUserActive = () => {
	const invalidate = useUsersInvalidate();
	return useMutation({
		mutationFn: ({ userId, isActive }) => setUserActive(userId, isActive),
		onSuccess: invalidate,
	});
};

export const useSetUserClients = () => {
	const invalidate = useUsersInvalidate();
	return useMutation({
		mutationFn: ({ userId, clientIds }) => setUserClients(userId, clientIds),
		onSuccess: invalidate,
	});
};

export const useDeleteAccountUser = () => {
	const invalidate = useUsersInvalidate();
	return useMutation({
		mutationFn: ({ userId }) => deleteAccountUser(userId),
		onSuccess: invalidate,
	});
};

export const useResetUserPassword = () =>
	useMutation({
		mutationFn: ({ userId, newPassword }) =>
			resetUserPassword(userId, newPassword),
	});

export const useChangeOwnPassword = () =>
	useMutation({
		mutationFn: ({ currentPassword, newPassword }) =>
			changeOwnPassword(currentPassword, newPassword),
	});
