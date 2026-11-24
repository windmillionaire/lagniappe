import { createIcon } from "../shared/icons.ts";
import { captureLoginError } from "./error.ts";
import {
	checkUserStatus,
	getAuthErrorMessage,
	handleIdentityUser,
} from "./tools.ts";

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

const recoverExistingAccount = (error, email) => {
	if (error.code !== "auth/email-already-in-use") return false;
	document.dispatchEvent(
		new CustomEvent("login:show-signin", {
			detail: { email, action: "existing-account" },
		}),
	);
	return true;
};

class LoginForms {
	constructor(auth, form) {
		this.auth = auth;
		this.form = form;
		this.data = {};
		this.initialized = false;
		this.actionButton = null;
		this.error = this.form.querySelector("[data-role='error']");
		this.success = this.form.querySelector("[data-role='success']");
		this.hideOnConfirmation = this.form.querySelectorAll(
			"[data-hide-on-confirmation]",
		);
	}

	show() {
		if (!this.initialized) {
			this.init();
			this.initialized = true;
		}
		this.reset();
		this.sync();
		this.form.classList.remove("hidden");
	}

	sync() {}

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

	showConfirmation(message) {
		this.showSuccess(message);
		this.form.querySelectorAll("input[type='password']").forEach((input) => {
			input.value = "";
		});
		this.hideOnConfirmation.forEach((element) => {
			element.classList.add("hidden");
		});
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
		this.hideOnConfirmation.forEach((element) => {
			element.classList.remove("hidden");
		});
	}
}

class AuthMethodForm extends LoginForms {
	init() {
		this.emailButton = this.form.querySelector(
			"[data-role='show-email-check']",
		);
		this.emailButton.addEventListener("click", () => {
			document.dispatchEvent(new CustomEvent("login:show-email-check"));
		});
	}

	sync() {
		if (this.data.error) this.showError(this.data.error);
	}
}

class EmailCheckForm extends LoginForms {
	init() {
		this.error = this.form.querySelector("[data-role='error']");
		this.email = this.form.querySelector("input[type='email']");
		this.backButton = this.form.querySelector("[data-role='back-to-method']");
		this.setActionButton(this.form.querySelector("[data-role='signin']"));

		this.email.focus();

		this.actionButton.addEventListener("click", this.handleSignIn.bind(this));
		this.backButton.addEventListener("click", () => {
			document.dispatchEvent(new CustomEvent("login:show-auth-method"));
		});
	}

	sync() {
		this.email.focus();
	}

	handleSignIn() {
		const email = this.email.value.trim();
		if (!email || !this.email.validity.valid) {
			this.showError("Please enter a valid email address");
			return;
		}
		this.setActionState("Checking Email");

		checkUserStatus(email, this);
	}
}

class OwnerSetupForm extends LoginForms {
	init() {
		this.googleSetup = this.form.querySelector(
			"[data-role='owner-google-setup']",
		);
		this.passwordSetup = this.form.querySelector(
			"[data-role='owner-password-setup']",
		);
		this.googleError = this.googleSetup.querySelector("[data-role='error']");
		this.passwordError = this.passwordSetup.querySelector(
			"[data-role='error']",
		);
		this.verificationSuccessMessage =
			"We've sent a verification link to the application owner email on file.";
		this.password = this.passwordSetup.querySelector("input[type='password']");
		this.showPasswordButton = this.form.querySelector(
			"[data-role='show-owner-password']",
		);
		this.backToGoogleButton = this.form.querySelector(
			"[data-role='back-to-owner-google']",
		);

		this.setActionButton(this.form.querySelector("[data-role='signin']"));
		if (!this.showPasswordButton) this.error = this.passwordError;
		this.showPasswordButton?.addEventListener("click", () => {
			this.reset();
			this.error = this.passwordError;
			this.googleSetup.classList.add("hidden");
			this.passwordSetup.classList.remove("hidden");
			this.password.focus();
		});
		this.backToGoogleButton?.addEventListener("click", () => {
			this.password.value = "";
			this.reset();
			this.error = this.googleError;
			this.passwordSetup.classList.add("hidden");
			this.googleSetup.classList.remove("hidden");
		});
		this.actionButton.addEventListener("click", this.handleSignIn.bind(this));
	}

	handleSignIn() {
		const email = String(this.data.email || "").trim();
		const password = this.password.value.trim();
		if (!email) {
			this.showError("The application owner is not configured.");
			return;
		}
		if (!password) {
			this.showError("Please choose a password");
			return;
		}

		this.setActionState("Creating Password");
		this.auth
			.signUp(email, password)
			.then((user) => {
				handleIdentityUser(user, this);
			})
			.catch((error) => {
				if (recoverExistingAccount(error, email)) return;
				this.showError(getAuthErrorMessage(error));
			});
	}

	sync() {
		if (this.data.error) this.showError(this.data.error);
	}
}

class FirstTimeSetupForm extends LoginForms {
	init() {
		this.email = this.form.querySelector("input[name='email']");
		this.selectedEmail = this.form.querySelector(
			"[data-role='selected-email']",
		);
		this.password = this.form.querySelector("input[type='password']");
		this.backButton = this.form.querySelector("[data-role='back-to-email']");

		this.setActionButton(this.form.querySelector("[data-role='signin']"));
		this.actionButton.addEventListener("click", this.handleSignIn.bind(this));
		this.backButton.addEventListener("click", () => {
			document.dispatchEvent(new CustomEvent("login:show-email-check"));
		});
	}

	sync() {
		this.email.value = this.data.email || "";
		this.selectedEmail.textContent = this.data.email || "";
		this.password.value = "";
		setTimeout(() => this.password.focus(), 100);
	}

	handleSignIn() {
		const password = this.password.value.trim();
		if (!password) {
			this.showError("Please choose a password");
			return;
		}
		this.setActionState("Setting Password");
		this.auth
			.signUp(this.email.value, password)
			.then((user) => {
				handleIdentityUser(user, this);
			})
			.catch((error) => {
				if (recoverExistingAccount(error, this.email.value)) return;
				this.showError(getAuthErrorMessage(error));
			});
	}
}

class SignInForm extends LoginForms {
	init() {
		this.email = this.form.querySelector("input[name='email']");
		this.selectedEmail = this.form.querySelector(
			"[data-role='selected-email']",
		);
		this.password = this.form.querySelector("input[type='password']");
		this.rememberMe = this.form.querySelector("input[type='checkbox']");
		this.signinButton = this.form.querySelector("[data-role='signin']");
		this.backButton = this.form.querySelector("[data-role='back-to-email']");
		this.setActionButton(this.signinButton);
		this.signinButton?.addEventListener("click", this.handleSignIn.bind(this));

		this.forgotPasswordButton = this.form.querySelector(
			"[data-role='show-forgot-form']",
		);
		this.forgotPasswordButton.addEventListener("click", () => {
			const email = this.email.value.trim();
			document.dispatchEvent(
				new CustomEvent("login:show-forgot-form", { detail: { email } }),
			);
		});
		this.backButton.addEventListener("click", () => {
			document.dispatchEvent(new CustomEvent("login:show-email-check"));
		});
	}

	sync() {
		this.email.value = this.data.email || "";
		this.selectedEmail.textContent = this.data.email || "";
		this.password.value = "";
		if (this.data.action === "reset-password") {
			this.showSuccess(
				"Password updated successfully. Please sign in with your new password.",
			);
		} else if (this.data.action === "existing-account") {
			this.showSuccess("Your password is already set. Sign in to continue.");
		} else if (this.data.action === "verification-delivery-failed") {
			this.showError(
				"We couldn't send the verification email. Sign in again to retry delivery.",
			);
		}
		this.password.focus();
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
	}

	sync() {
		this.email.value = this.data.email || "";
		if (!this.data.email) this.email.focus();
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
				this.showConfirmation(
					"A password reset link has been sent to your email address.",
				);
			})
			.catch((_error) => {
				this.showError(
					"We couldn't send the password reset email. Please try again later.",
				);
			});
	}
}

class ResetPasswordForm extends LoginForms {
	init() {
		this.linkValidated = false;
		this.password = this.form.querySelector("input[type='password']");
		this.controls = this.form.querySelector(
			"[data-role='reset-password-controls']",
		);
		this.resetPasswordButton = this.form.querySelector(
			"[data-role='reset-password']",
		);
		this.requestNewLinkButton = this.form.querySelector(
			"[data-role='request-new-reset-link']",
		);
		this.resetPasswordButton.disabled = true;
		this.setActionButton(this.resetPasswordButton);
		this.actionButton.addEventListener(
			"click",
			this.handleResetPassword.bind(this),
		);
		this.requestNewLinkButton.addEventListener("click", () => {
			document.dispatchEvent(
				new CustomEvent("login:show-forgot-form", {
					detail: { email: this.email || "" },
				}),
			);
		});
		this.auth
			.verifyPasswordResetCode(this.data.code)
			.then((result) => {
				this.email = result.email || "";
				this.linkValidated = true;
				this.resetPasswordButton.disabled = false;
				setLoginActionButton(this.actionButton, this.oldActionText);
				this.password.focus();
			})
			.catch((error) => {
				this.linkValidated = true;
				this.showError(getAuthErrorMessage(error));
				this.controls.classList.add("hidden");
			});
	}

	sync() {
		if (!this.linkValidated) this.setActionState("Checking Link");
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
			.then((result) => {
				document.dispatchEvent(
					new CustomEvent("login:show-signin", {
						detail: { action: "reset-password", email: result.email },
					}),
				);
			})
			.catch((error) => {
				this.showError(getAuthErrorMessage(error));
			});
	}
}

class VerifyEmailForm extends LoginForms {
	init() {
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
				this.signinButton.disabled = false;
				this.setActionButton(this.signinButton);
				this.actionButton.addEventListener(
					"click",
					this.handleSignIn.bind(this),
				);
				this.showSuccess("Email verified successfully");
			})
			.catch((error) => {
				captureLoginError(error, "verify_email");
				this.showError(getAuthErrorMessage(error));
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
				this.showError(getAuthErrorMessage(error));
			});
	}
}

export {
	AuthMethodForm,
	EmailCheckForm,
	FirstTimeSetupForm,
	ForgotPasswordForm,
	OwnerSetupForm,
	ResetPasswordForm,
	SignInForm,
	setLoginActionButton,
	VerifyEmailForm,
};
