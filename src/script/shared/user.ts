import { request } from "./request.ts";

let userDataUpdate = null;
let userLocationUpdate = null;

export function updateUserData() {
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

export function updateUserLocation() {
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
