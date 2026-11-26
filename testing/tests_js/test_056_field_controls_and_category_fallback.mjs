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
	assert.equal(
		scheduleRow.querySelector(":scope > button[data-role='clear']"),
		null,
		"Open DueDate relies on its chevron toggle instead of an extra Close button",
	);
	scheduleButton.click();
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
	assert.equal(
		uploadRow.querySelector(":scope > button[data-role='clear']"),
		null,
		"Open TaskUpload relies on its chevron toggle instead of an extra Close button",
	);
	uploadButton.click();
	assert.equal(upload.open, false);
	assert.equal(uploadButton.getAttribute("aria-expanded"), "false");

	upload.destroy();
});

test("test_form_fields_click_to_edit_divider_actions_full_width_read_and_lazy_history", async (t) => {
	createBrowser(t, {
		url: "https://lagniappe.test/pages/page-1",
		html: `<form data-widget="TestForm" data-kind="page"></form>`,
	});

	const { InputElement } = await import("../../src/script/elements/input.ts");
	const { RadioElement } = await import("../../src/script/elements/radio.ts");
	const { TableElement } = await import("../../src/script/elements/table.ts");
	const { TodoElement } = await import("../../src/script/elements/todo.ts");
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
	const tableField = new TableElement(
		{ kind: "page", readonly: false },
		{
			id: "table-1",
			type: "table",
			title: "Measurements",
			columns: [{ id: "row-1", type: "input", input: "text", title: "Item" }],
		},
		null,
	);
	const todoField = new TodoElement(
		{ kind: "task", readonly: false },
		{ id: "todo-1", type: "todo", title: "Checklist" },
		{ items: [{ text: "Check brood", checked: false }] },
	);

	class TestFormWidget extends FormWidget {
		get html() {
			return [
				nameField.elt,
				emailField.elt,
				radioField.elt,
				historyField.elt,
				tableField.elt,
				todoField.elt,
			];
		}
	}

	const widget = new TestFormWidget({ target: formElt, name: "TestForm" });
	const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
	try {
		await widget.init();
		const form = widget.target;

		// No form-level Edit all bar is rendered.
		assert.equal(form.querySelector("[data-role='edit-all']"), null);
		assert.equal(form.querySelector("[data-role='edit-all-bar']"), null);

		// Edit action lives in the label row with the existing 'edit' icon, divider hook, and full-width read box.
		const nameElt = form.querySelector("#name");
		const editBtn = nameElt.querySelector(
			"[data-role='label'] [data-role='edit']",
		);
		assert.ok(editBtn, "Edit button should live inside the label row");
		assert.equal(editBtn.getAttribute("aria-label"), "Edit Name");
		assert.ok(editBtn.textContent.includes("Edit"));
		assert.ok(editBtn.classList.contains("form-field-action"));
		assert.equal(
			editBtn.querySelector("[data-icon]")?.dataset.icon,
			"edit",
			"Edit button must keep the existing edit icon",
		);
		const nameRead = nameElt.querySelector("[data-role='read']");
		assert.equal(nameElt.querySelector("[data-role='read-row']"), null);
		assert.ok(
			nameRead.classList.contains("w-full"),
			"Read-mode value box should span full width",
		);

		// Table and Todo header actions also live inside [data-role='label'] with divider hook.
		const addRowBtn = form.querySelector(
			"#table-1 [data-role='label'] [data-role='create']",
		);
		assert.ok(addRowBtn?.classList.contains("form-field-action"));
		const todoEditBtn = form.querySelector(
			"#todo-1 [data-role='label'] [data-role='todo-edit']",
		);
		assert.ok(todoEditBtn?.classList.contains("form-field-action"));

		// Clicking an <a> link inside a read box must not hijack into edit mode.
		const emailElt = form.querySelector("#email");
		const mailLink = emailElt.querySelector("[data-role='read'] a");
		assert.ok(mailLink);
		mailLink.addEventListener("click", (e) => e.preventDefault());
		mailLink.dispatchEvent(
			new MouseEvent("click", { bubbles: true, cancelable: true }),
		);
		await flush();
		assert.equal(emailElt.dataset.mode, "read");

		// Clicking the read value box switches into edit mode and exposes Clear (clear icon) and Close (x icon).
		nameRead.dispatchEvent(
			new MouseEvent("click", { bubbles: true, cancelable: true }),
		);
		await flush();
		assert.equal(nameElt.dataset.mode, "edit");
		const nameClear = nameElt.querySelector(
			"[data-role='label'] [data-role='clear']",
		);
		const nameClose = nameElt.querySelector(
			"[data-role='label'] [data-role='close']",
		);
		assert.ok(nameClear);
		assert.ok(nameClose);
		assert.ok(nameClear.classList.contains("form-field-action"));
		assert.ok(nameClose.classList.contains("form-field-action"));
		assert.equal(nameClear.dataset.kind, "default");
		assert.equal(nameClose.dataset.kind, "default");
		assert.equal(
			nameClear.querySelector("[data-icon]")?.dataset.icon,
			"clear",
			"Form element Clear should use the same clear icon as select clear",
		);
		assert.equal(
			nameClose.querySelector("[data-icon]")?.dataset.icon,
			"x",
			"Form element Close should use the x icon",
		);
		assert.equal(nameClear.hidden, false);
		assert.equal(nameClose.hidden, false);

		// Editing and clicking Close returns to the updated read view.
		const nameInput = nameElt.querySelector("input");
		nameInput.value = "Hive 2";
		nameInput.dispatchEvent(new Event("input", { bubbles: true }));
		nameClose.click();
		await flush();
		assert.equal(nameElt.dataset.mode, "read");
		assert.equal(
			nameElt.querySelector("[data-role='read']")?.textContent,
			"Hive 2",
		);

		// Re-opening edit mode and clearing empties the input and hides both Clear and Close.
		nameElt
			.querySelector("[data-role='read']")
			.dispatchEvent(
				new MouseEvent("click", { bubbles: true, cancelable: true }),
			);
		await flush();
		assert.equal(nameElt.dataset.mode, "edit");
		assert.equal(nameClear.hidden, false);
		assert.equal(nameClose.hidden, false);
		nameClear.click();
		assert.equal(nameInput.value, "");
		assert.equal(nameClear.hidden, true);
		assert.equal(nameClose.hidden, true);

		// Initially-empty radio gets hidden Clear and Close actions that appear once an option is chosen;
		// Close returns a read view with an Edit action, and Clear hides both.
		const radioElt = form.querySelector("#queen");
		const radioClear = radioElt.querySelector(
			"[data-role='label'] [data-role='clear']",
		);
		const radioClose = radioElt.querySelector(
			"[data-role='label'] [data-role='close']",
		);
		assert.ok(radioClear);
		assert.ok(radioClose);
		assert.equal(radioClear.hidden, true);
		assert.equal(radioClose.hidden, true);
		const yesRadio = radioElt.querySelector("input[type='radio'][value='yes']");
		yesRadio.checked = true;
		yesRadio.dispatchEvent(new Event("change", { bubbles: true }));
		assert.equal(radioClear.hidden, false);
		assert.equal(radioClose.hidden, false);
		radioClose.click();
		await flush();
		assert.equal(radioElt.dataset.mode, "read");
		assert.equal(
			radioElt.querySelector("[data-role='read']")?.textContent,
			"Yes",
		);
		assert.ok(
			radioElt.querySelector("[data-role='label'] [data-role='edit']"),
			"Closing an initially-empty field with a value should expose Edit",
		);
		radioElt.querySelector("[data-role='label'] [data-role='edit']").click();
		await flush();
		assert.equal(radioElt.dataset.mode, "edit");
		radioClear.click();
		assert.equal(yesRadio.checked, false);
		assert.equal(radioClear.hidden, true);
		assert.equal(radioClose.hidden, true);

		// History fill stays lazy, sits before Clear in the label row, and restores value.
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
		const varroaLabel = form.querySelector("#varroa [data-role='label']");
		const historyBtn = varroaLabel.querySelector("[data-role='history-fill']");
		const varroaClear = varroaLabel.querySelector("[data-role='clear']");
		assert.ok(historyBtn);
		assert.ok(historyBtn.classList.contains("form-field-action"));
		assert.equal(historyBtn.dataset.kind, "default");
		assert.ok(historyBtn.textContent.includes("Use last"));
		assert.equal(
			Boolean(
				historyBtn.compareDocumentPosition(varroaClear) &
					Node.DOCUMENT_POSITION_FOLLOWING,
			),
			true,
			"Use last should sit before Clear in the label row",
		);
		historyBtn.click();
		assert.equal(fetchCalls, 1);
		assert.ok(historyBtn.textContent.includes("Loading..."));
		resolveHistory("1.2");
		await flush();
		assert.equal(
			form.querySelector("#varroa [data-role='read']")?.textContent,
			"1.2",
		);
		assert.ok(
			form.querySelector("#varroa [data-role='label'] [data-role='edit']"),
			"Restored field should expose Edit in its label row",
		);
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
