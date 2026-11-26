import { STYLES } from "../generated/styles.mjs";
import { setIcon } from "../shared/icons.ts";
import { withTransition } from "../shared/transitions.ts";
import type { PagePhoto } from "../widgets/pagePhoto.ts";
import type { SubcomponentEvent } from "./base/component.ts";
import Entity, {
	type EntityLayoutOptions,
	type PreparedEntityLayout,
} from "./base/entity.ts";

export default class Page extends Entity {
	declare photoHasImage: boolean;
	declare photoOpen: boolean;
	declare photoToolsOpen: boolean;
	declare photoGenerationReturnOpen: boolean | null;
	declare photoActiveTab?: string;
	declare photoBusy?: boolean;
	declare _taskChannelUnsubscribe?: (() => void) | null;
	declare _pendingTabWidget?: { tabId: string; widget: string } | null;

	async reconcilePollingSubscriptions() {
		await super.reconcilePollingSubscriptions();
		const component = this.components.tasks;
		const list = Object.values(component?.widgets || {}).find(
			(widget) => widget?.name === "PageTaskList" && widget.loaded,
		);
		if (!component || !list || !this.PollingCoordinator) {
			this._taskChannelUnsubscribe?.();
			this._taskChannelUnsubscribe = null;
			return;
		}
		if (this._taskChannelUnsubscribe) return;
		this._taskChannelUnsubscribe = this.PollingCoordinator.subscribe(
			{
				id: `page:tasks:${this.key}`,
				type: "channel",
				channel: "tasks",
				revision: this.elt.dataset.collectionRevision || null,
			},
			{
				mode: "periodic",
				initial: "scheduled",
				onResult: async (result) => {
					if (result.status === "changed") {
						await this._refreshCollectionComponents([component]);
					}
				},
			},
		);
	}

	async init() {
		this.photoHasImage = this.elt.dataset.hasImage === "true";
		this.photoOpen =
			this.photoHasImage &&
			localStorage.getItem(`${this.hash}-photo-visible`) !== "false";
		this.photoToolsOpen = false;
		this.photoGenerationReturnOpen = null;
		this.elt.addEventListener("click", (event) => {
			if (this._handleHeaderClick(event)) return;
			void this._photoClick(event);
		});
		const taskId =
			new URLSearchParams(window.location.search).get("task") ||
			this.elt.dataset.focusTask;
		if (taskId) {
			localStorage.setItem(`${this.hash}-active`, "tasks");
			this.postRender = this._focusTask.bind(this, taskId);
		} else if (this._requestedUserSettings()) {
			this._pendingTabWidget = { tabId: "info", widget: "UserSettings" };
		}

		await super.init();

		if (this._requestedUserSettings()) {
			this._replaceInitialTabUrl();
		}

		const photo = this.elt.querySelector<HTMLElement>("#photo");
		if (photo) {
			const component = this.getComponent(photo);
			const initiallyVisible =
				component?.active || this.isSecondaryCardVisible(photo);
			if (initiallyVisible && component && !component.active) {
				await component.activate("PagePhoto");
			}
		}
	}

	get secondaryCard() {
		const available = this.mobile
			? this.photoHasImage || this.photoToolsOpen
			: this.photoOpen;
		if (!available) return null;
		return this.elt.querySelector<HTMLElement>("#photo");
	}

	_requestedUserSettings() {
		const raw = new URLSearchParams(window.location.search).get("tab")?.trim();
		const requested =
			typeof this.querySlug === "function"
				? this.querySlug(raw)
				: raw?.toLowerCase();
		return (
			(requested === "user-settings" || requested === "settings") &&
			Boolean(this.elt.querySelector("form[data-widget='UserSettings']"))
		);
	}

	_initialTabId() {
		if (this._pendingTabWidget) return this._pendingTabWidget.tabId;
		const tabId = super._initialTabId();
		return tabId === "photo" && (!this.mobile || !this.secondaryCard)
			? "info"
			: tabId;
	}

	_initialTabWidget(tabId: string) {
		if (this._pendingTabWidget?.tabId === tabId) {
			const { widget } = this._pendingTabWidget;
			this._pendingTabWidget = null;
			return widget;
		}
		return super._initialTabWidget(tabId);
	}

	_replaceInitialTabUrl() {
		const url = new URL(window.location.href);
		url.searchParams.delete("tab");
		const next = `${url.pathname}${url.search}${url.hash}`;
		window.history.replaceState(null, "", next);
	}

	_tabChange(event: SubcomponentEvent) {
		super._tabChange(event);
		if (event.detail.subcomponent.elt.dataset.tab === "true") {
			this._syncPhotoControls(event.detail.subcomponent.name);
		}
	}

	async updateLayout(options: EntityLayoutOptions = {}) {
		return super.updateLayout({
			secondary: this.elt.querySelector<HTMLElement>("#photo"),
			secondaryActive: Boolean(this.secondaryCard),
			...options,
		});
	}

	_commitLayoutBody(prepared: PreparedEntityLayout) {
		const tabId = super._commitLayoutBody(prepared);
		this._syncPhotoControls(tabId);
		return tabId;
	}

	_syncPhotoControls(
		tabId = this.photoActiveTab || this._initialTabId() || "info",
		controls = this.elt.querySelector<HTMLElement>(
			"[data-role='photo-prompt']",
		),
	) {
		this.photoActiveTab = tabId;
		if (!controls) return;
		controls.dataset.visible =
			!this.mobile || tabId === "info" ? "true" : "false";

		const emptyActions = controls.querySelector<HTMLElement>(
			"[data-role='photo-empty-actions']",
		);
		const existingActions = controls.querySelector<HTMLElement>(
			"[data-role='photo-existing-actions']",
		);
		if (emptyActions) {
			emptyActions.dataset.visible = String(!this.photoHasImage);
		}
		if (existingActions) {
			existingActions.dataset.visible = String(this.photoHasImage);
		}

		const uploadBtn = controls.querySelector<HTMLButtonElement>(
			"[data-role='photo-upload']",
		);
		if (uploadBtn) {
			const uploadLabel = this.photoOpen
				? "Close image upload"
				: "Upload image";
			uploadBtn.title = uploadLabel;
			uploadBtn.setAttribute("aria-label", uploadLabel);
			uploadBtn.setAttribute("aria-expanded", String(this.photoOpen));
		}

		const toggle = controls.querySelector<HTMLButtonElement>(
			"[data-role='photo-toggle']",
		);
		if (toggle) {
			const icon = this.photoOpen ? "visibility.visible" : "visibility.hidden";
			const label = this.photoOpen ? "Hide image" : "Show image";
			const iconElement = toggle.querySelector<HTMLElement>("[data-icon]");
			if (iconElement) setIcon(iconElement, icon);
			const textElement = toggle.querySelector<HTMLElement>(
				"[data-role='photo-toggle-label']",
			);
			if (textElement) textElement.textContent = label;
			toggle.title = label;
			toggle.setAttribute("aria-label", label);
			toggle.setAttribute("aria-expanded", String(this.photoOpen));
		}

		controls.querySelectorAll("button").forEach((button) => {
			button.disabled = Boolean(this.photoBusy);
		});
		this.elt
			.querySelectorAll<HTMLButtonElement>("button[lp-show='photo:active']")
			.forEach((button) => {
				// The mobile flipper reveals unselected tabs via data-visible.
				// Keep unavailable image tabs hidden independently of selection.
				button.hidden = !this.photoHasImage && !this.photoToolsOpen;
			});
	}

	setPhotoBusy(busy: boolean) {
		this.photoBusy = busy;
		this._syncPhotoControls();
	}

	_handleHeaderClick(event: MouseEvent): boolean {
		const target = event.target as Element | null;
		if (!target?.closest) return false;

		const pageAction = target.closest<HTMLElement>("[data-page-action]");
		if (pageAction?.dataset.pageAction && this.elt.contains(pageAction)) {
			const action = pageAction.dataset.pageAction;
			event.preventDefault();
			event.stopPropagation();
			if (action === "rename") {
				this.startRename();
				return true;
			}
			if (action === "description") {
				this.startDescriptionEdit();
				return true;
			}
		}

		const editableDescription = target.closest<HTMLElement>(
			"[data-role='description'][data-editable='true']",
		);
		if (
			editableDescription &&
			this.elt.contains(editableDescription) &&
			!target.closest("a, button, input, textarea, form")
		) {
			event.preventDefault();
			event.stopPropagation();
			this.startDescriptionEdit();
			return true;
		}

		return false;
	}

	_syncPageMetadata(updates: { name?: string; description?: string }) {
		const pageInfoForm = this.elt.querySelector<HTMLElement>(
			"form[data-widget='PageInfo']",
		);
		const infoWidget = this.components.info?.widgets.PageInfo as
			| { initialTarget?: HTMLElement | null }
			| undefined;

		if (updates.name !== undefined) {
			const titleSpan = this.elt.querySelector<HTMLElement>(
				"[data-nav='view'] [data-role='title']",
			);
			if (titleSpan) titleSpan.textContent = updates.name;
			document.title = updates.name;
			if (pageInfoForm) pageInfoForm.dataset.name = updates.name;
			if (infoWidget?.initialTarget) {
				infoWidget.initialTarget.dataset.name = updates.name;
			}
		}

		if (updates.description !== undefined) {
			const descEl = this.elt.querySelector<HTMLElement>(
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
			const actionLabel = this.elt.querySelector<HTMLElement>(
				"[data-role='description-action-label']",
			);
			if (actionLabel) {
				actionLabel.textContent = updates.description
					? "Edit description"
					: "Add description";
			}
			if (pageInfoForm) {
				if (updates.description) {
					pageInfoForm.dataset.description = updates.description;
				} else {
					delete pageInfoForm.dataset.description;
				}
			}
			if (infoWidget?.initialTarget) {
				if (updates.description) {
					infoWidget.initialTarget.dataset.description = updates.description;
				} else {
					delete infoWidget.initialTarget.dataset.description;
				}
			}
		}
	}

	startRename() {
		if (this.elt.dataset.canRename !== "true") return;
		const anchor = this.elt.querySelector<HTMLElement>(
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
		input.setAttribute("aria-label", "Page name");
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
				const { request } = await import("../shared/index.ts");
				const response = await request.patch(`/pages/${this.key}/patch`, {
					schema_id: "name",
					value: nextName,
				});
				if (this.successfulResponse(response)) {
					this._syncPageMetadata({ name: nextName });
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

	startDescriptionEdit() {
		if (this.elt.dataset.canEdit !== "true") return;
		const descEl = this.elt.querySelector<HTMLElement>(
			"[data-role='description']",
		);
		if (!descEl) return;
		const existing = this.elt.querySelector<HTMLElement>(
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
		form.dataset.kind = "page";
		form.className = STYLES.page.description.editor;

		const textarea = document.createElement("textarea");
		textarea.name = "description";
		textarea.rows = 1;
		textarea.value = original;
		textarea.placeholder = "Describe this page...";
		textarea.setAttribute("aria-label", "Page description");
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
		saveBtn.dataset.kind = "page";
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
				const { request } = await import("../shared/index.ts");
				const response = await request.patch(`/pages/${this.key}/patch`, {
					schema_id: "description",
					value: trimmed,
				});
				if (this.successfulResponse(response)) {
					this._syncPageMetadata({ description: trimmed });
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

	async _photoClick(event: MouseEvent) {
		const target = event.target as Element | null;
		const photoActionBtn = target?.closest?.<HTMLButtonElement>(
			"[data-photo-action]",
		);
		if (photoActionBtn && this.elt.contains(photoActionBtn)) {
			if (this.photoBusy) return;
			const action = photoActionBtn.dataset.photoAction;
			const controls = photoActionBtn.closest("[data-role='photo-prompt']");
			const error = controls?.querySelector<HTMLElement>(
				"[data-role='photo-prompt-error']",
			);
			if (error) error.dataset.visible = "false";

			const component = this.getComponent(
				this.elt.querySelector<HTMLElement>("#photo"),
			);
			if (!component) return;

			if (action === "generate") {
				this.setPhotoBusy(true);
				try {
					await component.activate("PagePhoto");
					this.photoGenerationReturnOpen ??= this.photoOpen;
					this.photoOpen = true;
					this.photoToolsOpen = !this.photoHasImage;
					await this.updateLayout({
						activeTabId: this.mobile ? "photo" : null,
						mutate: () => () => {
							const photo = component.active as PagePhoto | null;
							photo?.showGenerateForm({ transition: false });
						},
					});
				} catch (failure) {
					if (error) {
						error.textContent =
							(failure instanceof Error && failure.message) ||
							"Unable to show image tools.";
						error.dataset.visible = "true";
					}
				} finally {
					this.setPhotoBusy(false);
				}
				return;
			}

			try {
				await component.activate("PagePhoto");
				const photo = component.active as PagePhoto | null;
				if (!photo) return;
				if (action === "replace") {
					photo.replaceFile();
				} else if (action === "paste") {
					await photo.processPaste();
				} else if (action === "remove") {
					photo.removeFile();
				}
			} catch (failure) {
				if (error) {
					error.textContent =
						(failure instanceof Error && failure.message) ||
						"Unable to update page image.";
					error.dataset.visible = "true";
				}
			}
			return;
		}

		const button = target?.closest?.<HTMLButtonElement>(
			"[data-role='photo-upload'], [data-role='photo-toggle'], [data-role='photo-generate']",
		);
		if (!button || this.photoBusy) return;
		const controls = button.closest("[data-role='photo-prompt']");
		if (!controls) return;
		const error = controls.querySelector<HTMLElement>(
			"[data-role='photo-prompt-error']",
		);
		if (!error) return;
		error.dataset.visible = "false";
		this.setPhotoBusy(true);
		try {
			const generate = button.dataset.role === "photo-generate";
			const component = this.getComponent(
				this.elt.querySelector<HTMLElement>("#photo"),
			);
			if (!component) return;
			const open = generate || this.mobile || !this.photoOpen;
			if (open) await component.activate("PagePhoto");
			if (generate) this.photoGenerationReturnOpen ??= this.photoOpen;
			this.photoOpen = open;
			this.photoToolsOpen = open && !this.photoHasImage;
			if (!generate && this.photoHasImage) {
				localStorage.setItem(`${this.hash}-photo-visible`, String(open));
			}
			await this.updateLayout({
				activeTabId: this.mobile ? "photo" : null,
				mutate: () => () => {
					const photo = component.active as PagePhoto | null;
					if (generate) photo?.showGenerateForm({ transition: false });
					else photo?.hideGenerateForm({ transition: false });
				},
			});
		} catch (failure) {
			error.textContent =
				(failure instanceof Error && failure.message) ||
				"Unable to show image tools.";
			error.dataset.visible = "true";
		} finally {
			this.setPhotoBusy(false);
		}
	}

	async cancelPhotoGeneration(widget: Pick<PagePhoto, "hideGenerateForm">) {
		this.photoOpen = this.photoGenerationReturnOpen ?? this.photoHasImage;
		this.photoToolsOpen = this.photoOpen && !this.photoHasImage;
		this.photoGenerationReturnOpen = null;
		await this.updateLayout({
			activeTabId: this.mobile && !this.secondaryCard ? "info" : null,
			mutate: () => () => widget.hideGenerateForm({ transition: false }),
		});
		this.elt
			.querySelector<HTMLElement>(
				this.photoHasImage
					? "[data-photo-menu='true']"
					: "[data-role='photo-generate']",
			)
			?.focus();
	}

	async updatePhotoImage(hasImage: boolean, mutate: () => void) {
		this.photoHasImage = hasImage;
		this.photoOpen = hasImage;
		this.photoToolsOpen = false;
		this.photoGenerationReturnOpen = null;
		localStorage.setItem(`${this.hash}-photo-visible`, String(hasImage));
		await this.updateLayout({
			activeTabId: !hasImage && this.mobile ? "info" : null,
			mutate: () => () => {
				mutate();
				this.elt.dataset.hasImage = String(hasImage);
			},
		});
	}

	async _focusTask(taskId: string) {
		const taskTab = this.getComponent(this.elt.querySelector("#tasks"));
		if (!taskTab) return;
		await taskTab.activate("PageTaskList");
		await taskTab.prepareRender(true);
		await withTransition(() => taskTab.render(true), {
			label: "page:focus-task-tab",
		});
		await taskTab.widgets.PageTaskList?.focusTask(taskId);
		this._replaceFocusedTaskUrl();
		this.postRender = null;
	}

	_replaceFocusedTaskUrl() {
		const pagePath = this.key ? `/pages/${this.key}` : window.location.pathname;
		history.replaceState(null, "", pagePath);
	}
}
