/*! Third-party licenses: /third-party-licenses.txt */
import { r as request } from './foundation.js?v=b8c49d0d';

const LOGOUT_BUTTON_SELECTOR = "[data-action='logout'][data-route]";
let initialized = false;
const submitLogout = async (route, { submitter = null, state = null } = {}) => {
  state = state || submitter;
  if (state?.dataset?.submitting === "true") return;
  if (state?.dataset) state.dataset.submitting = "true";
  if (submitter && "disabled" in submitter) {
    submitter.disabled = true;
  }
  const response = await request.post(route);
  if (response?.redirect) {
    window.location.href = response.redirect;
  } else if (response?.ok) {
    window.location.href = "/users/login";
  } else {
    if (state?.dataset) state.dataset.submitting = "false";
    if (submitter && "disabled" in submitter) {
      submitter.disabled = false;
    }
  }
};
const initializeLogoutForms = (root = document) => {
  if (initialized) return;
  initialized = true;
  root.addEventListener("click", async (event) => {
    const target = event.target;
    const button = target?.closest?.(LOGOUT_BUTTON_SELECTOR);
    const route = button?.dataset.route;
    if (!button || route === void 0) return;
    event.preventDefault();
    await submitLogout(route, {
      submitter: button,
      state: button
    });
  });
};

var logout = /*#__PURE__*/Object.freeze({
	__proto__: null,
	initializeLogoutForms: initializeLogoutForms
});

let userDataUpdate = null;
let userLocationUpdate = null;
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
    }
  );
  userDataUpdate = update;
  return update;
}
async function _syncUserData({ includeLocation = false } = {}) {
  const currentTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const sentThisSession = sessionStorage.getItem("timezone_sent");
  const userHash = sessionStorage.getItem("userHash");
  const timezoneChanged = sentThisSession !== currentTimezone || !userHash;
  const position = includeLocation ? await _getCurrentPosition({
    enableHighAccuracy: false,
    maximumAge: 36e5,
    // up to 1 hour old
    timeout: 8e3
  }) : null;
  const location = position ? {
    latitude: position.coords.latitude,
    longitude: position.coords.longitude
  } : null;
  const payload = {};
  if (timezoneChanged) payload.timezone = currentTimezone;
  if (location) payload.location = location;
  if (Object.keys(payload).length === 0) {
    return { retry: false, synced: false };
  }
  const response = await request.post(
    "/l/update-session",
    payload,
    { keepalive: true }
  );
  if (!response?.ok) return { retry: true, synced: false };
  if (timezoneChanged) {
    sessionStorage.setItem("timezone_sent", currentTimezone);
  }
  if (response.userHash) sessionStorage.setItem("userHash", response.userHash);
  return {
    retry: false,
    synced: includeLocation ? Boolean(location) : timezoneChanged
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
      options
    );
  });
}
function updateUserLocation() {
  if (userLocationUpdate) return userLocationUpdate;
  const update = updateUserData().then(() => _syncUserData({ includeLocation: true })).then(
    ({ retry, synced }) => {
      if (retry && userLocationUpdate === update) {
        userLocationUpdate = null;
      }
      return synced;
    },
    (error) => {
      if (userLocationUpdate === update) userLocationUpdate = null;
      throw error;
    }
  );
  userLocationUpdate = update;
  return update;
}

var user = /*#__PURE__*/Object.freeze({
	__proto__: null,
	updateUserData: updateUserData,
	updateUserLocation: updateUserLocation
});

export { user as a, logout as l, updateUserLocation as u };
