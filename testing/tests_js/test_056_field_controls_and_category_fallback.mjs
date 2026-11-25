import assert from "node:assert/strict";
import { test } from "node:test";
import { createBrowser } from "../utility/js/environment.mjs";

test("test_due_date_and_task_upload_open_panels_render_outside_section_toggle_row", async (t) => {
	createBrowser(t, {
		url: "https://lagniappe.test/pages/page-1",
		html: `
			<div class="schedule-wrap">
				<button type="button"
				        data-action="schedule"
				        data-title="Schedule"></button>
			</div>
			<div class="upload-wrap">
				<button type="button"
				        data-action="uploadFile"
				        data-role="file-select"
				        data-title="Attach File/Photo"></button>
			</div>
		`,
	});
	window.matchMedia = () => ({
		matches: false,
		addEventListener() {},
		removeEventListener() {},
	});
	globalThis.IntersectionObserver = class {
		observe() {}
		disconnect() {}
	};

	const { SectionToggle } = await import(
		"../../src/script/elements/sectionToggle.ts"
	);

	const scheduleButton = document.querySelector(
		"button[data-action='schedule']",
	);
	const dueDate = SectionToggle.date({}, scheduleButton);
	dueDate.init();

	const scheduleRow = scheduleButton.parentElement;
	assert.equal(scheduleRow?.dataset.role, "section-toggle-row");
	assert.equal(
		scheduleRow.querySelector("[data-role='date-form']"),
		null,
		"DueDate panel must not be inserted inside the horizontal section-toggle-row",
	);
	assert.equal(
		scheduleRow.nextElementSibling?.dataset.role,
		"date-form",
		"DueDate panel should sit directly after section-toggle-row",
	);

	const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

	scheduleButton.click();
	await flush();
	assert.equal(scheduleButton.getAttribute("aria-expanded"), "true");
	assert.equal(scheduleRow.nextElementSibling?.dataset.visible, "true");
	const scheduleClose = scheduleRow.querySelector(
		":scope > button[data-role='clear']",
	);
	assert.ok(scheduleClose, "Open DueDate should expose sibling Close button");
	scheduleClose.click();
	await flush();
	assert.equal(scheduleButton.getAttribute("aria-expanded"), "false");
	assert.equal(scheduleRow.nextElementSibling?.dataset.visible, "false");

	const uploadButton = document.querySelector(
		"button[data-role='file-select']",
	);
	const upload = SectionToggle.upload({}, uploadButton);
	await upload.init();

	const uploadRow = uploadButton.parentElement;
	assert.equal(uploadRow?.dataset.role, "section-toggle-row");
	assert.equal(
		uploadRow.contains(upload.target),
		false,
		"TaskUpload dropzone must not be inside section-toggle-row",
	);
	assert.equal(uploadRow.nextElementSibling, upload.target);
	assert.equal(uploadButton.getAttribute("aria-expanded"), "false");

	uploadButton.click();
	assert.equal(upload.open, true);
	assert.equal(uploadButton.getAttribute("aria-expanded"), "true");
	const uploadClose = uploadRow.querySelector(
		":scope > button[data-role='clear']",
	);
	assert.ok(uploadClose, "Open TaskUpload should expose sibling Close button");
	uploadClose.click();
	assert.equal(upload.open, false);
	assert.equal(uploadButton.getAttribute("aria-expanded"), "false");

	upload.destroy();
});

test("test_form_fields_click_to_edit_neutral_clear_lazy_history_and_edit_all", async (t) => {
	createBrowser(t, {
		url: "https://lagniappe.test/pages/page-1",
		html: `<form data-widget="TestForm" data-kind="page"></form>`,
	});

	const { InputElement } = await import("../../src/script/elements/input.ts");
	const { RadioElement } = await import("../../src/script/elements/radio.ts");
	const { FormWidget } = await import(
		"../../src/script/widgets/base/formWidget.ts"
	);

	const formElt = document.querySelector("form");
	const nameField = new InputElement(
		{ kind: "page", readonly: false },
		{ id: "name", title: "Name", input: "text" },
		"Magnolia Hive",
	);
	const emailField = new InputElement(
		{ kind: "page", readonly: false },
		{ id: "email", title: "Email", input: "email" },
		"bees@example.com",
	);
	const radioField = new RadioElement(
		{ kind: "page", readonly: false },
		{
			id: "queen",
			title: "Queen Seen",
			options: [
				{ value: "yes", label: "Yes" },
				{ value: "no", label: "No" },
			],
		},
		null,
	);
	const historyField = new InputElement(
		{ kind: "page", readonly: false, historyFillEnabled: true },
		{ id: "varroa", title: "Varroa", input: "text" },
		null,
	);

	class TestFormWidget extends FormWidget {
		get html() {
			return [nameField.elt, emailField.elt, radioField.elt, historyField.elt];
		}
	}

	const widget = new TestFormWidget({ target: formElt, name: "TestForm" });
	const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
	try {
		await widget.init();
		const form = widget.target;

		// Value pill uses existing 'edit' icon beside read pill, and Edit all appears for 2+ read fields.
		const nameElt = form.querySelector("#name");
		const editBtn = nameElt.querySelector("[data-role='edit']");
		assert.ok(editBtn);
		assert.equal(
			editBtn.querySelector("[data-icon]")?.dataset.icon,
			"edit",
			"Edit button beside read pill must keep the existing edit icon",
		);
		const editAllBtn = form.querySelector("[data-role='edit-all']");
		assert.ok(editAllBtn, "Edit all button should appear for 2+ read fields");

		// Clicking an <a> link inside a read pill must not hijack into edit mode.
		const emailElt = form.querySelector("#email");
		const mailLink = emailElt.querySelector("[data-role='read'] a");
		assert.ok(mailLink);
		mailLink.addEventListener("click", (e) => e.preventDefault());
		mailLink.dispatchEvent(
			new MouseEvent("click", { bubbles: true, cancelable: true }),
		);
		await flush();
		assert.equal(emailElt.dataset.mode, "read");

		// Clicking the read value pill itself switches into edit mode and exposes neutral Clear chip.
		nameElt
			.querySelector("[data-role='read']")
			.dispatchEvent(
				new MouseEvent("click", { bubbles: true, cancelable: true }),
			);
		await flush();
		assert.equal(nameElt.dataset.mode, "edit");
		const nameClear = nameElt.querySelector("[data-role='clear']");
		assert.ok(nameClear);
		assert.equal(nameClear.dataset.kind, "default");
		assert.equal(nameClear.hidden, false);
		assert.equal(
			form.querySelector("[data-role='edit-all']"),
			null,
			"Edit all should hide once fewer than 2 read fields remain",
		);

		// Clearing empties the input and hides the Clear chip.
		nameClear.click();
		assert.equal(nameElt.querySelector("input").value, "");
		assert.equal(nameClear.hidden, true);

		// Initially-empty radio gets a hidden Clear chip that appears once an option is chosen.
		const radioElt = form.querySelector("#queen");
		const radioClear = radioElt.querySelector("[data-role='clear']");
		assert.ok(radioClear);
		assert.equal(radioClear.hidden, true);
		const yesRadio = radioElt.querySelector("input[type='radio'][value='yes']");
		yesRadio.checked = true;
		yesRadio.dispatchEvent(new Event("change", { bubbles: true }));
		assert.equal(radioClear.hidden, false);
		radioClear.click();
		assert.equal(yesRadio.checked, false);
		assert.equal(radioClear.hidden, true);

		// History fill chip stays lazy and shows 'Use last' -> 'Loading...' -> restores value.
		let resolveHistory;
		let fetchCalls = 0;
		const added = historyField.addHistoryFill(() => {
			fetchCalls += 1;
			return new Promise((resolve) => {
				resolveHistory = resolve;
			});
		});
		assert.equal(added, true);
		assert.equal(fetchCalls, 0, "History fill must remain lazy until clicked");
		const historyBtn = form.querySelector("#varroa [data-role='history-fill']");
		assert.ok(historyBtn);
		assert.ok(historyBtn.textContent.includes("Use last"));
		historyBtn.click();
		assert.equal(fetchCalls, 1);
		assert.ok(historyBtn.textContent.includes("Loading..."));
		resolveHistory("1.2");
		await flush();
		assert.equal(
			form.querySelector("#varroa [data-role='read']")?.textContent,
			"1.2",
		);

		// Now email + varroa are in read mode (2 read fields): Edit all switches both at once.
		assert.ok(form.querySelector("[data-role='edit-all']"));
		form.querySelector("[data-role='edit-all']").click();
		await flush();
		assert.equal(emailElt.dataset.mode, "edit");
		assert.equal(form.querySelector("#varroa").dataset.mode, "edit");
		assert.equal(form.querySelector("[data-role='edit-all']"), null);
	} finally {
		widget.destroy();
	}
});

test("test_create_page_prepare_submit_honors_or_prompts_unselected_category", async (t) => {
	createBrowser(t, {
		url: "https://lagniappe.test/",
		html: `<form data-widget="CreatePage" data-kind="page"></form>`,
	});

	const { CreatePage } = await import("../../src/script/widgets/pageInfo.ts");

	const formElt = document.querySelector("form");
	const widget = new CreatePage({ target: formElt, name: "CreatePage" });
	let shownError = null;
	let hiddenError = 0;
	let selectedOption = null;
	let panelShown = 0;
	let focused = 0;

	const input = document.createElement("input");
	input.focus = () => {
		focused += 1;
	};
	const panel = document.createElement("div");

	widget.form = {
		_subForm: null,
		showError(msg) {
			shownError = msg;
		},
		hideError() {
			hiddenError += 1;
			shownError = null;
		},
	};
	widget.categorySelect = {
		select: {
			multiple: false,
			creatable: "true",
			element: input,
			panel,
			values: new Set(),
			async _search(query) {
				if (query.toLowerCase() === "lagniappe") {
					panel.innerHTML = `<div role="option" data-id="cat-1" data-name="Lagniappe">Lagniappe</div>`;
				} else {
					panel.innerHTML = `<div role="option" data-command="create" data-name="${query}">Create ${query}</div>`;
				}
			},
			selectOption(opt) {
				selectedOption = opt.dataset.id;
				this.values.add(opt.dataset.id);
				this.element.value = "";
			},
			showPanel() {
				panelShown += 1;
			},
		},
	};

	// 1. Blank category input proceeds cleanly (Uncategorized Pages).
	input.value = "";
	assert.equal(await widget.prepareSubmit(), true);
	assert.equal(shownError, null);
	assert.equal(hiddenError, 1);

	// 2. Typed exact match (case-insensitive) auto-selects and submits.
	input.value = "lagniappe";
	assert.equal(await widget.prepareSubmit(), true);
	assert.equal(selectedOption, "cat-1");
	assert.equal(shownError, null);

	// 3. Typed non-matching text blocks submit, shows inline prompt, and opens dropdown.
	panel.innerHTML = "";
	widget.categorySelect.select.values.clear();
	input.value = "Brand New Cat";
	assert.equal(await widget.prepareSubmit(), false);
	assert.ok(shownError?.includes("Create Brand New Cat"));
	assert.equal(focused, 1);
	assert.equal(panelShown, 1);
});
