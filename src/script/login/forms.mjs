import { createIcon } from "../shared/icons";
import { captureLoginError } from "./error";
import {
	checkUserStatus,
	getAuthErrorMessage,
	handleIdentityUser,
} from "./tools";

/**
 * @testable true
 * @tests tests_js/test_034_login_buttons.py::test_login_action_button_uses_fixed_icon_and_text_slots
 * @features login
 * @dimensions submit-button loading-state
 */
const setLoginActionButton = (button, text, icon = null) => {
	if (!button) return;

	let textElement = button.querySelector("[data-role='text']");
	if (!textElement) {
		textElement = document.createElement("span");
		textElement.dataset.role = "text";
		button.replaceChildren(textElement);
	}
	textElement.textContent = text;

	let iconWrapper = button.querySelector("[data-role='icon']");
	if (!iconWrapper) {
		iconWrapper = document.createElement("span");
		iconWrapper.dataset.role = "icon";
		iconWrapper.setAttribute("aria-hidden", "true");
		button.prepend(iconWrapper);
	}
	if (icon) {
		iconWrapper.replaceChildren(createIcon(icon));
		iconWrapper.dataset.visible = "true";
	} else {
		iconWrapper.replaceChildren();
		iconWrapper.dataset.visible = "false";
	}
};

/**
 * @testable false
 * @reason base form shell; concrete login forms own the tested workflows
 */
class LoginForms {
	constructor(auth, form) {
		this.auth = auth;
		this.form = form;
		this.data = {};
		this.initialized = false;
		this.actionButton = null;
		this.error = this.form.querySelector("[data-role='error']");
		this.success = this.form.querySelector("[data-role='success']");
	}

	show() {
		if (!this.initialized) {
			this.init();
			this.initialized = true;
		}
		this.reset();
		this.form.classList.remove("hidden");
	}

	hide() {
		this.form.classList.add("hidden");
		this.reset();
	}

	setActionButton(button) {
		this.reset();
		this.actionButton = button;
		this.oldActionText =
			this.actionButton?.querySelector("[data-role='text']")?.textContent ||
			this.actionButton?.textContent.trim();
	}

	remember() {
		return this.form.querySelector("input[name='remember-me']")?.checked;
	}

	getEmailAndPassword() {
		if (this.email) {
			const email = this.email.value.trim();
			const password = this.password.value.trim();
			if (!email || !password) {
				this.showError("Please enter your email and password");
				return;
			}
			return { email, password };
		}
		return null;
	}

	showSuccess(message) {
		this.reset();
		this.success.textContent = message;
		this.success.classList.remove("hidden");
	}

	showError(message) {
		this.reset();
		this.error.textContent = message;
		this.error.classList.remove("hidden");
	}

	getToken() {
		return document.getElementById("token")?.value;
	}

	setActionState(text) {
		setLoginActionButton(this.actionButton, text, "spinner");
	}

	reset() {
		setLoginActionButton(this.actionButton, this.oldActionText);
		if (this.success) {
			this.success.textContent = "";
			this.success.classList.add("hidden");
		}
		if (this.error) {
			this.error.textContent = "";
			this.error.classList.add("hidden");
		}
	}
}

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001b_login.py::test_login_defaults_to_email_check_form
 * @tests tests_e2e/001_site/test_001b_login.py::test_unknown_email_transitions_to_sign_in_without_leaking_existence
 * @tests tests_e2e/001_site/test_001b_login.py::test_known_registered_email_shows_sign_in
 * @tests tests_e2e/001_site/test_001b_login.py::test_login_responsive_design
 * @features login
 * @dimensions email-check sign-in-transition account-enumeration responsive-layout
 */
class EmailCheckForm extends LoginForms {
	init() {
		this.error = this.form.querySelector("[data-role='error']");
		this.email = this.form.querySelector("input[type='email']");
		this.setActionButton(this.form.querySelector("[data-role='signin']"));

		this.email.focus();

		this.actionButton.addEventListener("click", this.handleSignIn.bind(this));
	}

	/**
	 * @testable true
	 * @tests tests_e2e/001_site/test_001b_login.py::test_unknown_email_transitions_to_sign_in_without_leaking_existence
	 * @tests tests_e2e/001_site/test_001b_login.py::test_known_registered_email_shows_sign_in
	 * @tests tests_e2e/001_site/test_001b_login.py::test_email_input_validation
	 * @features login
	 * @dimensions email-check sign-in-transition account-enumeration email-validation
	 */
	handleSignIn() {
		const email = this.email.value.trim();
		if (!email) {
			this.showError("Please enter your email address");
			return;
		}
		this.setActionState("Checking Email");

		checkUserStatus(email, this);
	}
}

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001b_login.py::test_first_time_setup_form_creates_password_and_can_return_to_email_check
 * @features login
 * @dimensions first-time-setup account-create form-state
 */
class FirstTimeSetupForm extends LoginForms {
	init(name, email) {
		this.name = name;
		this.email = email;

		this.welcomeMessage = this.form.querySelector("[data-role='welcome']");
		this.password = this.form.querySelector("input[type='password']");
		this.googleSigninSetup = this.form.querySelector("#google-signin-setup");
		this.backButton = this.form.querySelector("[data-role='back-to-email']");

		this.welcomeMessage.textContent = this.data.name
			? `Welcome, ${this.data.name}!`
			: "Welcome!";
		this.setActionButton(this.form.querySelector("[data-role='signin']"));
		this.actionButton.addEventListener("click", this.handleSignIn.bind(this));
		this.backButton.addEventListener("click", () => {
			document.dispatchEvent(new CustomEvent("login:show-email-check"));
		});

		setTimeout(() => this.password.focus(), 100);
	}

	handleSignIn() {
		this.setActionState("Setting Password");
		this.auth
			.signUp(this.data.email, this.password.value)
			.then((user) => {
				handleIdentityUser(user, this);
			})
			.catch((error) => {
				this.showError(getAuthErrorMessage(error));
			});
	}
}

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001b_login.py::test_known_registered_email_shows_sign_in
 * @tests tests_e2e/001_site/test_001b_login.py::test_forgot_password_form_opens_from_sign_in
 * @features login
 * @dimensions sign-in-transition forgot-password
 */
class SignInForm extends LoginForms {
	init() {
		this.email = this.form.querySelector("input[type='email']");
		this.password = this.form.querySelector("input[type='password']");
		this.rememberMe = this.form.querySelector("input[type='checkbox']");
		this.signinButton = this.form.querySelector("[data-role='signin']");
		this.createButton = this.form.querySelector("[data-role='create']");
		this.googleSigninCustom = this.form.querySelector("#google-signin-custom");
		this.setActionButton(this.signinButton);
		this.signinButton?.addEventListener("click", this.handleSignIn.bind(this));

		if (this.data.email) {
			this.email.value = this.data.email;
			this.password.focus();
		}

		this.forgotPasswordButton = this.form.querySelector(
			"[data-role='show-forgot-form']",
		);
		this.forgotPasswordButton.addEventListener("click", () => {
			const email = this.email.value.trim();
			document.dispatchEvent(
				new CustomEvent("login:show-forgot-form", { detail: { email } }),
			);
		});

		if (this.data.action === "reset-password") {
			this.showSuccess(
				"Password updated successfully. Please sign in with your new password.",
			);
			this.googleSigninCustom.classList.add("hidden");
			return;
		}

		this.addSwitchListener(this.signinButton, this.createButton);

		this.createButton?.addEventListener("click", this.handleCreate.bind(this));
	}

	addSwitchListener(signinButton, createButton) {
		const modeLinks = this.form.querySelector(
			"[data-role='signin-mode-links']",
		);
		const message = this.form.querySelector("[data-role='message']");
		const switchToCreate = this.form.querySelector(
			"[data-role='switch-to-create']",
		);
		const switchToSignin = this.form.querySelector(
			"[data-role='switch-to-signin']",
		);
		const forgotPassword = this.form.querySelector(
			"[data-role='show-forgot-form']",
		);
		if (!switchToCreate || !switchToSignin) return;

		modeLinks.addEventListener("click", (event) => {
			const target = event.target.closest("button");
			if (target.dataset.role === "switch-to-create") {
				switchToCreate.closest("div").classList.add("hidden");
				switchToSignin.closest("div").classList.remove("hidden");
				createButton.classList.remove("hidden");
				signinButton.classList.add("hidden");
				forgotPassword.classList.add("hidden");
				message.textContent = "Create an account";
				this.setActionButton(createButton);
			} else if (target.dataset.role === "switch-to-signin") {
				switchToCreate.closest("div").classList.remove("hidden");
				switchToSignin.closest("div").classList.add("hidden");
				createButton.classList.add("hidden");
				signinButton.classList.remove("hidden");
				forgotPassword.classList.remove("hidden");
				message.textContent = "Sign in to your account";
				this.setActionButton(signinButton);
			}
		});
	}

	handleSignIn() {
		this.setActionState("Signing In");
		const { email, password } = this.getEmailAndPassword();
		if (!email || !password) return;

		this.auth
			.signInWithPassword(email, password)
			.then((user) => {
				handleIdentityUser(user, this);
			})
			.catch((error) => {
				if (error.code === "auth/invalid-credential") {
					this.showError(
						"We couldn't log you in. If you previously signed in with Google, please either sign in with Google or reset your password.",
					);
				} else {
					this.showError(getAuthErrorMessage(error));
				}
			});
	}

	handleCreate() {
		this.setActionState("Creating Account");
		const { email, password } = this.getEmailAndPassword();
		if (!email || !password) return;

		this.auth
			.signUp(email, password)
			.then((user) => {
				handleIdentityUser(user, this);
			})
			.catch((error) => {
				this.showError(getAuthErrorMessage(error));
			});
	}
}

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001b_login.py::test_forgot_password_form_opens_from_sign_in
 * @features login
 * @dimensions forgot-password
 */
class ForgotPasswordForm extends LoginForms {
	init() {
		this.email = this.form.querySelector("input[type='email']");
		this.resetPasswordButton = this.form.querySelector(
			"[data-role='reset-password-email']",
		);
		this.backToSigninButton = this.form.querySelector(
			"[data-role='back-to-signin']",
		);

		this.setActionButton(this.resetPasswordButton);
		this.actionButton.addEventListener(
			"click",
			this.handleResetPassword.bind(this),
		);

		this.backToSigninButton.addEventListener("click", () => {
			document.dispatchEvent(
				new CustomEvent("login:show-signin", {
					detail: { email: this.data.email },
				}),
			);
		});

		if (this.data.email) {
			this.email.value = this.data.email;
		} else {
			this.email.focus();
		}
	}

	handleResetPassword() {
		const email = this.email.value.trim();
		if (!email) {
			this.showError("Please enter your email address");
			return;
		}
		this.setActionState("Sending Reset Email");
		this.auth
			.sendPasswordResetEmail(email, this.getToken())
			.then(() => {
				this.showSuccess(
					"A password reset link has been sent to your email address.",
				);
			})
			.catch((error) => {
				captureLoginError(error, "reset_password");
				this.showError(getAuthErrorMessage(error));
			});
	}
}

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001b_login.py::test_reset_password_mode
 * @features login
 * @dimensions reset-password query-mode
 */
class ResetPasswordForm extends LoginForms {
	init() {
		this.password = this.form.querySelector("input[type='password']");
		this.resetPasswordButton = this.form.querySelector(
			"[data-role='reset-password']",
		);
		this.setActionButton(this.resetPasswordButton);
		this.actionButton.addEventListener(
			"click",
			this.handleResetPassword.bind(this),
		);
	}

	handleResetPassword() {
		const password = this.password.value.trim();
		if (!password) {
			this.showError("Please enter a new password");
			return;
		}
		this.setActionState("Updating Password");
		this.auth
			.confirmPasswordReset(this.data.code, password)
			.then(() => {
				document.dispatchEvent(
					new CustomEvent("login:show-signin", {
						detail: { action: "reset-password", email: this.data.email },
					}),
				);
			})
			.catch((error) => {
				this.showError(getAuthErrorMessage(error));
			});
	}
}

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001b_login.py::test_verify_email_mode
 * @features login
 * @dimensions verify-email query-mode
 */
class VerifyEmailForm extends LoginForms {
	init() {
		let verified = false;
		this.password = this.form.querySelector("input[type='password']");
		this.signinButton = this.form.querySelector("[data-role='signin']");
		this.signinButton.disabled = true;
		this.email = this.form.querySelector("input[type='email']");
		this.email.value = localStorage.getItem("verificationEmail");
		localStorage.removeItem("verificationEmail");

		this.forgotPasswordButton = this.form.querySelector(
			"[data-role='show-forgot-form']",
		);
		this.forgotPasswordButton.addEventListener("click", () => {
			const email = this.email.value.trim();
			document.dispatchEvent(
				new CustomEvent("login:show-forgot-form", { detail: { email } }),
			);
		});

		this.auth
			.applyActionCode(this.data.code)
			.then(() => {
				verified = true;
				this.signinButton.disabled = false;
				this.setActionButton(this.signinButton);
				this.actionButton.addEventListener(
					"click",
					this.handleSignIn.bind(this),
				);
			})
			.catch((error) => {
				captureLoginError(error, "verify_email");
				this.showError(getAuthErrorMessage(error));
			});

		if (verified) {
			this.showSuccess("Email verified successfully");
		}
	}

	handleSignIn() {
		this.setActionState("Signing In");
		const { email, password } = this.getEmailAndPassword();
		if (!email || !password) return;

		this.auth
			.signInWithPassword(email, password)
			.then((user) => {
				handleIdentityUser(user, this);
			})
			.catch((error) => {
				this.showError(getAuthErrorMessage(error));
			});
	}
}

export {
	EmailCheckForm,
	FirstTimeSetupForm,
	ForgotPasswordForm,
	ResetPasswordForm,
	SignInForm,
	setLoginActionButton,
	VerifyEmailForm,
};
