import { request } from "./request.ts";

const LOGOUT_BUTTON_SELECTOR = "[data-action='logout'][data-route]";

let initialized = false;

type LogoutOptions = {
	submitter?: HTMLElement | null;
	state?: HTMLElement | null;
};

const submitLogout = async (
	route: string,
	{ submitter = null, state = null }: LogoutOptions = {},
) => {
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

export const initializeLogoutForms = (
	root: Document | HTMLElement = document,
) => {
	if (initialized) return;
	initialized = true;

	root.addEventListener("click", async (event) => {
		const target = event.target as Element | null;
		const button = target?.closest?.<HTMLElement>(LOGOUT_BUTTON_SELECTOR);
		const route = button?.dataset.route;
		if (!button || route === undefined) return;

		event.preventDefault();
		await submitLogout(route, {
			submitter: button,
			state: button,
		});
	});
};
