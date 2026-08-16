/*! Third-party licenses: /third-party-licenses.txt */
import { r as request } from './foundation.js?v=ba53d151';
import './connectivity.js?v=ba53d151';

let userLocationUpdate = null;

/**
 * @testable true
 * @tests tests_js/test_020_shared_utilities.py::test_user_data_sync_posts_location_on_page_load_and_deduplicates
 * @tests tests_js/test_020_shared_utilities.py::test_user_data_sync_still_posts_timezone_when_location_is_unavailable
 * @pairs location:page-load location:session-update timezone:session-update
 */
function updateUserData() {
	return updateUserLocation();
}

/**
 * @testable false
 * @covered-by src/script/shared/user.mjs::updateUserLocation
 * @reason one request keeps concurrent location and timezone writes in the same session response
 */
async function _syncUserData() {
	const currentTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
	const sentThisSession = sessionStorage.getItem("timezone_sent");
	const userHash = sessionStorage.getItem("userHash");
	const timezoneChanged = sentThisSession !== currentTimezone || !userHash;
	const position = await _getCurrentPosition({
		enableHighAccuracy: false,
		maximumAge: 3600000, // up to 1 hour old
		timeout: 8000,
	});
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
	return { retry: false, synced: Boolean(location) };
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
 * @tests tests_js/test_020_shared_utilities.py::test_user_data_sync_posts_location_on_page_load_and_deduplicates
 * @tests tests_js/test_020_shared_utilities.py::test_user_location_sync_retries_failed_session_update
 * @tests tests_js/test_020_shared_utilities.py::test_user_data_sync_still_posts_timezone_when_location_is_unavailable
 * @pairs location:geolocation location:page-load location:session-update
 * @pairs location:deduplication location:retry location:unavailable
 */
function updateUserLocation() {
	if (userLocationUpdate) return userLocationUpdate;

	const update = _syncUserData().then(
		({ retry, synced }) => {
			if (retry && userLocationUpdate === update) userLocationUpdate = null;
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
