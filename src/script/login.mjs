import {
	EmailCheckForm,
	FirstTimeSetupForm,
	ForgotPasswordForm,
	ResetPasswordForm,
	SignInForm,
	setLoginActionButton,
	VerifyEmailForm,
} from "./login/forms";
import { IdentityPlatformClient } from "./login/identity";
import { initializeLogoutForms } from "./shared/logout.mjs";
import { request } from "./shared/request.mjs";
import { withTransition } from "./shared/utilities.mjs";

initializeLogoutForms();

const REMEMBER_COOKIE_NAME = "lagniappe_remember";

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001b_login.py::test_agent_access_login_form_creates_session
 * @features login
 * @dimensions agent-access
 */
function initializeAgentLoginForms(root = document) {
	root.addEventListener("submit", async (event) => {
		const form = event.target;
		if (!(form instanceof HTMLFormElement)) return;
		const route = form.dataset.route || form.action;
		if (!route.endsWith("/users/agent-login")) return;

		event.preventDefault();
		if (form.dataset.submitting === "true") return;
		form.dataset.submitting = "true";

		const submitter = event.submitter;
		const submitText =
			submitter?.querySelector("[data-role='text']")?.textContent ||
			submitter?.textContent.trim();
		const error = form.querySelector("[data-role='error']");
		error?.classList.add("hidden");
		if (submitter && "disabled" in submitter) {
			submitter.disabled = true;
			setLoginActionButton(submitter, "Signing In", "spinner");
		}

		const response = await request.post(route, new FormData(form));
		if (response?.redirect) {
			window.location.href = response.redirect;
			return;
		}

		if (error) {
			error.textContent = response?.error || "Authentication failed.";
			error.classList.remove("hidden");
		}
		form.dataset.submitting = "false";
		if (submitter && "disabled" in submitter) {
			submitter.disabled = false;
			setLoginActionButton(submitter, submitText);
		}
	});
}

initializeAgentLoginForms();

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001b_login.py::test_login_page_loads
 * @features login
 * @dimensions page-load
 */
async function initializeIdentityPlatform() {
	try {
		const response = await fetch("/identity-config");
		const config = await response.json();
		return new IdentityPlatformClient(config);
	} catch (error) {
		console.error("Failed to initialize Identity Platform:", error);
		throw error;
	}
}

if (document.getElementById("emailCheck")) {
	const auth = await initializeIdentityPlatform();

	let allowRegistration = document.body.hasAttribute("allow-registration");
	const mode = document.body.getAttribute("data-mode");
	const code = document.body.getAttribute("data-code");

	const forms = {};

	/**
	 * @testable false
	 * @covered-by src/script/login.mjs::setRememberPreference
	 * @reason read helper is part of the remember-me preference sync contract
	 */
	const rememberPreference = () => {
		const cookie = document.cookie
			.split("; ")
			.find((entry) => entry.startsWith(`${REMEMBER_COOKIE_NAME}=`));
		if (!cookie) return true;
		return cookie.split("=")[1] !== "0";
	};

	/**
	 * @testable false
	 * @covered-by src/script/login.mjs::setRememberPreference
	 * @reason DOM propagation helper is part of the remember-me preference sync contract
	 */
	const syncRememberInputs = () => {
		const remember = rememberPreference();
		document.querySelectorAll("input[name='remember-me']").forEach((input) => {
			input.checked = remember;
		});
	};

	/**
	 * @testable true
	 * @tests tests_e2e/001_site/test_001b_login.py::test_login_remember_preference_syncs_across_forms
	 * @features login
	 * @dimensions remember-preference
	 */
	const setRememberPreference = (remember) => {
		const secure = window.location.protocol === "https:" ? "; Secure" : "";
		// biome-ignore lint/suspicious/noDocumentCookie: this stores a non-sensitive UI preference for Google redirect login.
		document.cookie = `${REMEMBER_COOKIE_NAME}=${remember ? "1" : "0"}; Path=/; Max-Age=31536000; SameSite=Lax${secure}`;
		syncRememberInputs();
	};

	/**
	 * @testable true
	 * @tests tests_e2e/001_site/test_001b_login.py::test_login_defaults_to_email_check_form
	 * @tests tests_e2e/001_site/test_001b_login.py::test_known_registered_email_shows_sign_in
	 * @tests tests_e2e/001_site/test_001b_login.py::test_reset_password_mode
	 * @tests tests_e2e/001_site/test_001b_login.py::test_verify_email_mode
	 * @features login
	 * @dimensions email-check sign-in-transition query-mode
	 */
	const showForm = (form) => {
		withTransition(() => {
			Object.values(forms).forEach((form) => {
				if (form) form.hide();
			});
			form.show();
			syncRememberInputs();
		});
	};

	if (mode === "resetPassword") {
		allowRegistration = false;
		const resetPasswordForm = document.getElementById("resetPassword");
		forms.resetPassword = new ResetPasswordForm(auth, resetPasswordForm);
		forms.resetPassword.data.code = code;
		showForm(forms.resetPassword);
	} else if (mode === "verifyEmail") {
		const verifyEmailForm = document.getElementById("verifyEmail");
		forms.verifyEmail = new VerifyEmailForm(auth, verifyEmailForm);
		forms.verifyEmail.data.code = code;
		showForm(forms.verifyEmail);
	} else if (allowRegistration) {
		const signInForm = document.getElementById("signIn");
		forms.signIn = new SignInForm(auth, signInForm);
		showForm(forms.signIn);
	} else {
		const emailCheckForm = document.getElementById("emailCheck");
		forms.emailCheck = new EmailCheckForm(auth, emailCheckForm);
		showForm(forms.emailCheck);
	}

	document.addEventListener("login:show-signin", (event) => {
		if (!forms.signIn) {
			const formElt = document.getElementById("signIn");
			forms.signIn = new SignInForm(auth, formElt);
		}
		forms.signIn.data = { ...event.detail };
		showForm(forms.signIn);
	});

	document.addEventListener("login:show-email-check", () => {
		if (!forms.emailCheck) {
			const formElt = document.getElementById("emailCheck");
			forms.emailCheck = new EmailCheckForm(auth, formElt);
		}
		showForm(forms.emailCheck);
	});

	document.addEventListener("login:show-first-time-setup", (event) => {
		if (!forms.firstTimeSetup) {
			const formElt = document.getElementById("firstTimeSetup");
			forms.firstTimeSetup = new FirstTimeSetupForm(auth, formElt);
		}
		const form = forms.firstTimeSetup;
		form.data = { ...event.detail };
		showForm(form);
	});

	document.addEventListener("login:show-forgot-form", (event) => {
		if (!forms.forgotPassword) {
			const formElt = document.getElementById("forgotPassword");
			forms.forgotPassword = new ForgotPasswordForm(auth, formElt);
		}
		const form = forms.forgotPassword;
		form.data = { ...event.detail };
		showForm(form);
	});

	document.addEventListener("change", (event) => {
		if (event.target.matches("input[name='remember-me']")) {
			setRememberPreference(event.target.checked);
		}
	});
}
