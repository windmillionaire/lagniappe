import { STYLES } from "../generated/styles.mjs";
import { request } from "../shared/index.ts";
import type Core from "../views/base/core.ts";

type ProjectHeaderView = Pick<Core, "elt" | "key" | "successfulResponse">;

interface ProjectPatchResponse {
	name?: string;
	description?: string;
	fingerprint?: string;
}

function syncProjectMetadata(
	view: ProjectHeaderView,
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

export function startProjectRename(view: ProjectHeaderView) {
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
	input.setAttribute("aria-label", "Project name");
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
			const response = await request.patch<ProjectPatchResponse>(
				`/projects/${view.key}/patch`,
				{
					schema_id: "name",
					value: nextName,
				},
			);
			if (view.successfulResponse(response)) {
				syncProjectMetadata(view, {
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

export function startProjectDescriptionEdit(view: ProjectHeaderView) {
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
	form.dataset.kind = "project";
	form.className = STYLES.page.description.editor;

	const textarea = document.createElement("textarea");
	textarea.name = "description";
	textarea.rows = 1;
	textarea.value = original;
	textarea.placeholder = "Describe this project...";
	textarea.setAttribute("aria-label", "Project description");
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
	saveBtn.dataset.kind = "project";
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
			const response = await request.patch<ProjectPatchResponse>(
				`/projects/${view.key}/patch`,
				{
					schema_id: "description",
					value: trimmed,
				},
			);
			if (view.successfulResponse(response)) {
				syncProjectMetadata(view, {
					description: response?.description ?? trimmed,
					fingerprint: response?.fingerprint,
				});
			}
		} finally {
			close();
		}
	};

	form.addEventListener("submit", (e) => {
		e.preventDefault();
		void save(textarea.value);
	});
	cancelBtn.addEventListener("click", () => {
		close();
	});
	textarea.addEventListener("keydown", (e) => {
		if (e.key === "Escape") {
			e.preventDefault();
			close();
		} else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
			e.preventDefault();
			void save(textarea.value);
		}
	});
}
