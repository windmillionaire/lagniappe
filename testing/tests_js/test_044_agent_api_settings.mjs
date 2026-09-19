import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";

function replaceGlobal(t, name, value) {
	const descriptor = Object.getOwnPropertyDescriptor(globalThis, name);
	Object.defineProperty(globalThis, name, {
		configurable: true,
		writable: true,
		value,
	});
	t.after(() => {
		if (descriptor) Object.defineProperty(globalThis, name, descriptor);
		else delete globalThis[name];
	});
}

async function loadUserSettings({
	FormWidget,
	Modal = class {},
	captureError = () => {},
	request = {},
}) {
	return await esmock.strict("../../src/script/widgets/userSettings.mjs", {
		"../../src/script/elements/input.mjs": { InputElement: class {} },
		"../../src/script/elements/radio.mjs": { RadioElement: class {} },
		"../../src/script/elements/sectionToggle.mjs": { SectionToggle: {} },
		"../../src/script/shared/index.mjs": {
			captureError,
			Modal,
			request,
		},
		"../../src/script/widgets/base/formWidget.mjs": { FormWidget },
	});
}

// @matrix agent-api : expiry poll-reconcile revoke rotate shown-once status
// @matrix user-settings : poll-reconcile status
test("test_agent_api_key_controls_keep_secret_ephemeral", async (t) => {
	let stored = false;
	replaceGlobal(t, "localStorage", {
		getItem() {
			stored = true;
			throw new Error("API key read from storage");
		},
		setItem() {
			stored = true;
			throw new Error("API key written to storage");
		},
	});
	class FormWidget {
		constructor() {
			this.destroyables = [];
		}
		async _initForm() {}
		postreconcile() {
			if (!this._updated) return;
			this._updated = false;
			this.commitReset();
			this.target.dataset.visible = "true";
		}
	}
	const request = {
		async post() {
			return {
				ok: true,
				token: "lgn_identifier.secret",
				credential: {
					active: true,
					display_prefix: "lgn_ident…",
					expires_at: "2026-09-30T12:00:00+00:00",
				},
			};
		},
		async delete() {
			return { ok: true, credential: { active: false } };
		},
	};
	const { UserSettings } = await loadUserSettings({ FormWidget, request });
	const elements = {
		status: { textContent: "" },
		issue: { disabled: false, textContent: "Generate API key" },
		revoke: { dataset: {}, disabled: false },
		secret: { dataset: {} },
		value: { textContent: "" },
		message: { dataset: {}, textContent: "" },
	};
	const selectors = new Map([
		["[data-role='api-key-status']", elements.status],
		["[data-action='issue-api-key']", elements.issue],
		["[data-action='revoke-api-key']", elements.revoke],
		["[data-role='api-key-secret']", elements.secret],
		["[data-role='api-key-value']", elements.value],
		["[data-role='api-key-message']", elements.message],
	]);
	const section = {
		querySelector(selector) {
			return selectors.get(selector) || null;
		},
	};
	const widget = Object.create(UserSettings.prototype);
	const confirmations = [];
	widget._confirmApiKeyAction = async (_section, _trigger, options) => {
		confirmations.push(options);
		return true;
	};

	await widget._issueApiKey(section, "/users/me/api-key");
	assert.equal(elements.value.textContent, "lgn_identifier.secret");
	assert.equal(elements.secret.dataset.visible, "true");
	assert.equal(elements.issue.textContent, "Regenerate API key");
	assert.equal(elements.issue.disabled, false);

	await widget._issueApiKey(section, "/users/me/api-key");
	assert.equal(confirmations.length, 1);
	assert.equal(confirmations[0].title, "Regenerate API key");
	assert.equal(confirmations[0].label, "Regenerate API key");

	widget._renderApiKey(section, {
		active: true,
		display_prefix: "lgn_ident…",
		expires_at: "2026-09-30T12:00:00+00:00",
	});
	assert.equal(elements.value.textContent, "");
	assert.equal(elements.secret.dataset.visible, "false");

	await widget._revokeApiKey(section, "/users/me/api-key");
	assert.equal(confirmations.length, 2);
	assert.equal(confirmations[1].title, "Revoke API key");
	assert.equal(confirmations[1].label, "Revoke API key");
	assert.equal(elements.revoke.dataset.visible, "false");
	assert.equal(elements.issue.textContent, "Generate API key");
	assert.equal(elements.revoke.disabled, false);
	assert.equal(stored, false);

	const preview = Object.create(UserSettings.prototype);
	preview.revisionPreview = true;
	preview.target = {
		querySelector() {
			throw new Error("Revision preview initialized API key controls");
		},
	};
	preview._initApiKey();

	const initialized = [];
	widget._updated = true;
	widget.target = { dataset: {} };
	widget.commitReset = () => initialized.push("commit");
	widget._initGroups = () => initialized.push("groups");
	widget._initPageSelect = () => initialized.push("page-select");
	widget._initRemovePage = () => initialized.push("remove-page");
	widget._initApiKey = () => initialized.push("api-key");
	widget.setEntityMetadata = () => initialized.push("metadata");
	await widget._initForm({ replace: false });
	widget.postreconcile();
	assert.deepEqual(initialized, [
		"groups",
		"page-select",
		"remove-page",
		"api-key",
		"commit",
		"metadata",
	]);
	assert.equal(widget._updated, false);
	assert.equal(widget.target.dataset.visible, "true");
});

// @matrix agent-api user-settings : confirmation-modal
test("test_agent_api_key_confirmation_uses_app_modal", async () => {
	const modalInstances = [];
	class Modal {
		constructor(view, trigger) {
			this.view = view;
			this.trigger = trigger;
			this.removed = false;
			modalInstances.push(this);
		}
		async attach(element) {
			this.element = element;
			return element;
		}
		async remove() {
			this.removed = true;
		}
	}
	class FormWidget {}
	let capturedError = null;
	const { UserSettings } = await loadUserSettings({
		FormWidget,
		Modal,
		captureError(error) {
			capturedError = error;
		},
	});

	let fixture = null;
	function newFixture() {
		const title = { textContent: "" };
		const description = { textContent: "" };
		const label = { textContent: "" };
		let click = null;
		const confirm = {
			disabled: false,
			focused: false,
			querySelector(selector) {
				return selector === "[data-role='text']" ? label : null;
			},
			addEventListener(type, callback) {
				if (type === "click") click = callback;
			},
			focus() {
				this.focused = true;
			},
			async activate() {
				return await click();
			},
		};
		const modalElement = {
			querySelector(selector) {
				if (selector === "[data-role='confirmation-title']") return title;
				if (selector === "[data-role='confirmation-description']")
					return description;
				if (selector === "[data-role='confirmation-confirm']") return confirm;
				return null;
			},
		};
		return { confirm, description, label, modalElement, title };
	}
	const template = {
		content: {
			querySelector(selector) {
				if (selector !== "#modal") return null;
				return {
					cloneNode() {
						fixture = newFixture();
						return fixture.modalElement;
					},
				};
			},
		},
	};
	const section = {
		querySelector(selector) {
			return selector === "template[data-role='api-key-confirmation-template']"
				? template
				: null;
		},
	};
	const trigger = {};
	const widget = Object.create(UserSettings.prototype);
	widget.view = { dataset: { kind: "user" } };

	const confirmed = widget._confirmApiKeyAction(section, trigger, {
		title: "Regenerate API key",
		description: "The old key will stop working.",
		label: "Regenerate API key",
	});
	await new Promise((resolve) => setImmediate(resolve));
	assert.equal(capturedError, null);
	assert.equal(modalInstances.length, 1);
	assert.equal(fixture.title.textContent, "Regenerate API key");
	assert.equal(
		fixture.description.textContent,
		"The old key will stop working.",
	);
	assert.equal(fixture.label.textContent, "Regenerate API key");
	assert.equal(fixture.confirm.focused, true);
	await fixture.confirm.activate();
	assert.equal(await confirmed, true);
	assert.equal(modalInstances[0].removed, true);

	const cancelled = widget._confirmApiKeyAction(section, trigger, {
		title: "Revoke API key",
		description: "The key will stop working.",
		label: "Revoke API key",
	});
	await new Promise((resolve) => setImmediate(resolve));
	await modalInstances[1].remove();
	assert.equal(await cancelled, false);
	assert.equal(modalInstances[1].removed, true);
});
