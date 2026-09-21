import assert from "node:assert/strict";
import { test } from "node:test";
import { createBrowser } from "../utility/js/environment.mjs";

/** @matrix login : loading-state submit-button */
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
		"../../src/script/login/forms.mjs"
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

/** @matrix login : disabled-provider owner-bootstrap */
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
	const { OwnerSetupForm } = await import("../../src/script/login/forms.mjs");
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
