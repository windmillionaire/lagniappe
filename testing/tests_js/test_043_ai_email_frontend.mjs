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

test("test_ai_email_address_selection_and_copy_controls", async (t) => {
	const appended = [];
	const timers = [];
	let clipboardText = null;
	let fallbackCopies = 0;
	const navigatorBoundary = {
		clipboard: {
			async writeText(value) {
				clipboardText = value;
			},
		},
	};
	replaceGlobal(t, "navigator", navigatorBoundary);
	replaceGlobal(t, "document", {
		body: { append: (node) => appended.push(node) },
		createElement: () => ({
			value: "",
			style: {},
			setAttribute() {},
			select() {},
			remove() {},
		}),
		execCommand(command) {
			if (command === "copy") fallbackCopies += 1;
			return true;
		},
	});
	replaceGlobal(t, "setTimeout", (callback) => {
		timers.push(callback);
		return timers.length;
	});
	replaceGlobal(t, "clearTimeout", () => {});
	const { CreateToolReport } = await esmock.strict(
		"../../src/script/widgets/tools.mjs",
		{
			"../../src/script/elements/base/baseUpload.mjs": {
				BaseUpload: class {},
			},
			"../../src/script/elements/upload.mjs": {
				UploadMenu: class {},
				uploadElement: {},
			},
		},
	);
	const widget = Object.create(CreateToolReport.prototype);
	widget.emailSubmissions = {
		dataset: {
			addressAi: "ai@inbound.example.com",
			addressAsk: "ask@inbound.example.com",
			addressCreate: "create@inbound.example.com",
		},
	};
	widget.emailAddress = { textContent: "ai@inbound.example.com" };
	widget.emailCopyButton = {
		textContent: "Copy",
		isConnected: true,
		focus() {},
	};
	await widget.copyEmailAddress();
	assert.equal(clipboardText, "ai@inbound.example.com");
	assert.equal(widget.emailCopyButton.textContent, "Copied");
	timers.shift()();
	assert.equal(widget.emailCopyButton.textContent, "Copy");
	navigatorBoundary.clipboard.writeText = async () => {
		throw new Error("denied");
	};
	await widget.copyEmailAddress();
	assert.equal(fallbackCopies, 1);
	assert.equal(appended.length, 1);
	assert.equal(widget.emailCopyButton.textContent, "Copied");
	const absent = Object.create(CreateToolReport.prototype);
	absent.emailSubmissions = null;
	absent.emailAddress = null;
	absent.emailCopyButton = null;
	await absent.copyEmailAddress();
});

test("test_create_tool_report_preserves_and_resets_auto_execute_control", async () => {
	const autoExecuteInput = {
		checked: false,
		dataset: { defaultChecked: "true" },
	};
	const autoExecuteControl = { role: "auto-execute-control" };
	const contextElement = { role: "context-upload" };
	const { CreateToolReport } = await esmock.strict(
		"../../src/script/widgets/tools.mjs",
		{
			"../../src/script/elements/base/baseUpload.mjs": {
				BaseUpload: class {
					constructor(attributes) {
						Object.assign(this, attributes);
					}
					reset() {}
				},
			},
			"../../src/script/elements/upload.mjs": {
				UploadMenu: class {},
				uploadElement: {
					contextUpload: () => ({
						element: contextElement,
						dropzone: { show() {} },
						clear() {},
					}),
				},
			},
		},
	);
	const widget = new CreateToolReport({
		target: {
			querySelector(selector) {
				if (selector === "[data-role='auto-execute-control']")
					return autoExecuteControl;
				if (selector === "[name='auto_execute']") return autoExecuteInput;
				return null;
			},
		},
	});
	assert.deepEqual(widget.html, [contextElement, autoExecuteControl]);
	widget._resetUI();
	assert.equal(autoExecuteInput.checked, true);
});
