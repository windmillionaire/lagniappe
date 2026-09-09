/*! Third-party licenses: /third-party-licenses.txt */
import { w as withTransition } from '../foundation.js?v=bb100edc';
import '../connectivity.js?v=bb100edc';
import { s as setIcon } from '../icons.js?v=bb100edc';
import { E as Entity } from '../entity-foundation.js?v=bb100edc';
import '../upstreamUnavailable.js?v=bb100edc';
import '../core-foundation.js?v=bb100edc';

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_add_image_to_page
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_mobile_photo_prompt_rejoins_section_switching
 * @tests tests_js/test_038_startup_specializations.py::test_page_photo_initializes_only_when_selected_or_visible
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_photo_controls_toggle_and_remember_desktop_visibility
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_readonly_viewer_can_toggle_image_without_editing
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_photo_prompt_upload_keeps_mobile_photo_tab_hidden_on_desktop
 * @tests tests_e2e/005_pages/test_005c_page_mobile_ui.py::test_page_mobile_flipper_reveals_sections
 * @matrix pages : image-add mobile-photo-tab photo-lazy-activation photo-prompt photo-visible-startup desktop-tabs photo-visibility readonly
 * @matrix entity-layout : flipper page-mobile
 */
class Page extends Entity {
	async init() {
		this.photoHasImage = this.elt.dataset.hasImage === "true";
		this.photoOpen =
			this.photoHasImage &&
			localStorage.getItem(`${this.hash}-photo-visible`) !== "false";
		this.photoToolsOpen = false;
		this.photoGenerationReturnOpen = null;
		this.elt.addEventListener("click", (event) => this._photoClick(event));
		const taskId =
			new URLSearchParams(window.location.search).get("task") ||
			this.elt.dataset.focusTask;
		if (taskId) {
			localStorage.setItem(`${this.hash}-active`, "tasks");
			this.postRender = this._focusTask.bind(this, taskId);
		}

		await super.init();

		const photo = this.elt.querySelector("#photo");
		if (photo) {
			const component = this.getComponent(photo);
			const initiallyVisible =
				component?.active || this.isSecondaryCardVisible(photo);
			if (initiallyVisible && !component.active) {
				await component.activate("PagePhoto");
			}
		}
	}

	get secondaryCard() {
		const available = this.mobile
			? this.photoHasImage || this.photoToolsOpen
			: this.photoOpen;
		if (!available) return null;
		return this.elt.querySelector("#photo");
	}

	_initialTabId() {
		const tabId = super._initialTabId();
		return tabId === "photo" && (!this.mobile || !this.secondaryCard)
			? "info"
			: tabId;
	}

	_tabChange(event) {
		super._tabChange(event);
		if (event.detail.subcomponent.elt.dataset.tab === "true") {
			this._syncPhotoControls(event.detail.subcomponent.name);
		}
	}

	async updateLayout(options = {}) {
		return super.updateLayout({
			secondary: this.elt.querySelector("#photo"),
			secondaryActive: Boolean(this.secondaryCard),
			...options,
		});
	}

	_commitLayoutBody(prepared) {
		const tabId = super._commitLayoutBody(prepared);
		this._syncPhotoControls(tabId);
		return tabId;
	}

	_syncPhotoControls(
		tabId = this.photoActiveTab || this._initialTabId() || "info",
		controls = this.elt.querySelector("[data-role='photo-prompt']"),
	) {
		this.photoActiveTab = tabId;
		if (!controls) return;
		controls.dataset.visible =
			!this.mobile || (!this.photoHasImage && tabId === "info")
				? "true"
				: "false";
		const toggle = controls.querySelector("[data-role='photo-upload']");
		const icon = this.photoHasImage
			? this.photoOpen
				? "visibility.visible"
				: "visibility.hidden"
			: "upload";
		const label = this.photoHasImage
			? this.photoOpen
				? "Hide page image"
				: "Show page image"
			: this.photoOpen
				? "Close image upload"
				: "Upload page image";
		setIcon(toggle.querySelector("[data-icon]"), icon);
		toggle.title = label;
		toggle.setAttribute("aria-label", label);
		toggle.setAttribute("aria-expanded", String(this.photoOpen));
		controls.querySelectorAll("button").forEach((button) => {
			button.disabled = Boolean(this.photoBusy);
		});
		this.elt
			.querySelectorAll("button[lp-show='photo:active']")
			.forEach((button) => {
				// The mobile flipper reveals unselected tabs via data-visible.
				// Keep unavailable image tabs hidden independently of selection.
				button.hidden = !this.photoHasImage && !this.photoToolsOpen;
			});
	}

	setPhotoBusy(busy) {
		this.photoBusy = busy;
		this._syncPhotoControls();
	}

	async _photoClick(event) {
		const button = event.target.closest(
			"[data-role='photo-upload'], [data-role='photo-generate']",
		);
		if (!button || this.photoBusy) return;
		const controls = button.closest("[data-role='photo-prompt']");
		if (!controls) return;
		const error = controls.querySelector("[data-role='photo-prompt-error']");
		error.dataset.visible = "false";
		this.setPhotoBusy(true);
		try {
			const generate = button.dataset.role === "photo-generate";
			const component = this.getComponent(this.elt.querySelector("#photo"));
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
					if (generate)
						component.active.showGenerateForm({ transition: false });
					else component.active?.hideGenerateForm({ transition: false });
				},
			});
		} catch (failure) {
			error.textContent = failure.message || "Unable to show image tools.";
			error.dataset.visible = "true";
		} finally {
			this.setPhotoBusy(false);
		}
	}

	async cancelPhotoGeneration(widget) {
		this.photoOpen = this.photoGenerationReturnOpen ?? this.photoHasImage;
		this.photoToolsOpen = this.photoOpen && !this.photoHasImage;
		this.photoGenerationReturnOpen = null;
		await this.updateLayout({
			activeTabId: this.mobile && !this.secondaryCard ? "info" : null,
			mutate: () => () => widget.hideGenerateForm({ transition: false }),
		});
		this.elt
			.querySelector(
				this.mobile && this.secondaryCard
					? "#photo [data-role='upload-menu']"
					: "[data-role='photo-generate']",
			)
			?.focus();
	}

	async updatePhotoImage(hasImage, mutate) {
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

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005c_page_mobile_ui.py::test_page_mobile_create_task_opens_from_tasks_section
	 * @matrix entity-layout : page-mobile task-create
	 */
	async _focusTask(taskId) {
		const taskTab = this.getComponent(this.elt.querySelector("#tasks"));
		await taskTab.activate("PageTaskList");
		await taskTab.prepareRender(true);
		await withTransition(() => taskTab.render(true), {
			label: "page:focus-task-tab",
		});
		await taskTab.active.focusTask(taskId);
		this._replaceFocusedTaskUrl();
		this.postRender = null;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_route_rewrites_to_page_url_after_focus
	 * @matrix tasks : canonical-url navigation reload
	 */
	_replaceFocusedTaskUrl() {
		const pagePath = this.key ? `/pages/${this.key}` : window.location.pathname;
		history.replaceState(null, "", pagePath);
	}
}

export { Page as default };
