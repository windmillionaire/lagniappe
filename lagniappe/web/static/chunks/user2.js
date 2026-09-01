/*! Third-party licenses: /third-party-licenses.txt */
import { r as request } from './foundation.js?v=b8995073';
import './upstreamUnavailable.js?v=b8995073';
import './connectivity.js?v=b8995073';

let userDataUpdate = null;
let userLocationUpdate = null;

/**
 * @testable true
 * @tests tests_js/test_020_shared_utilities.py::test_user_data_sync_posts_timezone_without_requesting_location
 * @tests tests_js/test_020_shared_utilities.py::test_unavailable_user_location_does_not_affect_timezone_sync
 * @matrix timezone : page-load session-update
 * @pair location:permission-deferral
 */
function updateUserData() {
	if (userDataUpdate) return userDataUpdate;

	const update = _syncUserData().then(
		({ retry, synced }) => {
			if (retry && userDataUpdate === update) userDataUpdate = null;
			return synced;
		},
		(error) => {
			if (userDataUpdate === update) userDataUpdate = null;
			throw error;
		},
	);
	userDataUpdate = update;
	return update;
}

/**
 * @testable false
 * @covered-by src/script/shared/user.mjs::updateUserData
 * @covered-by src/script/shared/user.mjs::updateUserLocation
 * @reason shared payload construction keeps serialized timezone and optional location updates consistent
 */
async function _syncUserData({ includeLocation = false } = {}) {
	const currentTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
	const sentThisSession = sessionStorage.getItem("timezone_sent");
	const userHash = sessionStorage.getItem("userHash");
	const timezoneChanged = sentThisSession !== currentTimezone || !userHash;
	const position = includeLocation
		? await _getCurrentPosition({
				enableHighAccuracy: false,
				maximumAge: 3600000, // up to 1 hour old
				timeout: 8000,
			})
		: null;
	const location = position
		? {
				latitude: position.coords.latitude,
				longitude: position.coords.longitude,
			}
		: null;
	const payload = {};
	if (timezoneChanged) payload.timezone = currentTimezone;
	if (location) payload.location = location;
	if (Object.keys(payload).length === 0) {
		return { retry: false, synced: false };
	}

	const response = await request.post("/l/update-session", payload, {
		keepalive: true,
	});
	if (!response?.ok) return { retry: true, synced: false };

	if (timezoneChanged) {
		sessionStorage.setItem("timezone_sent", currentTimezone);
	}
	if (response.userHash) sessionStorage.setItem("userHash", response.userHash);
	return {
		retry: false,
		synced: includeLocation ? Boolean(location) : timezoneChanged,
	};
}

/**
 * @testable false
 * @covered-by src/script/shared/user.mjs::updateUserLocation
 * @reason geolocation lookup is private location-update plumbing
 */
function _getCurrentPosition(options) {
	return new Promise((resolve) => {
		if (!("geolocation" in navigator)) {
			resolve(null);
			return;
		}
		navigator.geolocation.getCurrentPosition(
			(pos) => resolve(pos),
			() => resolve(null),
			options,
		);
	});
}

/**
 * @testable true
 * @tests tests_js/test_020_shared_utilities.py::test_user_location_sync_starts_on_demand_and_deduplicates
 * @tests tests_js/test_020_shared_utilities.py::test_user_location_sync_retries_failed_session_update
 * @tests tests_js/test_020_shared_utilities.py::test_unavailable_user_location_does_not_affect_timezone_sync
 * @matrix location : deduplication geolocation on-demand retry session-update unavailable
 * @pair timezone:serialized-update
 */
function updateUserLocation() {
	if (userLocationUpdate) return userLocationUpdate;

	const update = updateUserData()
		.then(() => _syncUserData({ includeLocation: true }))
		.then(
			({ retry, synced }) => {
				if (retry && userLocationUpdate === update) {
					userLocationUpdate = null;
				}
				return synced;
			},
			(error) => {
				if (userLocationUpdate === update) userLocationUpdate = null;
				throw error;
			},
		);
	userLocationUpdate = update;
	return update;
}

export { updateUserData, updateUserLocation };
