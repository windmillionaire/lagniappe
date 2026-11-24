import { request } from "./request.ts";

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

export const initializeLogoutForms = (root = document) => {
	if (initialized) return;
	initialized = true;

	root.addEventListener("click", async (event) => {
		const button = event.target?.closest?.(LOGOUT_BUTTON_SELECTOR);
		if (!button) return;

		event.preventDefault();
		await submitLogout(button.dataset.route, {
			submitter: button,
			state: button,
		});
	});
};
