import { FacetsBox } from "../elements/combobox/facets.ts";
import { STYLES } from "../generated/styles.mjs";
import { request } from "../shared/index.ts";
import type EntityIndex from "../views/base/index.ts";

interface PreloadedForm {
	id?: string;
	name?: string;
	hash?: string;
	kind?: string;
}

interface CategoryPatchResponse {
	name?: string;
	description?: string;
	form?: PreloadedForm | null;
	fingerprint?: string;
}

function syncCategoryMetadata(
	view: EntityIndex,
	updates: { name?: string; description?: string; fingerprint?: string },
) {
	if (updates.fingerprint) {
		view.elt.dataset.fingerprint = updates.fingerprint;
	}

	if (updates.name !== undefined) {
		const titleSpan = view.elt.querySelector<HTMLElement>(
			"[data-nav='view'] [data-role='title']",
		);
		if (titleSpan) titleSpan.textContent = updates.name;
		document.title = updates.name;
	}

	if (updates.description !== undefined) {
		const descEl = view.elt.querySelector<HTMLElement>(
			"[data-role='description']",
		);
		if (descEl) {
			if (updates.description) {
				const span = document.createElement("span");
				span.textContent = updates.description;
				descEl.replaceChildren(span);
			} else {
				descEl.replaceChildren();
			}
		}
		const actionLabel = view.elt.querySelector<HTMLElement>(
			"[data-role='description-action-label']",
		);
		if (actionLabel) {
			actionLabel.textContent = updates.description
				? "Edit description"
				: "Add description";
		}
	}
}

export function startCategoryRename(view: EntityIndex) {
	if (view.elt.dataset.canEdit !== "true" || !view.key) return;
	const anchor = view.elt.querySelector<HTMLElement>(
		"[data-nav='view'] [data-menu-anchor]",
	);
	const titleSpan = anchor?.querySelector<HTMLElement>("[data-role='title']");
	if (!anchor || !titleSpan) return;
	if (anchor.querySelector("[data-role='rename-form']")) return;

	const originalName = titleSpan.textContent?.trim() || "";
	const menuWrap = anchor.querySelector<HTMLElement>("[lp-menu='title']");
	titleSpan.hidden = true;
	if (menuWrap) menuWrap.hidden = true;

	const form = document.createElement("form");
	form.dataset.role = "rename-form";
	form.className = STYLES.page.rename.form;

	const input = document.createElement("input");
	input.type = "text";
	input.name = "name";
	input.value = originalName;
	input.setAttribute("aria-label", "Category name");
	input.className = STYLES.page.rename.input;
	form.appendChild(input);

	anchor.appendChild(form);
	input.focus({ preventScroll: true });
	input.select();

	let finished = false;
	const restore = () => {
		form.remove();
		titleSpan.hidden = false;
		if (menuWrap) menuWrap.hidden = false;
	};

	const commit = async () => {
		if (finished) return;
		finished = true;
		const nextName = input.value.trim();
		if (!nextName || nextName === originalName) {
			restore();
			return;
		}
		input.disabled = true;
		try {
			const response = await request.patch<CategoryPatchResponse>(
				`/categories/${view.key}/patch`,
				{
					schema_id: "name",
					value: nextName,
				},
			);
			if (view.successfulResponse(response)) {
				syncCategoryMetadata(view, {
					name: response?.name || nextName,
					fingerprint: response?.fingerprint,
				});
			}
		} finally {
			restore();
		}
	};

	form.addEventListener("submit", (e) => {
		e.preventDefault();
		void commit();
	});
	input.addEventListener("blur", () => {
		void commit();
	});
	input.addEventListener("keydown", (e) => {
		if (e.key === "Escape") {
			e.preventDefault();
			finished = true;
			restore();
		}
	});
}

export function startCategoryDescriptionEdit(view: EntityIndex) {
	if (view.elt.dataset.canEdit !== "true" || !view.key) return;
	const descEl = view.elt.querySelector<HTMLElement>(
		"[data-role='description']",
	);
	if (!descEl) return;
	const existing = view.elt.querySelector<HTMLElement>(
		"[data-role='description-editor']",
	);
	if (existing) {
		existing.querySelector<HTMLTextAreaElement>("textarea")?.focus();
		return;
	}

	const original = descEl.textContent?.trim() || "";
	descEl.hidden = true;

	const form = document.createElement("form");
	form.dataset.role = "description-editor";
	form.dataset.kind = "category";
	form.className = STYLES.page.description.editor;

	const textarea = document.createElement("textarea");
	textarea.name = "description";
	textarea.rows = 1;
	textarea.value = original;
	textarea.placeholder = "Describe this category...";
	textarea.setAttribute("aria-label", "Category description");
	textarea.className = STYLES.page.description.input;
	const autoSize = () => {
		textarea.style.height = "auto";
		if (textarea.scrollHeight > 0) {
			textarea.style.height = `${textarea.scrollHeight}px`;
		}
	};
	textarea.addEventListener("input", autoSize);
	form.appendChild(textarea);

	const actions = document.createElement("div");
	actions.className = STYLES.page.description.actions;

	if (original) {
		const removeBtn = document.createElement("button");
		removeBtn.type = "button";
		removeBtn.dataset.role = "description-remove";
		removeBtn.dataset.kind = "delete";
		removeBtn.className = STYLES.page.description.remove;
		removeBtn.textContent = "Remove";
		removeBtn.addEventListener("click", () => {
			void save("");
		});
		actions.appendChild(removeBtn);
	}

	const buttonGroup = document.createElement("div");
	buttonGroup.className = STYLES.page.description.buttons;

	const cancelBtn = document.createElement("button");
	cancelBtn.type = "button";
	cancelBtn.dataset.role = "description-cancel";
	cancelBtn.className = STYLES.page.description.cancel;
	cancelBtn.textContent = "Cancel";
	buttonGroup.appendChild(cancelBtn);

	const saveBtn = document.createElement("button");
	saveBtn.type = "submit";
	saveBtn.dataset.kind = "category";
	saveBtn.className = STYLES.page.description.save;
	saveBtn.textContent = "Save";
	buttonGroup.appendChild(saveBtn);

	actions.appendChild(buttonGroup);
	form.appendChild(actions);
	descEl.after(form);
	autoSize();
	textarea.focus({ preventScroll: true });
	textarea.setSelectionRange(textarea.value.length, textarea.value.length);

	let busy = false;
	const close = () => {
		form.remove();
		descEl.hidden = false;
	};

	const save = async (nextValue: string) => {
		if (busy) return;
		const trimmed = nextValue.trim();
		if (trimmed === original) {
			close();
			return;
		}
		busy = true;
		textarea.disabled = true;
		form.querySelectorAll("button").forEach((btn) => {
			btn.disabled = true;
		});
		try {
			const response = await request.patch<CategoryPatchResponse>(
				`/categories/${view.key}/patch`,
				{
					schema_id: "description",
					value: trimmed,
				},
			);
			if (view.successfulResponse(response)) {
				syncCategoryMetadata(view, {
					description: response?.description ?? trimmed,
					fingerprint: response?.fingerprint,
				});
			}
		} finally {
			close();
		}
	};

	cancelBtn.addEventListener("click", close);
	form.addEventListener("submit", (e) => {
		e.preventDefault();
		void save(textarea.value);
	});
	textarea.addEventListener("keydown", (e) => {
		if (e.key === "Escape") {
			e.preventDefault();
			close();
		} else if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
			e.preventDefault();
			void save(textarea.value);
		}
	});
}

export function startCategoryDefaultFormEdit(view: EntityIndex) {
	if (
		view.elt.dataset.canEdit !== "true" ||
		view.elt.dataset.canViewForms !== "true" ||
		!view.key
	) {
		return;
	}
	const displayEl = view.elt.querySelector<HTMLElement>(
		"[data-role='default-form']",
	);
	if (!displayEl) return;
	const existing = view.elt.querySelector<HTMLElement>(
		"[data-role='default-form-editor']",
	);
	if (existing) {
		existing.querySelector<HTMLInputElement>("input[type='text']")?.focus();
		return;
	}

	let preloaded: PreloadedForm | null = null;
	if (displayEl.dataset.preload) {
		try {
			preloaded = JSON.parse(displayEl.dataset.preload) as PreloadedForm;
		} catch {
			preloaded = null;
		}
	}
	const originalId = preloaded?.id || "";
	displayEl.hidden = true;

	const form = document.createElement("form");
	form.dataset.role = "default-form-editor";
	form.dataset.kind = "form";
	form.className = STYLES.category.defaultForm.editor;

	const label = document.createElement("span");
	label.className = STYLES.category.defaultForm.label;
	label.textContent = "Default form";
	form.appendChild(label);

	const selectWrap = document.createElement("div");
	selectWrap.className = "grid grid-cols-1";
	selectWrap.dataset.type = "select";
	selectWrap.setAttribute("lp-select", "");

	const input = document.createElement("input");
	input.type = "text";
	input.name = "form";
	input.dataset.index = "form";
	input.dataset.kind = "form";
	input.dataset.multiple = "false";
	input.dataset.creatable = "true";
	input.dataset.formType = "page";
	input.dataset.placeholder = "Select a default page form...";
	input.setAttribute("aria-label", "Default page form");
	input.className = STYLES.select.default;
	if (preloaded?.id) {
		input.dataset.preload = JSON.stringify(preloaded);
	}
	selectWrap.appendChild(input);
	form.appendChild(selectWrap);

	const actions = document.createElement("div");
	actions.className = STYLES.page.description.actions;

	if (originalId) {
		const removeBtn = document.createElement("button");
		removeBtn.type = "button";
		removeBtn.dataset.role = "default-form-remove";
		removeBtn.dataset.kind = "delete";
		removeBtn.className = STYLES.page.description.remove;
		removeBtn.textContent = "Remove";
		removeBtn.addEventListener("click", () => {
			void save("");
		});
		actions.appendChild(removeBtn);
	}

	const buttonGroup = document.createElement("div");
	buttonGroup.className = STYLES.page.description.buttons;

	const cancelBtn = document.createElement("button");
	cancelBtn.type = "button";
	cancelBtn.dataset.role = "default-form-cancel";
	cancelBtn.className = STYLES.page.description.cancel;
	cancelBtn.textContent = "Cancel";
	buttonGroup.appendChild(cancelBtn);

	const saveBtn = document.createElement("button");
	saveBtn.type = "submit";
	saveBtn.dataset.kind = "form";
	saveBtn.className = STYLES.page.description.save;
	saveBtn.textContent = "Save";
	buttonGroup.appendChild(saveBtn);

	actions.appendChild(buttonGroup);
	form.appendChild(actions);
	displayEl.after(form);

	const combobox = new FacetsBox(selectWrap);
	combobox.init();
	input.focus({ preventScroll: true });

	let busy = false;
	const close = () => {
		combobox.destroy();
		form.remove();
	};

	const save = async (nextFormId: string) => {
		if (busy) return;
		if (nextFormId === originalId) {
			close();
			return;
		}
		busy = true;
		form
			.querySelectorAll<HTMLButtonElement | HTMLInputElement>("button, input")
			.forEach((el) => {
				el.disabled = true;
			});
		try {
			const response = await request.patch<CategoryPatchResponse>(
				`/categories/${view.key}/patch`,
				{
					schema_id: "form",
					value: nextFormId || null,
				},
			);
			if (view.successfulResponse(response)) {
				// Reload so table columns, CreatePage default form, and filter fields stay in sync.
				window.location.reload();
				return;
			}
		} finally {
			close();
		}
	};

	cancelBtn.addEventListener("click", close);
	form.addEventListener("submit", (e) => {
		e.preventDefault();
		const selectedValue = Array.from(combobox.values)[0] || "";
		void save(selectedValue);
	});
	form.addEventListener("keydown", (e) => {
		if (e.key === "Escape") {
			e.preventDefault();
			close();
		}
	});
}
