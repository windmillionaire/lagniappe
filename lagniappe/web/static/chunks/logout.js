/*! Third-party licenses: /third-party-licenses.txt */
import { r as request } from './request.js?v=b19dd33c';
import './errors.js?v=b19dd33c';

const LOGOUT_BUTTON_SELECTOR = "[data-action='logout'][data-route]";

let initialized = false;

/**
 * @testable false
 * @covered-by src/script/shared/logout.mjs::initializeLogoutForms
 * @reason private logout request helper is exercised through logout controls
 */
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

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001b_login.py::test_logout_clears_session_and_returns_login
 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_user_settings_panel_opens_from_my_page
 * @tests tests_js/test_009_request_csrf.py::test_logout_button_posts_without_hidden_form
 * @features login
 * @dimensions logout redirect button
 */
const initializeLogoutForms = (root = document) => {
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

export { initializeLogoutForms };
