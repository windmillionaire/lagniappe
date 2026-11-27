import { createIcon } from "../shared/icons.ts";
import { captureLoginError } from "./error.ts";
import type { IdentityPlatformClient } from "./identity.ts";
import {
	authErrorCode,
	checkUserStatus,
	getAuthErrorMessage,
	handleIdentityUser,
} from "./tools.ts";

interface LoginFormData {
	email?: string | null;
	error?: string | null;
	code?: string | null;
	action?:
		| "reset-password"
		| "existing-account"
		| "verification-delivery-failed";
}

declare global {
	interface DocumentEventMap {
		"login:show-signin": CustomEvent<LoginFormData>;
		"login:show-first-time-setup": CustomEvent<LoginFormData>;
		"login:show-forgot-form": CustomEvent<LoginFormData>;
	}
}

function requiredControl<T extends HTMLElement = HTMLElement>(
	root: ParentNode,
	selector: string,
): T {
	const control = root.querySelector<T>(selector);
	if (!control) throw new Error(`Missing login control: ${selector}`);
	return control;
}

const setLoginActionButton = (
	button: HTMLElement | null,
	text: string | null | undefined,
	icon: string | null = null,
) => {
	if (!button) return;

	let textElement = button.querySelector<HTMLElement>("[data-role='text']");
	if (!textElement) {
		textElement = document.createElement("span");
		textElement.dataset.role = "text";
		button.replaceChildren(textElement);
	}
	textElement.textContent = text ?? null;

	let iconWrapper = button.querySelector<HTMLElement>("[data-role='icon']");
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

const recoverExistingAccount = (error: unknown, email: string) => {
	if (authErrorCode(error) !== "auth/email-already-in-use") return false;
	document.dispatchEvent(
		new CustomEvent("login:show-signin", {
			detail: { email, action: "existing-account" },
		}),
	);
	return true;
};

abstract class LoginForms {
	declare auth: IdentityPlatformClient;
	declare form: HTMLElement;
	declare data: LoginFormData;
	declare initialized: boolean;
	declare actionButton: HTMLElement | null;
	declare oldActionText: string | null | undefined;
	declare error: Element | null;
	declare success: Element | null;
	declare hideOnConfirmation: NodeListOf<Element>;
	declare email?: HTMLInputElement | string;
	declare password?: HTMLInputElement;
	declare verificationSuccessMessage?: string;

	constructor(auth: IdentityPlatformClient, form: HTMLElement) {
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

	abstract init(): void;

	show() {
		if (!this.initialized) {
			this.init();
			this.initialized = true;
		}
		this.reset();
		this.sync();
		this.form.classList.remove("hidden");
		this.focusInitial();
	}

	sync() {}

	focusInitial() {}

	hide() {
		this.form.classList.add("hidden");
		this.reset();
	}

	setActionButton(button: HTMLElement | null) {
		this.reset();
		this.actionButton = button;
		this.oldActionText =
			this.actionButton?.querySelector("[data-role='text']")?.textContent ||
			this.actionButton?.textContent.trim();
	}

	remember() {
		return this.form.querySelector<HTMLInputElement>(
			"input[name='remember-me']",
		)?.checked;
	}

	getEmailAndPassword() {
		if (this.email && typeof this.email !== "string" && this.password) {
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

	showSuccess(message: string) {
		this.reset();
		if (!this.success) return;
		this.success.textContent = message;
		this.success.classList.remove("hidden");
	}

	showConfirmation(message: string) {
		this.showSuccess(message);
		this.form
			.querySelectorAll<HTMLInputElement>("input[type='password']")
			.forEach((input) => {
				input.value = "";
			});
		this.hideOnConfirmation.forEach((element) => {
			element.classList.add("hidden");
		});
	}

	showError(message: string) {
		this.reset();
		if (!this.error) return;
		this.error.textContent = message;
		this.error.classList.remove("hidden");
	}

	getToken() {
		return document.querySelector<HTMLInputElement>("#token")?.value;
	}

	setActionState(text: string) {
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
	declare emailButton: HTMLElement;

	init() {
		this.emailButton = requiredControl(
			this.form,
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
	declare email: HTMLInputElement;
	declare backButton: HTMLElement;

	init() {
		this.error = this.form.querySelector("[data-role='error']");
		this.email = requiredControl<HTMLInputElement>(
			this.form,
			"input[type='email']",
		);
		this.backButton = requiredControl(
			this.form,
			"[data-role='back-to-method']",
		);
		this.setActionButton(requiredControl(this.form, "[data-role='signin']"));

		this.actionButton?.addEventListener("click", this.handleSignIn.bind(this));
		this.backButton.addEventListener("click", () => {
			document.dispatchEvent(new CustomEvent("login:show-auth-method"));
		});
	}

	focusInitial() {
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
	declare googleSetup: HTMLElement;
	declare passwordSetup: HTMLElement;
	declare googleError: Element | null;
	declare passwordError: Element | null;
	declare password: HTMLInputElement;
	declare showPasswordButton: Element | null;
	declare backToGoogleButton: Element | null;

	init() {
		this.googleSetup = requiredControl(
			this.form,
			"[data-role='owner-google-setup']",
		);
		this.passwordSetup = requiredControl(
			this.form,
			"[data-role='owner-password-setup']",
		);
		this.googleError = this.googleSetup.querySelector("[data-role='error']");
		this.passwordError = this.passwordSetup.querySelector(
			"[data-role='error']",
		);
		this.verificationSuccessMessage =
			"We've sent a verification link to the application owner email on file.";
		this.password = requiredControl<HTMLInputElement>(
			this.passwordSetup,
			"input[type='password']",
		);
		this.showPasswordButton = this.form.querySelector(
			"[data-role='show-owner-password']",
		);
		this.backToGoogleButton = this.form.querySelector(
			"[data-role='back-to-owner-google']",
		);

		this.setActionButton(requiredControl(this.form, "[data-role='signin']"));
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
		this.actionButton?.addEventListener("click", this.handleSignIn.bind(this));
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
	declare email: HTMLInputElement;
	declare selectedEmail: HTMLElement;
	declare password: HTMLInputElement;
	declare backButton: HTMLElement;

	init() {
		this.email = requiredControl<HTMLInputElement>(
			this.form,
			"input[name='email']",
		);
		this.selectedEmail = requiredControl(
			this.form,
			"[data-role='selected-email']",
		);
		this.password = requiredControl<HTMLInputElement>(
			this.form,
			"input[type='password']",
		);
		this.backButton = requiredControl(this.form, "[data-role='back-to-email']");

		this.setActionButton(requiredControl(this.form, "[data-role='signin']"));
		this.actionButton?.addEventListener("click", this.handleSignIn.bind(this));
		this.backButton.addEventListener("click", () => {
			document.dispatchEvent(new CustomEvent("login:show-email-check"));
		});
	}

	sync() {
		this.email.value = this.data.email || "";
		this.selectedEmail.textContent = this.data.email || "";
		this.password.value = "";
	}

	focusInitial() {
		this.password.focus();
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
	declare email: HTMLInputElement;
	declare selectedEmail: HTMLElement;
	declare password: HTMLInputElement;
	declare rememberMe: HTMLInputElement | null;
	declare signinButton: HTMLElement | null;
	declare backButton: HTMLElement;
	declare forgotPasswordButton: HTMLElement;

	init() {
		this.email = requiredControl<HTMLInputElement>(
			this.form,
			"input[name='email']",
		);
		this.selectedEmail = requiredControl(
			this.form,
			"[data-role='selected-email']",
		);
		this.password = requiredControl<HTMLInputElement>(
			this.form,
			"input[type='password']",
		);
		this.rememberMe = this.form.querySelector<HTMLInputElement>(
			"input[type='checkbox']",
		);
		this.signinButton = this.form.querySelector<HTMLElement>(
			"[data-role='signin']",
		);
		this.backButton = requiredControl(this.form, "[data-role='back-to-email']");
		this.setActionButton(this.signinButton);
		this.signinButton?.addEventListener("click", this.handleSignIn.bind(this));

		this.forgotPasswordButton = requiredControl(
			this.form,
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
	}

	focusInitial() {
		this.password.focus();
	}

	handleSignIn() {
		this.setActionState("Signing In");
		const credentials = this.getEmailAndPassword();
		if (!credentials) return;
		const { email, password } = credentials;

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
	declare email: HTMLInputElement;
	declare resetPasswordButton: HTMLElement;
	declare backToSigninButton: HTMLElement;

	init() {
		this.email = requiredControl<HTMLInputElement>(
			this.form,
			"input[type='email']",
		);
		this.resetPasswordButton = requiredControl(
			this.form,
			"[data-role='reset-password-email']",
		);
		this.backToSigninButton = requiredControl(
			this.form,
			"[data-role='back-to-signin']",
		);

		this.setActionButton(this.resetPasswordButton);
		this.actionButton?.addEventListener(
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
	}

	focusInitial() {
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
	declare linkValidated: boolean;
	declare password: HTMLInputElement;
	declare controls: HTMLElement;
	declare resetPasswordButton: HTMLButtonElement;
	declare requestNewLinkButton: HTMLElement;
	declare email: string | undefined;

	init() {
		this.linkValidated = false;
		this.password = requiredControl<HTMLInputElement>(
			this.form,
			"input[type='password']",
		);
		this.controls = requiredControl(
			this.form,
			"[data-role='reset-password-controls']",
		);
		this.resetPasswordButton = requiredControl<HTMLButtonElement>(
			this.form,
			"[data-role='reset-password']",
		);
		this.requestNewLinkButton = requiredControl(
			this.form,
			"[data-role='request-new-reset-link']",
		);
		this.resetPasswordButton.disabled = true;
		this.setActionButton(this.resetPasswordButton);
		this.actionButton?.addEventListener(
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
	declare password: HTMLInputElement;
	declare signinButton: HTMLButtonElement;
	declare email: HTMLInputElement;
	declare forgotPasswordButton: HTMLElement;

	init() {
		this.password = requiredControl<HTMLInputElement>(
			this.form,
			"input[type='password']",
		);
		this.signinButton = requiredControl<HTMLButtonElement>(
			this.form,
			"[data-role='signin']",
		);
		this.signinButton.disabled = true;
		this.email = requiredControl<HTMLInputElement>(
			this.form,
			"input[type='email']",
		);
		this.email.value = localStorage.getItem("verificationEmail") ?? "";
		localStorage.removeItem("verificationEmail");

		this.forgotPasswordButton = requiredControl(
			this.form,
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
				this.actionButton?.addEventListener(
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
		const credentials = this.getEmailAndPassword();
		if (!credentials) return;
		const { email, password } = credentials;

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
	type LoginForms,
	OwnerSetupForm,
	ResetPasswordForm,
	SignInForm,
	setLoginActionButton,
	VerifyEmailForm,
};
