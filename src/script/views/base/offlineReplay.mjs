/**
 * Replay persisted mutations outside the Core startup closure. The queue owns
 * mounted-form polling; the broad refresh covers collection consumers after
 * successful writes.
 *
 * @testable true
 * @tests tests_js/test_028_form_state_split.py::test_visibility_sync_stages_remote_form_edits_without_waiting_for_offline_replay
 * @features offline polling
 * @dimensions background-replay nonblocking
 * @pair offline:background-replay
 * @pair polling:nonblocking
 */
export const replayOfflineQueue = async (view, existingQueue = null) => {
	try {
		if (view._destroyed) return 0;
		const queue = existingQueue || (await view.ensureOfflineQueue());
		if (!queue || view._destroyed || !view.online) return 0;
		const replayed = (await queue.replay()) || 0;
		if (replayed && !view._destroyed) await view.refresh();
		return replayed;
	} catch (error) {
		view.reportStartupError(error, view.elt, "offline-replay");
		return 0;
	}
};
