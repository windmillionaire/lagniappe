/*! Third-party licenses: /third-party-licenses.txt */
import { r as request } from './request.js?v=b01d709d';
import './errors.js?v=b01d709d';

/**
 * @testable false
 * @reason session timezone heartbeat has no focused frontend assertion yet
 */
async function updateUserData() {
	const currentTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
	const sentThisSession = sessionStorage.getItem("timezone_sent");
	const userHash = sessionStorage.getItem("userHash");

	if (sentThisSession === currentTimezone && userHash) return;

	sessionStorage.setItem("timezone_sent", currentTimezone);
	const response = await request.post(
		"/update-session",
		{ timezone: currentTimezone },
		{ keepalive: true },
	);
	if (response?.ok) {
		if (response.userHash)
			sessionStorage.setItem("userHash", response.userHash);
	} else {
		sessionStorage.removeItem("timezone_sent");
	}
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
 * @testable false
 * @covered-by src/script/shared/user.mjs::updateUserLocation
 * @reason session location POST is owned by the exported location updater
 */
async function _updateUserLocation(newLocation) {
	localStorage.setItem("location", JSON.stringify(newLocation));
	await request.post(
		"/update-session",
		{ location: newLocation },
		{ keepalive: true },
	);
}

/**
 * @testable false
 * @covered-by src/script/shared/user.mjs::updateUserLocation
 * @reason distance threshold is private location-update plumbing
 */
function _approxDistanceKm(a, b) {
	// Equirectangular approximation; good enough for metro-area checks
	/**
	 * @testable false
	 * @covered-by src/script/shared/user.mjs::_approxDistanceKm
	 * @reason radians conversion is private distance math
	 */
	const toRad = (deg) => (deg * Math.PI) / 180;
	const R = 6371;
	const phi1 = toRad(a.latitude);
	const phi2 = toRad(b.latitude);
	const dPhi = toRad(b.latitude - a.latitude);
	const dLambda = toRad(b.longitude - a.longitude);
	const x = dLambda * Math.cos((phi1 + phi2) / 2);
	const y = dPhi;
	return Math.sqrt(x * x + y * y) * R;
}

/**
 * @testable true
 * @tests tests_js/test_020_shared_utilities.py::test_user_location_updates_only_for_initial_or_distant_positions
 * @pairs location:geolocation location:distance-threshold location:session-update
 */
async function updateUserLocation() {
	const METRO_RADIUS_KM = 50; // rough same-metro threshold

	const cachedLocation = localStorage.getItem("location");
	const oldLocation = cachedLocation ? JSON.parse(cachedLocation) : null;

	const position = await _getCurrentPosition({
		enableHighAccuracy: false,
		maximumAge: 3600000, // up to 1 hour old
		timeout: 8000,
	});
	if (!position) return;

	const newLocation = {
		latitude: position.coords.latitude,
		longitude: position.coords.longitude,
	};

	if (!oldLocation) {
		await _updateUserLocation(newLocation);
		return;
	}

	const distance = _approxDistanceKm(oldLocation, newLocation);

	if (distance > METRO_RADIUS_KM) {
		await _updateUserLocation(newLocation);
	}
}

export { updateUserData, updateUserLocation };
