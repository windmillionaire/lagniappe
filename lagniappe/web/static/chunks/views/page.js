/*! Third-party licenses: /third-party-licenses.txt */
import { w as withTransition } from '../foundation.js?v=bd163a0f';
import '../connectivity.js?v=bd163a0f';
import { E as Entity } from '../entity-foundation.js?v=bd163a0f';
import '../core-foundation.js?v=bd163a0f';

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_add_image_to_page
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_mobile_photo_prompt_rejoins_section_switching
 * @tests tests_js/test_038_startup_specializations.py::test_page_photo_initializes_only_when_selected_or_visible
 * @matrix pages : image-add mobile-photo-tab photo-lazy-activation photo-prompt photo-visible-startup
 */
class Page extends Entity {
	async init() {
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
		if (this.elt.dataset.secondary !== "true") return null;
		return this.elt.querySelector("#photo");
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity.setAttributeActive
	 * @reason the photo card has attribute state distinct from image/secondary visibility
	 */
	secondaryCardForAttribute(attribute) {
		if (attribute === "photo") return this.elt.querySelector("#photo");
		return super.secondaryCardForAttribute(attribute);
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity._renderLayout
	 * @covered-by src/script/views/base/entity.mjs::Entity.updateLayout
	 * @reason page-specific inactive attribute guard feeds the shared layout renderer
	 */
	_prerender(tabId, secondaryElement = undefined) {
		const tab = this._tabElement(tabId);
		if (tab?.dataset.hasAttribute === "false") {
			tabId = this._defaultTabId;
		}
		return super._prerender(tabId, secondaryElement);
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
