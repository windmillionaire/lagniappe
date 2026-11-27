import assert from "node:assert/strict";
import { test } from "node:test";
import { createBrowser } from "../utility/js/environment.mjs";

test("test_login_action_button_uses_fixed_icon_and_text_slots", async (t) => {
	createBrowser(t, {
		html: `
			<button data-role="signin">
				<span data-role="icon" data-visible="false"></span>
				<span data-role="text">Continue</span>
			</button>
		`,
	});
	const { setLoginActionButton } = await import(
		"../../src/script/login/forms.ts"
	);
	const button = document.querySelector("[data-role='signin']");
	const iconSlot = button.querySelector("[data-role='icon']");
	const textSlot = button.querySelector("[data-role='text']");

	setLoginActionButton(button, "Checking Email", "spinner");
	assert.equal(
		button.children[0],
		iconSlot,
		"Login button replaced its fixed icon slot",
	);
	assert.equal(
		button.children[1],
		textSlot,
		"Login button replaced its fixed text slot",
	);
	assert.equal(iconSlot.dataset.visible, "true");
	assert.equal(
		iconSlot.firstElementChild?.dataset.icon,
		"spinner",
		"Login button did not render its spinner in the icon slot",
	);
	assert.equal(
		textSlot.textContent,
		"Checking Email",
		"Login button did not update its text slot",
	);

	setLoginActionButton(button, "Continue");
	assert.equal(
		iconSlot.dataset.visible,
		"false",
		"Login button did not hide its icon slot",
	);
	assert.equal(
		iconSlot.children.length,
		0,
		"Login button did not clear its icon slot",
	);
	assert.equal(
		textSlot.textContent,
		"Continue",
		"Login button did not restore its text slot",
	);

	const unstructuredButton = document.createElement("button");
	setLoginActionButton(unstructuredButton, "Sign In", "spinner");
	assert.equal(
		unstructuredButton.children[0]?.dataset.role,
		"icon",
		"Login helper did not create an icon slot",
	);
	assert.equal(
		unstructuredButton.children[1]?.dataset.role,
		"text",
		"Login helper did not create a text slot",
	);
});

test("test_owner_setup_supports_password_only_mode", async (t) => {
	createBrowser(t, {
		html: `
			<form data-role="owner-setup" class="hidden">
				<p data-role="error" class="hidden"></p>
				<p data-role="success" class="hidden"></p>
				<section data-role="owner-google-setup" class="hidden">
					<p data-role="error" class="hidden"></p>
				</section>
				<section data-role="owner-password-setup">
					<p data-role="error" class="hidden"></p>
					<input type="password">
				</section>
				<button data-role="signin" type="button">
					<span data-role="text">Create Password</span>
				</button>
			</form>
		`,
	});
	const { OwnerSetupForm } = await import("../../src/script/login/forms.ts");
	const form = document.querySelector("[data-role='owner-setup']");
	const passwordSetup = form.querySelector(
		"[data-role='owner-password-setup']",
	);
	const passwordError = passwordSetup.querySelector("[data-role='error']");
	const ownerSetup = new OwnerSetupForm({}, form);
	ownerSetup.data = {
		email: "owner@example.test",
		error: "Provider unavailable",
	};
	ownerSetup.show();

	assert.equal(
		ownerSetup.error,
		passwordError,
		"Password-only owner setup did not select its visible error slot",
	);
	assert.equal(
		passwordSetup.classList.contains("hidden"),
		false,
		"Password-only owner setup hid its available setup pane",
	);
	assert.equal(
		form.classList.contains("hidden"),
		false,
		"Password-only owner setup did not open",
	);
	assert.equal(
		passwordError.textContent,
		"Provider unavailable",
		"Password-only owner setup did not display its error safely",
	);
});

test("test_login_forms_focus_initial_input_after_unhiding", async (t) => {
	createBrowser(t, {
		html: `
			<div id="emailCheck" class="hidden">
				<div data-role="error" class="hidden"></div>
				<input type="email" />
				<button data-role="signin"><span data-role="text">Continue</span></button>
				<button data-role="back-to-method">Back</button>
			</div>
			<div id="signIn" class="hidden">
				<div data-role="error" class="hidden"></div>
				<div data-role="success" class="hidden"></div>
				<div data-role="selected-email"></div>
				<input type="hidden" name="email" />
				<div data-hide-on-confirmation>
					<input type="password" />
					<button data-role="signin"><span data-role="text">Sign In</span></button>
					<button data-role="show-forgot-form">Forgot?</button>
				</div>
				<button data-role="back-to-email">Use different email</button>
			</div>
			<div id="forgotPassword" class="hidden">
				<div data-role="error" class="hidden"></div>
				<div data-role="success" class="hidden"></div>
				<input type="email" />
				<button data-role="reset-password-email"><span data-role="text">Send Reset Email</span></button>
				<button data-role="back-to-signin">Back</button>
			</div>
		`,
	});
	const { EmailCheckForm, SignInForm, ForgotPasswordForm } = await import(
		"../../src/script/login/forms.ts"
	);

	const spyFocusOrder = (container, input) => {
		let hiddenWhenFocused = null;
		const origFocus = input.focus.bind(input);
		input.focus = (...args) => {
			hiddenWhenFocused = container.classList.contains("hidden");
			return origFocus(...args);
		};
		return () => hiddenWhenFocused;
	};

	const emailCheckElt = document.getElementById("emailCheck");
	const emailCheckInput = emailCheckElt.querySelector("input[type='email']");
	const getEmailCheckHidden = spyFocusOrder(emailCheckElt, emailCheckInput);
	const emailCheck = new EmailCheckForm({}, emailCheckElt);
	emailCheck.show();
	assert.equal(getEmailCheckHidden(), false);
	assert.equal(document.activeElement, emailCheckInput);

	const signInElt = document.getElementById("signIn");
	const signInInput = signInElt.querySelector("input[type='password']");
	const getSignInHidden = spyFocusOrder(signInElt, signInInput);
	const signIn = new SignInForm({}, signInElt);
	signIn.data = { email: "user@example.test" };
	signIn.show();
	assert.equal(getSignInHidden(), false);
	assert.equal(document.activeElement, signInInput);

	const forgotElt = document.getElementById("forgotPassword");
	const forgotInput = forgotElt.querySelector("input[type='email']");
	const getForgotHidden = spyFocusOrder(forgotElt, forgotInput);
	const forgot = new ForgotPasswordForm({}, forgotElt);
	forgot.data = { email: "" };
	forgot.show();
	assert.equal(getForgotHidden(), false);
	assert.equal(document.activeElement, forgotInput);
});
